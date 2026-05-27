from __future__ import annotations

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
from src.dialogue.engine import DialogueEngine
from src.memory.manager import MemoryManager
from src.voice.controller import VoiceSessionController
from src.voice.models import (
    ASRResult,
    PlaybackResult,
    RecordedAudio,
    SpeechSynthesisResult,
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


class _Recorder:
    def __init__(self, recorded_audio: RecordedAudio) -> None:
        self.recorded_audio = recorded_audio

    def capture_to_wav(self) -> RecordedAudio:
        return self.recorded_audio


class _ASR:
    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        return ASRResult(
            text="keep the voice path moving",
            provider_name="mock-asr",
            model_name="mock-asr-model",
            latency_ms=88,
        )


class _SpeechService:
    is_enabled = True

    def get_requested_profile_id(self, profile_id: str | None = None) -> str | None:
        return profile_id or "serina_main"

    def synthesize_reply(
        self,
        reply_text: str,
        scene: str,
        profile_id: str | None = None,
    ) -> SpeechSynthesisResult:
        return SpeechSynthesisResult(
            synthesized_audio=SynthesizedAudio(
                audio_bytes=_make_wav_bytes(),
                provider_name="mock-tts",
                model_name="mock-tts-model",
                latency_ms=120,
            ),
            speech_text="Let us keep the voice path moving.",
            style_id="discussion",
            applied_rules=("strip_stage_directions", "compress_punctuation"),
            voice_profile_id="serina_main",
        )

    def synthesize_reply_stream(
        self,
        reply_text: str,
        scene: str,
        profile_id: str | None = None,
    ):
        return None


class _Playback:
    def play(
        self,
        synthesized_audio: SynthesizedAudio,
        *,
        output_device: str | int | None = None,
    ) -> PlaybackResult:
        return PlaybackResult(latency_ms=240, first_chunk_latency_ms=0, chunk_count=1)

    def play_stream(
        self,
        audio_chunks,
        *,
        output_device: str | int | None = None,
    ) -> PlaybackResult:
        return PlaybackResult(
            latency_ms=240,
            first_chunk_latency_ms=30,
            chunk_count=2,
            streamed=True,
        )


class VoiceObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_voice_turn_logs_core_metadata(self) -> None:
        app_config = build_test_config(self.workspace.db_path)
        memory_manager = MemoryManager.from_app_config(app_config)
        gateway = DummyGateway(["Wrap the main path first."])
        engine = DialogueEngine(app_config, gateway, memory_manager=memory_manager)
        coordinator = Coordinator(app_config, engine=engine)
        input_path = self.workspace.root / "input.wav"
        input_path.write_bytes(_make_wav_bytes())
        controller = VoiceSessionController(
            config=app_config.voice,
            coordinator=coordinator,
            recorder=_Recorder(
                RecordedAudio(
                    file_path=str(input_path),
                    sample_rate=16000,
                    channels=1,
                    duration_ms=450,
                    frame_count=7200,
                )
            ),
            asr_provider=_ASR(),
            speech_service=_SpeechService(),
            playback=_Playback(),
        )

        with patch("src.voice.controller.log_event") as mock_log_event:
            result = controller.run_voice_turn()

        self.assertTrue(result.success)
        event_names = [call.args[0] for call in mock_log_event.call_args_list]
        self.assertIn("voice_turn_started", event_names)
        self.assertIn("voice_recording_completed", event_names)
        self.assertIn("voice_transcription_completed", event_names)
        self.assertIn("voice_tts_completed", event_names)
        self.assertIn("voice_playback_completed", event_names)
        self.assertIn("voice_turn_completed", event_names)

        completed_calls = [
            call.kwargs
            for call in mock_log_event.call_args_list
            if call.args[0] == "voice_turn_completed"
        ]
        self.assertEqual(len(completed_calls), 1)
        payload = completed_calls[0]
        self.assertEqual(payload["source_channel"], "voice")
        self.assertEqual(payload["asr_provider"], "mock-asr")
        self.assertEqual(payload["tts_provider"], "mock-tts")
        self.assertEqual(payload["playback_latency_ms"], 240)
        self.assertEqual(payload["voice_profile_id"], "serina_main")
        self.assertEqual(payload["style_id"], "discussion")
        self.assertEqual(
            payload["speech_render_rules"],
            ("strip_stage_directions", "compress_punctuation"),
        )
        self.assertFalse(payload["streaming_playback_used"])
        self.assertEqual(payload["coordinator_turn_id"], result.coordinator_turn_id)


if __name__ == "__main__":
    unittest.main()
