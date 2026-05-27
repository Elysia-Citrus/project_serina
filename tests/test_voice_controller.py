from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.coordinator import Coordinator
from src.app.main_voice import _apply_cli_overrides
from src.config.loader import VoiceConfig
from src.dialogue.engine import DialogueEngine
from src.memory.manager import MemoryManager
from src.voice.controller import VoiceSessionController
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.microphone_stream import AudioChunk
from src.voice.models import (
    ASRResult,
    AudioChunkLike,
    PlaybackResult,
    RecordedAudio,
    SpeechSynthesisResult,
    SpeechSynthesisStreamResult,
    SynthesizedAudio,
)
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


def _make_wav_bytes(duration_ms: int = 120, sample_rate: int = 16000) -> bytes:
    frame_count = max(1, int(sample_rate * duration_ms / 1000))
    frames = b"\x00\x00" * frame_count
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return buffer.getvalue()


class FakeRecorder:
    def __init__(self, recorded_audio: RecordedAudio | Exception) -> None:
        self.recorded_audio = recorded_audio
        self.calls = 0

    def capture_to_wav(self) -> RecordedAudio:
        self.calls += 1
        if isinstance(self.recorded_audio, Exception):
            raise self.recorded_audio
        return self.recorded_audio

    def open_chunk_source(self):  # type: ignore[no-untyped-def]
        raise AssertionError("This fake recorder does not provide chunk streaming.")


class EndpointRecorder(FakeRecorder):
    def __init__(self, chunks: list[AudioChunk]) -> None:
        super().__init__(
            VoicePipelineError(
                VoiceErrorStage.RECORDING,
                "capture_to_wav should not be used",
            )
        )
        self.chunks = chunks

    def open_chunk_source(self):  # type: ignore[no-untyped-def]
        recorder = self

        class _ChunkSource:
            def iter_chunks(self_nonlocal):  # type: ignore[no-untyped-def]
                recorder.calls += 1
                for chunk in recorder.chunks:
                    yield chunk

        return _ChunkSource()


class FakeASR:
    def __init__(self, result: ASRResult | Exception) -> None:
        self.result = result
        self.calls = 0

    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeSpeechService:
    def __init__(
        self,
        result: SpeechSynthesisResult | Exception | None = None,
        *,
        is_enabled: bool = True,
        requested_profile_id: str | None = "serina_main",
    ) -> None:
        self.result = result
        self.stream_result: SpeechSynthesisStreamResult | Exception | None = None
        self.is_enabled = is_enabled
        self.requested_profile_id = requested_profile_id
        self.calls = 0
        self.stream_calls = 0
        self.requests: list[dict[str, str | None]] = []

    def get_requested_profile_id(self, profile_id: str | None = None) -> str | None:
        if not self.is_enabled:
            return None
        return profile_id or self.requested_profile_id

    def synthesize_reply(
        self,
        reply_text: str,
        scene: str,
        profile_id: str | None = None,
    ) -> SpeechSynthesisResult:
        self.calls += 1
        self.requests.append(
            {
                "reply_text": reply_text,
                "scene": scene,
                "profile_id": profile_id,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        assert self.result is not None
        return self.result

    def synthesize_reply_stream(
        self,
        reply_text: str,
        scene: str,
        profile_id: str | None = None,
    ) -> SpeechSynthesisStreamResult | None:
        self.stream_calls += 1
        if isinstance(self.stream_result, Exception):
            raise self.stream_result
        return self.stream_result


class FakePlayback:
    def __init__(self, latency_ms: int = 180, error: Exception | None = None) -> None:
        self.latency_ms = latency_ms
        self.error = error
        self.calls = 0
        self.stream_calls = 0

    def play(
        self,
        synthesized_audio: SynthesizedAudio,
        *,
        output_device: str | int | None = None,
        interrupt_token=None,
    ) -> PlaybackResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return PlaybackResult(
            latency_ms=self.latency_ms,
            first_chunk_latency_ms=0,
            chunk_count=1,
        )

    def play_stream(
        self,
        audio_chunks,
        *,
        output_device: str | int | None = None,
        interrupt_token=None,
    ) -> PlaybackResult:
        self.stream_calls += 1
        if self.error is not None:
            raise self.error
        return PlaybackResult(
            latency_ms=self.latency_ms,
            first_chunk_latency_ms=35,
            chunk_count=len(list(audio_chunks)),
            streamed=True,
        )

    def stop(self, reason: str = "interrupt") -> None:
        return None


class DummyCommandRouter:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[str] = []

    def route(self, user_input: str):  # type: ignore[no-untyped-def]
        from src.app.command_router import CommandRouteResult

        self.calls.append(user_input)
        return CommandRouteResult(handled=True, output_text=self.output_text, success=True)


class VoiceControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def _build_voice_config(self, *, debug_save_input_audio: bool = False) -> VoiceConfig:
        app_config = build_test_config(self.workspace.db_path)
        return replace(
            app_config.voice,
            enabled=True,
            temp_audio_dir=str(self.workspace.root),
            debug_save_input_audio=debug_save_input_audio,
        )

    def _build_controller(
        self,
        *,
        voice_config: VoiceConfig,
        recorder,
        asr_provider,
        speech_service,
        playback,
        command_router=None,
        gateway_scripts: list[str] | None = None,
    ) -> tuple[VoiceSessionController, DummyGateway]:
        app_config = build_test_config(self.workspace.db_path)
        memory_manager = MemoryManager.from_app_config(app_config)
        gateway = DummyGateway(gateway_scripts or ["I am here."])
        engine = DialogueEngine(app_config, gateway, memory_manager=memory_manager)
        coordinator = Coordinator(app_config, engine=engine)
        controller = VoiceSessionController(
            config=voice_config,
            coordinator=coordinator,
            recorder=recorder,
            asr_provider=asr_provider,
            speech_service=speech_service,
            playback=playback,
            command_router=command_router,
        )
        return controller, gateway

    def test_voice_turn_runs_through_existing_text_pipeline(self) -> None:
        input_path = self.workspace.root / "input.wav"
        input_path.write_bytes(_make_wav_bytes())
        recorded_audio = RecordedAudio(
            file_path=str(input_path),
            sample_rate=16000,
            channels=1,
            duration_ms=500,
            frame_count=8000,
        )
        voice_config = self._build_voice_config()
        speech_service = FakeSpeechService(
            SpeechSynthesisResult(
                synthesized_audio=SynthesizedAudio(
                    audio_bytes=_make_wav_bytes(),
                    provider_name="mock-tts",
                    model_name="mock-tts-model",
                    latency_ms=110,
                ),
                speech_text="I am here.",
                style_id="default",
                applied_rules=("normalize_whitespace",),
                voice_profile_id="serina_main",
            )
        )
        controller, gateway = self._build_controller(
            voice_config=voice_config,
            recorder=FakeRecorder(recorded_audio),
            asr_provider=FakeASR(
                ASRResult(
                    text="continue the plan",
                    provider_name="mock-asr",
                    model_name="mock-asr-model",
                    latency_ms=90,
                )
            ),
            speech_service=speech_service,
            playback=FakePlayback(latency_ms=220),
            gateway_scripts=["I am here."],
        )

        result = controller.run_voice_turn()

        self.assertTrue(result.success)
        self.assertEqual(result.source_channel, "voice")
        self.assertEqual(result.transcript_text, "continue the plan")
        self.assertEqual(result.reply_text, "I am here.")
        self.assertTrue(result.speech_played)
        self.assertFalse(result.streaming_playback_used)
        self.assertEqual(result.asr_provider, "mock-asr")
        self.assertEqual(result.tts_provider, "mock-tts")
        self.assertEqual(result.playback_latency_ms, 220)
        self.assertEqual(result.voice_profile_id, "serina_main")
        self.assertEqual(result.style_id, "default")
        self.assertEqual(result.speech_render_rules, ("normalize_whitespace",))
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(speech_service.requests[0]["reply_text"], "I am here.")
        self.assertEqual(speech_service.requests[0]["scene"], "casual_chat")
        self.assertFalse(input_path.exists())

    def test_speech_service_failure_degrades_but_keeps_text_reply(self) -> None:
        input_path = self.workspace.root / "input.wav"
        input_path.write_bytes(_make_wav_bytes())
        recorded_audio = RecordedAudio(
            file_path=str(input_path),
            sample_rate=16000,
            channels=1,
            duration_ms=400,
            frame_count=6400,
        )
        voice_config = self._build_voice_config()
        controller, gateway = self._build_controller(
            voice_config=voice_config,
            recorder=FakeRecorder(recorded_audio),
            asr_provider=FakeASR(
                ASRResult(
                    text="help me plan the voice path",
                    provider_name="mock-asr",
                    model_name="mock-asr-model",
                    latency_ms=70,
                )
            ),
            speech_service=FakeSpeechService(
                VoicePipelineError(
                    VoiceErrorStage.SPEAKING,
                    "TTS provider is unavailable.",
                )
            ),
            playback=FakePlayback(),
            gateway_scripts=["Hook up the minimal voice path first."],
        )

        result = controller.run_voice_turn()

        self.assertTrue(result.success)
        self.assertEqual(result.reply_text, "Hook up the minimal voice path first.")
        self.assertFalse(result.speech_played)
        self.assertEqual(result.error_stage, VoiceErrorStage.SPEAKING.value)
        self.assertEqual(result.voice_profile_id, "serina_main")
        self.assertEqual(len(gateway.calls), 1)

    def test_empty_asr_result_stops_before_coordinator(self) -> None:
        input_path = self.workspace.root / "input.wav"
        input_path.write_bytes(_make_wav_bytes())
        recorded_audio = RecordedAudio(
            file_path=str(input_path),
            sample_rate=16000,
            channels=1,
            duration_ms=300,
            frame_count=4800,
        )
        voice_config = self._build_voice_config()
        controller, gateway = self._build_controller(
            voice_config=voice_config,
            recorder=FakeRecorder(recorded_audio),
            asr_provider=FakeASR(
                ASRResult(
                    text="   ",
                    provider_name="mock-asr",
                    model_name="mock-asr-model",
                    latency_ms=60,
                )
            ),
            speech_service=FakeSpeechService(
                SpeechSynthesisResult(
                    synthesized_audio=SynthesizedAudio(
                        audio_bytes=_make_wav_bytes(),
                        provider_name="mock-tts",
                        model_name="mock-tts-model",
                        latency_ms=80,
                    ),
                    speech_text="unused",
                    style_id="default",
                    voice_profile_id="serina_main",
                )
            ),
            playback=FakePlayback(),
        )

        result = controller.run_voice_turn()

        self.assertFalse(result.success)
        self.assertIsNone(result.reply_text)
        self.assertEqual(result.error_stage, VoiceErrorStage.TRANSCRIBING.value)
        self.assertEqual(len(gateway.calls), 0)

    def test_unexpected_asr_runtime_error_returns_failure_without_raising(self) -> None:
        input_path = self.workspace.root / "input.wav"
        input_path.write_bytes(_make_wav_bytes())
        recorded_audio = RecordedAudio(
            file_path=str(input_path),
            sample_rate=16000,
            channels=1,
            duration_ms=300,
            frame_count=4800,
        )
        controller, gateway = self._build_controller(
            voice_config=self._build_voice_config(),
            recorder=FakeRecorder(recorded_audio),
            asr_provider=FakeASR(RuntimeError("ASR crashed")),
            speech_service=FakeSpeechService(
                SpeechSynthesisResult(
                    synthesized_audio=SynthesizedAudio(
                        audio_bytes=_make_wav_bytes(),
                        provider_name="unused",
                        model_name="unused",
                        latency_ms=0,
                    ),
                    speech_text="unused",
                    style_id="default",
                    voice_profile_id="serina_main",
                )
            ),
            playback=FakePlayback(),
        )

        result = controller.run_voice_turn()

        self.assertFalse(result.success)
        self.assertEqual(result.error_stage, VoiceErrorStage.TRANSCRIBING.value)
        self.assertIn("RuntimeError", result.error_message or "")
        self.assertEqual(len(gateway.calls), 0)
        self.assertFalse(input_path.exists())

    def test_handle_console_input_returns_failure_for_unexpected_asr_value_error(self) -> None:
        input_path = self.workspace.root / "input.wav"
        input_path.write_bytes(_make_wav_bytes())
        recorded_audio = RecordedAudio(
            file_path=str(input_path),
            sample_rate=16000,
            channels=1,
            duration_ms=300,
            frame_count=4800,
        )
        controller, gateway = self._build_controller(
            voice_config=self._build_voice_config(),
            recorder=FakeRecorder(recorded_audio),
            asr_provider=FakeASR(ValueError("bad ASR payload")),
            speech_service=FakeSpeechService(is_enabled=False),
            playback=FakePlayback(),
        )

        result = controller.handle_console_input("")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result.success)
        self.assertEqual(result.error_stage, VoiceErrorStage.TRANSCRIBING.value)
        self.assertIn("ValueError", result.error_message or "")
        self.assertEqual(len(gateway.calls), 0)

    def test_no_tts_cli_override_disables_speech_without_changing_default_config(self) -> None:
        app_config = build_test_config(self.workspace.db_path)

        overridden = _apply_cli_overrides(app_config, {"--no-tts"})

        self.assertNotEqual(app_config.voice.tts_provider, "none")
        self.assertEqual(overridden.voice.tts_provider, "none")
        self.assertFalse(overridden.voice.stream_playback_enabled)
        self.assertFalse(overridden.voice.tts_warmup_on_boot)

    def test_handle_console_input_routes_typed_commands(self) -> None:
        voice_config = self._build_voice_config()
        controller, gateway = self._build_controller(
            voice_config=voice_config,
            recorder=FakeRecorder(
                VoicePipelineError(VoiceErrorStage.RECORDING, "not used")
            ),
            asr_provider=FakeASR(
                VoicePipelineError(VoiceErrorStage.TRANSCRIBING, "not used")
            ),
            speech_service=FakeSpeechService(
                SpeechSynthesisResult(
                    synthesized_audio=SynthesizedAudio(
                        audio_bytes=_make_wav_bytes(),
                        provider_name="mock-tts",
                        model_name="mock-tts-model",
                        latency_ms=80,
                    ),
                    speech_text="unused",
                    style_id="default",
                    voice_profile_id="serina_main",
                )
            ),
            playback=FakePlayback(),
            command_router=DummyCommandRouter("memory list output"),
        )

        result = controller.handle_console_input("/memory list")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.command_handled)
        self.assertEqual(result.command_output_text, "memory list output")
        self.assertEqual(len(gateway.calls), 0)

    def test_handle_console_input_lists_voice_devices(self) -> None:
        voice_config = self._build_voice_config()
        controller, gateway = self._build_controller(
            voice_config=voice_config,
            recorder=FakeRecorder(
                VoicePipelineError(VoiceErrorStage.RECORDING, "not used")
            ),
            asr_provider=FakeASR(
                VoicePipelineError(VoiceErrorStage.TRANSCRIBING, "not used")
            ),
            speech_service=FakeSpeechService(
                SpeechSynthesisResult(
                    synthesized_audio=SynthesizedAudio(
                        audio_bytes=_make_wav_bytes(),
                        provider_name="mock-tts",
                        model_name="mock-tts-model",
                        latency_ms=80,
                    ),
                    speech_text="unused",
                    style_id="default",
                    voice_profile_id="serina_main",
                )
            ),
            playback=FakePlayback(),
        )

        with patch(
            "src.voice.controller.describe_audio_devices",
            return_value="Available input devices:\n[0] USB Mic",
        ):
            result = controller.handle_console_input("/voice devices")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.command_handled)
        self.assertEqual(
            result.command_output_text,
            "Available input devices:\n[0] USB Mic",
        )
        self.assertEqual(len(gateway.calls), 0)

    def test_endpoint_once_records_until_final_and_can_skip_speech(self) -> None:
        voice_config = replace(
            self._build_voice_config(),
            recording_mode="endpoint_once",
            chunk_ms=100,
            silence_timeout_s=0.2,
            min_speech_s=0.2,
            silence_rms_threshold=300,
            tts_provider="none",
        )
        silent = AudioChunk(
            audio_bytes=b"\x00\x00" * 1600,
            sample_rate=16000,
            channels=1,
            chunk_ms=100,
            rms=0,
        )
        speech = AudioChunk(
            audio_bytes=b"\x01\x00" * 1600,
            sample_rate=16000,
            channels=1,
            chunk_ms=100,
            rms=800,
        )
        status_messages: list[str] = []
        controller, gateway = self._build_controller(
            voice_config=voice_config,
            recorder=EndpointRecorder([silent, speech, speech, silent, silent]),
            asr_provider=FakeASR(
                ASRResult(
                    text="connect the local voice loop",
                    provider_name="mock-local-asr",
                    model_name="mock-local-model",
                    latency_ms=55,
                )
            ),
            speech_service=FakeSpeechService(
                is_enabled=False,
                result=SpeechSynthesisResult(
                    synthesized_audio=SynthesizedAudio(
                        audio_bytes=_make_wav_bytes(),
                        provider_name="unused",
                        model_name="unused",
                        latency_ms=0,
                    ),
                    speech_text="unused",
                    style_id="default",
                    voice_profile_id="unused",
                ),
            ),
            playback=FakePlayback(),
            gateway_scripts=["Already connected."],
        )
        controller.status_callback = status_messages.append

        result = controller.run_voice_turn()

        self.assertTrue(result.success)
        self.assertEqual(result.transcript_text, "connect the local voice loop")
        self.assertEqual(result.reply_text, "Already connected.")
        self.assertFalse(result.speech_played)
        self.assertEqual(result.tts_provider, "none")
        self.assertIsNone(result.voice_profile_id)
        self.assertGreaterEqual(len(status_messages), 2)
        self.assertIn("[voice] Listening...", status_messages[0])
        self.assertEqual(len(gateway.calls), 1)

    def test_streaming_playback_prefers_stream_path(self) -> None:
        voice_config = self._build_voice_config()
        speech_service = FakeSpeechService(
            SpeechSynthesisResult(
                synthesized_audio=SynthesizedAudio(
                    audio_bytes=_make_wav_bytes(),
                    provider_name="unused-full",
                    model_name="unused-full-model",
                    latency_ms=80,
                ),
                speech_text="unused",
                style_id="default",
                voice_profile_id="serina_main",
            )
        )
        speech_service.stream_result = SpeechSynthesisStreamResult(
            audio_chunks=(
                AudioChunkLike(
                    audio_bytes=_make_wav_bytes(),
                    provider_name="cosyvoice_local",
                    model_name="cosyvoice-local-primary",
                    sequence_index=0,
                ),
                AudioChunkLike(
                    audio_bytes=_make_wav_bytes(),
                    provider_name="cosyvoice_local",
                    model_name="cosyvoice-local-primary",
                    sequence_index=1,
                    is_final=True,
                ),
            ),
            provider_name="cosyvoice_local",
            model_name="cosyvoice-local-primary",
            speech_text="先接上本地运行时。然后再接克隆链路。",
            style_id="discussion",
            applied_rules=("normalize_whitespace",),
            voice_profile_id="serina_main",
        )
        playback = FakePlayback(latency_ms=260)
        controller, gateway = self._build_controller(
            voice_config=voice_config,
            recorder=FakeRecorder(
                VoicePipelineError(VoiceErrorStage.RECORDING, "not used")
            ),
            asr_provider=FakeASR(
                VoicePipelineError(VoiceErrorStage.TRANSCRIBING, "not used")
            ),
            speech_service=speech_service,
            playback=playback,
            gateway_scripts=["先接上本地运行时。然后再接克隆链路。"],
        )

        result = controller.run_text_turn("继续", source_channel="typed_text")

        self.assertTrue(result.success)
        self.assertTrue(result.speech_played)
        self.assertTrue(result.streaming_playback_used)
        self.assertEqual(result.tts_provider, "cosyvoice_local")
        self.assertEqual(result.first_audio_latency_ms, 35)
        self.assertEqual(result.speech_chunk_count, 2)
        self.assertEqual(playback.stream_calls, 1)
        self.assertEqual(playback.calls, 0)
        self.assertEqual(len(gateway.calls), 1)


if __name__ == "__main__":
    unittest.main()
