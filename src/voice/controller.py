from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable
from uuid import uuid4

from src.app.coordinator import Coordinator
from src.config.loader import VoiceConfig
from src.utils.logger import log_event
from src.utils.text_utils import safe_preview
from src.voice.endpoint import RmsEndpointDetector
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.recorder import describe_audio_devices
from src.voice.audio_player import InterruptToken
from src.voice.models import (
    ASRResult,
    AudioChunkLike,
    RecordedAudio,
    SynthesizedAudio,
    VoiceSessionState,
    VoiceTurnResult,
)
from src.voice.transcript import TranscriptAggregator
from src.voice.voice_loop import VoiceInterruptMonitor

if TYPE_CHECKING:
    from src.avatar.event_bus import AvatarEventBus
    from src.app.command_router import CommandRouter
    from src.voice.asr import ASRProvider
    from src.voice.playback import AudioPlayback
    from src.voice.recorder import AudioRecorder
    from src.voice.synthesis import SpeechSynthesisService


class VoiceSessionController:
    def __init__(
        self,
        *,
        config: VoiceConfig,
        coordinator: Coordinator,
        recorder: AudioRecorder,
        asr_provider: ASRProvider,
        speech_service: SpeechSynthesisService,
        playback: AudioPlayback,
        command_router: CommandRouter | None = None,
        status_callback: Callable[[str], None] | None = None,
        event_bus: AvatarEventBus | None = None,
    ) -> None:
        self.config = config
        self.coordinator = coordinator
        self.recorder = recorder
        self.asr_provider = asr_provider
        self.speech_service = speech_service
        self.playback = playback
        self.command_router = command_router
        self.status_callback = status_callback
        self.event_bus = event_bus
        self.state = VoiceSessionState()

    def handle_console_input(self, raw_input: str) -> VoiceTurnResult | None:
        if raw_input == "":
            return self.run_voice_turn()

        stripped = raw_input.strip()
        if not stripped:
            return None

        if stripped in {"/voice devices", "/voice inputs", "/voice list-devices"}:
            try:
                output_text = describe_audio_devices()
                return VoiceTurnResult(
                    success=True,
                    source_channel="command",
                    command_handled=True,
                    command_output_text=output_text,
                )
            except VoicePipelineError as exc:
                return VoiceTurnResult(
                    success=False,
                    source_channel="command",
                    command_handled=True,
                    command_output_text=str(exc),
                    error_stage=exc.stage.value,
                    error_message=str(exc),
                )

        if stripped.startswith("/") and self.command_router is not None:
            command_result = self.command_router.route(stripped)
            if command_result is not None and command_result.handled:
                return VoiceTurnResult(
                    success=command_result.success,
                    source_channel="command",
                    command_handled=True,
                    command_output_text=command_result.output_text,
                )

        return self.run_text_turn(stripped, source_channel="typed_text")

    def run_voice_turn(self) -> VoiceTurnResult:
        session_id = self.coordinator.session.session_id
        recorded_audio: RecordedAudio | None = None
        asr_result: ASRResult | None = None
        saved_paths: list[str] = []
        transcript_text: str | None = None
        transcript_aggregator = TranscriptAggregator(self.config)

        self._set_phase(
            "listening" if self.config.recording_mode == "endpoint_once" else "recording"
        )
        log_event(
            "voice_turn_started",
            level="INFO",
            source_channel="voice",
            session_id=session_id,
            voice_phase=self.state.phase,
        )

        try:
            if self.config.recording_mode == "endpoint_once":
                recorded_audio = self._record_until_endpoint(session_id=session_id)
            else:
                log_event(
                    "voice_recording_started",
                    level="DEBUG",
                    source_channel="voice",
                    session_id=session_id,
                    voice_phase=self.state.phase,
                    input_device=self.config.input_device,
                    sample_rate=self.config.sample_rate,
                    channels=self.config.channels,
                    recording_mode=self.config.recording_mode,
                    fixed_record_seconds=(
                        self.config.fixed_record_seconds
                        if self.config.recording_mode == "fixed_duration"
                        else None
                    ),
                    record_timeout_s=self.config.record_timeout_s,
                    silence_timeout_s=self.config.silence_timeout_s,
                )
                recorded_audio = self.recorder.capture_to_wav()
            if self.config.debug_save_input_audio:
                saved_paths.append(recorded_audio.file_path)
            if self.config.recording_mode != "endpoint_once":
                log_event(
                    "voice_recording_completed",
                    level="INFO",
                    source_channel="voice",
                    session_id=session_id,
                    voice_phase=self.state.phase,
                    audio_duration_ms=recorded_audio.duration_ms,
                    audio_container=recorded_audio.container_format,
                    overflow_detected=recorded_audio.overflow_detected,
                )

            self._set_phase("finalizing_transcript")
            log_event(
                "voice_transcription_started",
                level="DEBUG",
                source_channel="voice",
                session_id=session_id,
                voice_phase=self.state.phase,
                asr_provider=self.config.asr_provider,
                asr_model=self.config.asr_model,
            )
            asr_result = self.asr_provider.transcribe(
                recorded_audio,
                language=self.config.language,
            )
            if asr_result.partial_text:
                partial_update = transcript_aggregator.update_partial(asr_result.partial_text)
                if partial_update.display_text:
                    self.state.last_partial_transcript = partial_update.display_text
                    log_event(
                        "voice_transcription_partial",
                        level="DEBUG",
                        source_channel="voice",
                        session_id=session_id,
                        voice_phase=self.state.phase,
                        transcript_preview=safe_preview(
                            partial_update.display_text,
                            self.coordinator.config.runtime.debug_max_preview_chars,
                        ),
                    )
                    self._emit_status(f"[partial] {partial_update.display_text}")
            transcript_text = transcript_aggregator.finalize(asr_result.text).normalized_text
            self.state.last_transcript = transcript_text
            self.state.last_partial_transcript = None
            log_event(
                "voice_transcription_completed",
                level="INFO",
                source_channel="voice",
                session_id=session_id,
                voice_phase=self.state.phase,
                asr_provider=asr_result.provider_name,
                asr_model=asr_result.model_name,
                asr_latency_ms=asr_result.latency_ms,
                transcript_preview=safe_preview(
                    transcript_text,
                    self.coordinator.config.runtime.debug_max_preview_chars,
                ),
            )
            if not transcript_text:
                raise VoicePipelineError(
                    VoiceErrorStage.TRANSCRIBING,
                    "ASR returned an empty transcript.",
                )

            if self.config.allow_spoken_commands and transcript_text.startswith("/"):
                if self.command_router is not None:
                    command_result = self.command_router.route(transcript_text)
                    if command_result is not None and command_result.handled:
                        self._set_phase("idle")
                        self.state.completed_turns += 1
                        return VoiceTurnResult(
                            success=command_result.success,
                            source_channel="voice",
                            transcript_text=transcript_text,
                            command_handled=True,
                            command_output_text=command_result.output_text,
                            audio_duration_ms=recorded_audio.duration_ms,
                            asr_provider=asr_result.provider_name,
                            asr_latency_ms=asr_result.latency_ms,
                            debug_saved_paths=tuple(saved_paths),
                        )

            result = self._run_agent_turn(
                transcript_text,
                source_channel="voice",
                transcript_text=transcript_text,
                audio_duration_ms=recorded_audio.duration_ms,
                asr_result=asr_result,
            )
            return self._with_saved_paths(result, saved_paths)
        except VoicePipelineError as exc:
            return self._build_failed_voice_result(
                session_id=session_id,
                stage=exc.stage,
                error_message=str(exc),
                error_type=type(exc).__name__,
                recorded_audio=recorded_audio,
                asr_result=asr_result,
                transcript_text=transcript_text,
                saved_paths=saved_paths,
            )
        except Exception as exc:
            stage = self._infer_error_stage_from_phase()
            return self._build_failed_voice_result(
                session_id=session_id,
                stage=stage,
                error_message=f"{type(exc).__name__}: {exc}",
                error_type=type(exc).__name__,
                recorded_audio=recorded_audio,
                asr_result=asr_result,
                transcript_text=transcript_text,
                saved_paths=saved_paths,
            )
        finally:
            self._cleanup_recorded_audio(recorded_audio)

    def run_text_turn(self, user_input: str, *, source_channel: str = "typed_text") -> VoiceTurnResult:
        return self._run_agent_turn(
            user_input,
            source_channel=source_channel,
            transcript_text=None,
            audio_duration_ms=None,
            asr_result=None,
        )

    def _run_agent_turn(
        self,
        user_input: str,
        *,
        source_channel: str,
        transcript_text: str | None,
        audio_duration_ms: int | None,
        asr_result: ASRResult | None,
    ) -> VoiceTurnResult:
        session_id = self.coordinator.session.session_id
        self._set_phase("dispatch_to_agent")
        log_event(
            "voice_text_turn_started",
            level="DEBUG",
            source_channel=source_channel,
            session_id=session_id,
            voice_phase=self.state.phase,
            transcript_preview=(
                safe_preview(
                    transcript_text,
                    self.coordinator.config.runtime.debug_max_preview_chars,
                )
                if transcript_text
                else None
            ),
        )
        self._set_phase("thinking")

        try:
            coordinator_result = self.coordinator.process_user_message(
                user_input,
                source_channel=source_channel,
                raw_asr_text=transcript_text,
                asr_provider=asr_result.provider_name if asr_result else None,
                tts_provider=self.config.tts_provider,
            )
        except Exception as exc:
            self.state.last_error_stage = VoiceErrorStage.THINKING.value
            self._set_phase("idle")
            log_event(
                "voice_turn_failed",
                level="ERROR",
                source_channel=source_channel,
                session_id=session_id,
                voice_phase=VoiceErrorStage.THINKING.value,
                audio_duration_ms=audio_duration_ms,
                asr_provider=asr_result.provider_name if asr_result else None,
                asr_latency_ms=asr_result.latency_ms if asr_result else None,
                transcript_preview=(
                    safe_preview(
                        transcript_text,
                        self.coordinator.config.runtime.debug_max_preview_chars,
                    )
                    if transcript_text
                    else None
                ),
                error_stage=VoiceErrorStage.THINKING.value,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return VoiceTurnResult(
                success=False,
                source_channel=source_channel,
                transcript_text=transcript_text,
                error_stage=VoiceErrorStage.THINKING.value,
                error_message=str(exc),
                audio_duration_ms=audio_duration_ms,
                asr_provider=asr_result.provider_name if asr_result else None,
                asr_latency_ms=asr_result.latency_ms if asr_result else None,
            )

        if not self.speech_service.is_enabled:
            self._set_phase("present_reply")
            log_event(
                "voice_speaking_skipped",
                level="INFO",
                source_channel=source_channel,
                session_id=session_id,
                coordinator_turn_id=coordinator_result.turn_id,
                voice_phase=self.state.phase,
                tts_provider="none",
                voice_profile_id=None,
                speech_text_preview=None,
                speech_render_rules=(),
                style_id=None,
                streaming_playback_used=False,
                first_audio_latency_ms=None,
                speech_chunk_count=None,
            )
            self._set_phase("idle")
            self.state.completed_turns += 1
            log_event(
                "voice_turn_completed",
                level="INFO",
                source_channel=source_channel,
                session_id=session_id,
                voice_phase=self.state.phase,
                coordinator_turn_id=coordinator_result.turn_id,
                scene=coordinator_result.scene,
                audio_duration_ms=audio_duration_ms,
                asr_provider=asr_result.provider_name if asr_result else None,
                asr_latency_ms=asr_result.latency_ms if asr_result else None,
                transcript_preview=(
                    safe_preview(
                        transcript_text,
                        self.coordinator.config.runtime.debug_max_preview_chars,
                    )
                    if transcript_text
                    else None
                ),
                tts_provider="none",
                tts_latency_ms=0,
                playback_latency_ms=0,
                speech_played=False,
                voice_profile_id=None,
                speech_text_preview=None,
                speech_render_rules=(),
                style_id=None,
                streaming_playback_used=False,
                first_audio_latency_ms=None,
                speech_chunk_count=None,
                retrieval_mode=coordinator_result.retrieval_mode,
                startup_memory_pack_present=coordinator_result.startup_memory_pack_present,
                startup_memory_pack_count=coordinator_result.startup_memory_pack_count,
                success=True,
                error_stage=None,
                error_message=None,
            )
            return VoiceTurnResult(
                success=True,
                source_channel=source_channel,
                transcript_text=transcript_text,
                reply_text=coordinator_result.reply_text,
                coordinator_turn_id=coordinator_result.turn_id,
                scene=coordinator_result.scene,
                diagnostic_text=coordinator_result.diagnostic_text,
                speech_played=False,
                tts_played=False,
                audio_duration_ms=audio_duration_ms,
                asr_provider=asr_result.provider_name if asr_result else None,
                asr_latency_ms=asr_result.latency_ms if asr_result else None,
                tts_provider="none",
                tts_latency_ms=0,
                playback_latency_ms=0,
                voice_profile_id=None,
                speech_text_preview=None,
                speech_render_rules=(),
                style_id=None,
                streaming_playback_used=False,
                first_audio_latency_ms=None,
                speech_chunk_count=None,
            )

        self._set_phase("speaking")
        speech_played = False
        tts_provider: str | None = None
        tts_latency_ms: int | None = None
        playback_latency_ms: int | None = None
        streaming_playback_used = False
        first_audio_latency_ms: int | None = None
        speech_chunk_count: int | None = None
        debug_saved_paths: list[str] = []
        speaking_error_stage: str | None = None
        speaking_error_message: str | None = None
        voice_profile_id = self.speech_service.get_requested_profile_id()
        speech_text_preview: str | None = None
        speech_render_rules: tuple[str, ...] = ()
        style_id: str | None = None

        try:
            interrupt_token = InterruptToken()
            if self.event_bus is not None:
                self.event_bus.emit(
                    "tts_start",
                    {
                        "session_id": session_id,
                        "turn_id": coordinator_result.turn_id,
                        "source_channel": source_channel,
                    },
                )
            stream_result = self.speech_service.synthesize_reply_stream(
                coordinator_result.reply_text,
                scene=coordinator_result.scene,
            )
            if stream_result is not None:
                tts_provider = stream_result.provider_name
                voice_profile_id = stream_result.voice_profile_id
                speech_text_preview = safe_preview(
                    stream_result.speech_text,
                    self.coordinator.config.runtime.debug_max_preview_chars,
                )
                speech_render_rules = stream_result.applied_rules
                style_id = stream_result.style_id
                streaming_playback_used = True
                captured_chunks: list[AudioChunkLike] = []
                log_event(
                    "voice_playback_started",
                    level="DEBUG",
                    source_channel=source_channel,
                    session_id=session_id,
                    coordinator_turn_id=coordinator_result.turn_id,
                    voice_phase=self.state.phase,
                    tts_provider=tts_provider,
                    voice_profile_id=voice_profile_id,
                    speech_text_preview=speech_text_preview,
                    speech_render_rules=speech_render_rules,
                    style_id=style_id,
                    stream_playback_enabled=True,
                )
                with VoiceInterruptMonitor(
                    config=self.config,
                    playback=self.playback,
                    recorder=self.recorder,
                    interrupt_token=interrupt_token,
                    event_bus=self.event_bus,
                ):
                    playback_result = self.playback.play_stream(
                        self._capture_stream_chunks(
                            stream_result.audio_chunks,
                            captured_chunks,
                        ),
                        output_device=self.config.output_device,
                        interrupt_token=interrupt_token,
                    )
                playback_latency_ms = playback_result.latency_ms
                first_audio_latency_ms = playback_result.first_chunk_latency_ms
                speech_chunk_count = playback_result.chunk_count
                tts_latency_ms = first_audio_latency_ms
                if self.config.debug_save_output_audio and captured_chunks:
                    debug_saved_paths.append(self._save_output_chunks(captured_chunks))
                speech_played = True
            else:
                synthesis_result = self.speech_service.synthesize_reply(
                    coordinator_result.reply_text,
                    scene=coordinator_result.scene,
                )
                synthesized_audio = synthesis_result.synthesized_audio
                tts_provider = synthesized_audio.provider_name
                tts_latency_ms = synthesized_audio.latency_ms
                voice_profile_id = synthesis_result.voice_profile_id
                speech_text_preview = safe_preview(
                    synthesis_result.speech_text,
                    self.coordinator.config.runtime.debug_max_preview_chars,
                )
                speech_render_rules = synthesis_result.applied_rules
                style_id = synthesis_result.style_id
                if self.config.debug_save_output_audio:
                    debug_saved_paths.append(self._save_output_audio(synthesized_audio))

                log_event(
                    "voice_playback_started",
                    level="DEBUG",
                    source_channel=source_channel,
                    session_id=session_id,
                    coordinator_turn_id=coordinator_result.turn_id,
                    voice_phase=self.state.phase,
                    tts_provider=tts_provider,
                    voice_profile_id=voice_profile_id,
                    speech_text_preview=speech_text_preview,
                    speech_render_rules=speech_render_rules,
                    style_id=style_id,
                    stream_playback_enabled=False,
                )
                with VoiceInterruptMonitor(
                    config=self.config,
                    playback=self.playback,
                    recorder=self.recorder,
                    interrupt_token=interrupt_token,
                    event_bus=self.event_bus,
                ):
                    playback_result = self.playback.play(
                        synthesized_audio,
                        output_device=self.config.output_device,
                        interrupt_token=interrupt_token,
                    )
                playback_latency_ms = playback_result.latency_ms
                first_audio_latency_ms = playback_result.first_chunk_latency_ms
                speech_chunk_count = playback_result.chunk_count
                speech_played = True

            log_event(
                "voice_tts_completed",
                level="INFO",
                source_channel=source_channel,
                session_id=session_id,
                coordinator_turn_id=coordinator_result.turn_id,
                voice_phase=self.state.phase,
                tts_provider=tts_provider,
                tts_latency_ms=tts_latency_ms,
                voice_profile_id=voice_profile_id,
                speech_text_preview=speech_text_preview,
                speech_render_rules=speech_render_rules,
                style_id=style_id,
                streaming_playback_used=streaming_playback_used,
                first_audio_latency_ms=first_audio_latency_ms,
                speech_chunk_count=speech_chunk_count,
                interrupted=interrupt_token.is_interrupted(),
                interrupt_reason=interrupt_token.reason,
            )
            log_event(
                "voice_playback_completed",
                level="INFO",
                source_channel=source_channel,
                session_id=session_id,
                coordinator_turn_id=coordinator_result.turn_id,
                voice_phase=self.state.phase,
                playback_latency_ms=playback_latency_ms,
                voice_profile_id=voice_profile_id,
                speech_text_preview=speech_text_preview,
                speech_render_rules=speech_render_rules,
                style_id=style_id,
                streaming_playback_used=streaming_playback_used,
                first_audio_latency_ms=first_audio_latency_ms,
                speech_chunk_count=speech_chunk_count,
                interrupted=interrupt_token.is_interrupted(),
                interrupt_reason=interrupt_token.reason,
            )
            if self.event_bus is not None:
                self.event_bus.emit(
                    "tts_end",
                    {
                        "session_id": session_id,
                        "turn_id": coordinator_result.turn_id,
                        "interrupted": interrupt_token.is_interrupted(),
                        "reason": interrupt_token.reason,
                    },
                )
        except VoicePipelineError as exc:
            speaking_error_stage = exc.stage.value
            speaking_error_message = str(exc)
            self.state.last_error_stage = exc.stage.value
            log_event(
                "voice_speaking_failed",
                level="ERROR",
                source_channel=source_channel,
                session_id=session_id,
                coordinator_turn_id=coordinator_result.turn_id,
                voice_phase=exc.stage.value,
                tts_provider=tts_provider,
                tts_latency_ms=tts_latency_ms,
                voice_profile_id=voice_profile_id,
                speech_text_preview=speech_text_preview,
                speech_render_rules=speech_render_rules,
                style_id=style_id,
                streaming_playback_used=streaming_playback_used,
                first_audio_latency_ms=first_audio_latency_ms,
                speech_chunk_count=speech_chunk_count,
                error_stage=exc.stage.value,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        self._set_phase("idle")
        self.state.completed_turns += 1
        log_event(
            "voice_turn_completed",
            level="INFO",
            source_channel=source_channel,
            session_id=session_id,
            voice_phase=self.state.phase,
            coordinator_turn_id=coordinator_result.turn_id,
            scene=coordinator_result.scene,
            audio_duration_ms=audio_duration_ms,
            asr_provider=asr_result.provider_name if asr_result else None,
            asr_latency_ms=asr_result.latency_ms if asr_result else None,
            transcript_preview=(
                safe_preview(
                    transcript_text,
                    self.coordinator.config.runtime.debug_max_preview_chars,
                )
                if transcript_text
                else None
            ),
            tts_provider=tts_provider,
            tts_latency_ms=tts_latency_ms,
            playback_latency_ms=playback_latency_ms,
            speech_played=speech_played,
            voice_profile_id=voice_profile_id,
            speech_text_preview=speech_text_preview,
            speech_render_rules=speech_render_rules,
            style_id=style_id,
            streaming_playback_used=streaming_playback_used,
            first_audio_latency_ms=first_audio_latency_ms,
            speech_chunk_count=speech_chunk_count,
            retrieval_mode=coordinator_result.retrieval_mode,
            startup_memory_pack_present=coordinator_result.startup_memory_pack_present,
            startup_memory_pack_count=coordinator_result.startup_memory_pack_count,
            success=True,
            error_stage=speaking_error_stage,
            error_message=speaking_error_message,
        )
        return VoiceTurnResult(
            success=True,
            source_channel=source_channel,
            transcript_text=transcript_text,
            reply_text=coordinator_result.reply_text,
            coordinator_turn_id=coordinator_result.turn_id,
            scene=coordinator_result.scene,
            diagnostic_text=coordinator_result.diagnostic_text,
            speech_played=speech_played,
            tts_played=speech_played,
            error_stage=speaking_error_stage,
            error_message=speaking_error_message,
            audio_duration_ms=audio_duration_ms,
            asr_provider=asr_result.provider_name if asr_result else None,
            asr_latency_ms=asr_result.latency_ms if asr_result else None,
            tts_provider=tts_provider,
            tts_latency_ms=tts_latency_ms,
            playback_latency_ms=playback_latency_ms,
            voice_profile_id=voice_profile_id,
            speech_text_preview=speech_text_preview,
            speech_render_rules=speech_render_rules,
            style_id=style_id,
            streaming_playback_used=streaming_playback_used,
            first_audio_latency_ms=first_audio_latency_ms,
            speech_chunk_count=speech_chunk_count,
            debug_saved_paths=tuple(debug_saved_paths),
        )

    def _save_output_audio(self, synthesized_audio: SynthesizedAudio) -> str:
        temp_dir = Path(self.config.temp_audio_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / f"output_{uuid4().hex}.{synthesized_audio.container_format}"
        file_path.write_bytes(synthesized_audio.audio_bytes)
        return str(file_path)

    def _save_output_chunks(self, audio_chunks: list[AudioChunkLike]) -> str:
        if not audio_chunks:
            raise VoicePipelineError(
                VoiceErrorStage.PLAYBACK,
                "No audio chunks are available to save.",
            )
        stitched_audio = self._stitch_audio_chunks(audio_chunks)
        return self._save_output_audio(stitched_audio)

    def _stitch_audio_chunks(self, audio_chunks: list[AudioChunkLike]) -> SynthesizedAudio:
        import io
        import wave

        frame_buffer = io.BytesIO()
        sample_rate = None
        channels = None
        sample_width = None

        for audio_chunk in audio_chunks:
            if audio_chunk.container_format.lower() != "wav":
                raise VoicePipelineError(
                    VoiceErrorStage.PLAYBACK,
                    "Debug output saving only supports streamed WAV chunks.",
                )
            with wave.open(io.BytesIO(audio_chunk.audio_bytes), "rb") as wav_file:
                if sample_rate is None:
                    sample_rate = wav_file.getframerate()
                    channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                frame_buffer.write(wav_file.readframes(wav_file.getnframes()))

        output_buffer = io.BytesIO()
        with wave.open(output_buffer, "wb") as wav_file:
            wav_file.setnchannels(channels or 1)
            wav_file.setsampwidth(sample_width or 2)
            wav_file.setframerate(sample_rate or self.config.sample_rate)
            wav_file.writeframes(frame_buffer.getvalue())
        return SynthesizedAudio(
            audio_bytes=output_buffer.getvalue(),
            provider_name=audio_chunks[0].provider_name,
            model_name=audio_chunks[0].model_name,
            latency_ms=0,
            container_format="wav",
            sample_rate=sample_rate or self.config.sample_rate,
            channels=channels or self.config.channels,
            sample_width=sample_width or 2,
        )

    def _cleanup_recorded_audio(self, recorded_audio: RecordedAudio | None) -> None:
        if recorded_audio is None or self.config.debug_save_input_audio:
            return
        try:
            recorded_audio.path.unlink(missing_ok=True)
        except OSError:
            pass

    def _with_saved_paths(
        self,
        result: VoiceTurnResult,
        saved_paths: list[str],
    ) -> VoiceTurnResult:
        if not saved_paths:
            return result
        merged_paths = tuple(dict.fromkeys(result.debug_saved_paths + tuple(saved_paths)))
        return VoiceTurnResult(
            success=result.success,
            source_channel=result.source_channel,
            transcript_text=result.transcript_text,
            reply_text=result.reply_text,
            coordinator_turn_id=result.coordinator_turn_id,
            scene=result.scene,
            diagnostic_text=result.diagnostic_text,
            command_handled=result.command_handled,
            command_output_text=result.command_output_text,
            speech_played=result.speech_played,
            tts_played=result.tts_played,
            error_stage=result.error_stage,
            error_message=result.error_message,
            audio_duration_ms=result.audio_duration_ms,
            asr_provider=result.asr_provider,
            asr_latency_ms=result.asr_latency_ms,
            tts_provider=result.tts_provider,
            tts_latency_ms=result.tts_latency_ms,
            playback_latency_ms=result.playback_latency_ms,
            voice_profile_id=result.voice_profile_id,
            speech_text_preview=result.speech_text_preview,
            speech_render_rules=result.speech_render_rules,
            style_id=result.style_id,
            streaming_playback_used=result.streaming_playback_used,
            first_audio_latency_ms=result.first_audio_latency_ms,
            speech_chunk_count=result.speech_chunk_count,
            debug_saved_paths=merged_paths,
        )

    def _infer_error_stage_from_phase(self) -> VoiceErrorStage:
        phase = self.state.phase
        if phase in {"listening", "recording", "speech_detected", "buffering_utterance"}:
            return VoiceErrorStage.RECORDING
        if phase == "finalizing_transcript":
            return VoiceErrorStage.TRANSCRIBING
        if phase in {"dispatch_to_agent", "thinking"}:
            return VoiceErrorStage.THINKING
        if phase in {"speaking", "present_reply"}:
            return VoiceErrorStage.SPEAKING
        return VoiceErrorStage.TRANSCRIBING

    def _build_failed_voice_result(
        self,
        *,
        session_id: str,
        stage: VoiceErrorStage,
        error_message: str,
        error_type: str,
        recorded_audio: RecordedAudio | None,
        asr_result: ASRResult | None,
        transcript_text: str | None,
        saved_paths: list[str],
    ) -> VoiceTurnResult:
        self.state.last_error_stage = stage.value
        self._set_phase("idle")
        log_event(
            "voice_turn_failed",
            level="ERROR",
            source_channel="voice",
            session_id=session_id,
            voice_phase=stage.value,
            audio_duration_ms=recorded_audio.duration_ms if recorded_audio else None,
            asr_provider=asr_result.provider_name if asr_result else None,
            asr_latency_ms=asr_result.latency_ms if asr_result else None,
            transcript_preview=(
                safe_preview(
                    transcript_text or "",
                    self.coordinator.config.runtime.debug_max_preview_chars,
                )
                if transcript_text
                else None
            ),
            error_stage=stage.value,
            error_type=error_type,
            error_message=error_message,
        )
        return self._with_saved_paths(
            VoiceTurnResult(
                success=False,
                source_channel="voice",
                transcript_text=transcript_text,
                error_stage=stage.value,
                error_message=error_message,
                audio_duration_ms=recorded_audio.duration_ms if recorded_audio else None,
                asr_provider=asr_result.provider_name if asr_result else None,
                asr_latency_ms=asr_result.latency_ms if asr_result else None,
            ),
            saved_paths,
        )

    def _set_phase(self, phase: str) -> None:
        self.state.phase = phase

    def _record_until_endpoint(self, *, session_id: str) -> RecordedAudio:
        self._emit_status("[voice] Listening...")
        log_event(
            "voice_listening_started",
            level="INFO",
            source_channel="voice",
            session_id=session_id,
            voice_phase=self.state.phase,
            input_device=self.config.input_device,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            chunk_ms=self.config.chunk_ms,
            recording_mode=self.config.recording_mode,
            record_timeout_s=self.config.record_timeout_s,
            silence_timeout_s=self.config.silence_timeout_s,
            vad_enabled=self.config.vad_enabled,
        )

        if not hasattr(self.recorder, "open_chunk_source"):
            raise VoicePipelineError(
                VoiceErrorStage.RECORDING,
                "The configured recorder does not support endpoint_once chunk streaming.",
            )

        detector = RmsEndpointDetector(self.config)
        chunk_source = self.recorder.open_chunk_source()
        for chunk in chunk_source.iter_chunks():
            update = detector.consume(chunk)
            if update.speech_started:
                self._set_phase("speech_detected")
                self._emit_status("[voice] Speech detected.")
                log_event(
                    "voice_speech_detected",
                    level="INFO",
                    source_channel="voice",
                    session_id=session_id,
                    voice_phase=self.state.phase,
                    rms=update.current_rms,
                    peak_rms=update.peak_rms,
                    buffered_duration_ms=update.buffered_duration_ms,
                )
                self._set_phase("buffering_utterance")

            if update.endpoint_detected:
                self._set_phase("finalizing_transcript")
                self._emit_status("[voice] Endpoint detected. Finalizing transcript...")
                log_event(
                    "voice_endpoint_detected",
                    level="INFO",
                    source_channel="voice",
                    session_id=session_id,
                    voice_phase=self.state.phase,
                    stop_reason=update.stop_reason,
                    peak_rms=update.peak_rms,
                    rms=update.current_rms,
                    buffered_duration_ms=update.buffered_duration_ms,
                    voiced_duration_ms=update.voiced_duration_ms,
                    trailing_silence_ms=update.trailing_silence_ms,
                )
                recorded_audio = detector.build_recorded_audio(self.config.temp_audio_dir)
                log_event(
                    "voice_recording_completed",
                    level="INFO",
                    source_channel="voice",
                    session_id=session_id,
                    voice_phase=self.state.phase,
                    audio_duration_ms=recorded_audio.duration_ms,
                    audio_container=recorded_audio.container_format,
                    overflow_detected=recorded_audio.overflow_detected,
                    stop_reason=update.stop_reason,
                    voiced_duration_ms=update.voiced_duration_ms,
                    trailing_silence_ms=update.trailing_silence_ms,
                )
                return recorded_audio

        raise VoicePipelineError(
            VoiceErrorStage.RECORDING,
            "The microphone stream ended before an utterance endpoint was detected.",
        )

    def _capture_stream_chunks(
        self,
        audio_chunks: Iterable[AudioChunkLike],
        captured_chunks: list[AudioChunkLike],
    ) -> Iterable[AudioChunkLike]:
        for audio_chunk in audio_chunks:
            captured_chunks.append(audio_chunk)
            yield audio_chunk

    def _emit_status(self, message: str) -> None:
        if self.status_callback is None:
            return
        self.status_callback(message)
