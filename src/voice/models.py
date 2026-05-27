from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RecordedAudio:
    file_path: str
    sample_rate: int
    channels: int
    duration_ms: int
    frame_count: int
    container_format: str = "wav"
    overflow_detected: bool = False

    @property
    def path(self) -> Path:
        return Path(self.file_path)


@dataclass(frozen=True)
class ASRResult:
    text: str
    provider_name: str
    model_name: str
    latency_ms: int
    partial_text: str | None = None
    raw_result: object | None = None


@dataclass(frozen=True)
class TTSRequest:
    text: str
    language: str = "zh-CN"
    model_name: str | None = None
    voice_preset: str | None = None
    speaker_id: str | None = None
    voice_profile_id: str | None = None
    reference_audio_path: str | None = None
    style_hint: str | None = None
    profile_id: str | None = None
    runtime_id: str | None = None
    profile_kind: str | None = None
    asset_dir: str | None = None
    reference_text: str | None = None
    text_chunks: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AudioChunkLike:
    audio_bytes: bytes
    provider_name: str
    model_name: str
    container_format: str = "wav"
    sample_rate: int | None = None
    channels: int | None = None
    sample_width: int | None = None
    sequence_index: int = 0
    is_final: bool = False


@dataclass(frozen=True)
class SynthesizedAudio:
    audio_bytes: bytes
    provider_name: str
    model_name: str
    latency_ms: int
    container_format: str = "wav"
    sample_rate: int | None = None
    channels: int | None = None
    sample_width: int | None = None
    voice_preset: str | None = None
    audio_url: str | None = None


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    provider: str
    model: str
    runtime_id: str | None = None
    profile_kind: str = "preset"
    voice_preset: str | None = None
    speaker_id: str | None = None
    voice_profile_id: str | None = None
    reference_audio_path: str | None = None
    asset_dir: str | None = None
    reference_text: str | None = None
    scene_style_hints: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class SpeechRenderResult:
    speech_text: str
    style_id: str
    applied_rules: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SpeechSynthesisResult:
    synthesized_audio: SynthesizedAudio
    speech_text: str
    style_id: str
    applied_rules: tuple[str, ...] = field(default_factory=tuple)
    voice_profile_id: str | None = None


@dataclass(frozen=True)
class SpeechSynthesisStreamResult:
    audio_chunks: Iterable[AudioChunkLike]
    provider_name: str
    model_name: str
    speech_text: str
    style_id: str
    applied_rules: tuple[str, ...] = field(default_factory=tuple)
    voice_profile_id: str | None = None


@dataclass(frozen=True)
class PlaybackResult:
    latency_ms: int
    first_chunk_latency_ms: int | None = None
    chunk_count: int = 1
    streamed: bool = False
    interrupted: bool = False
    stop_reason: str | None = None


@dataclass
class VoiceSessionState:
    phase: str = "idle"
    completed_turns: int = 0
    last_transcript: str | None = None
    last_partial_transcript: str | None = None
    last_error_stage: str | None = None


@dataclass(frozen=True)
class VoiceTurnResult:
    success: bool
    source_channel: str
    transcript_text: str | None = None
    reply_text: str | None = None
    coordinator_turn_id: str | None = None
    scene: str | None = None
    diagnostic_text: str | None = None
    command_handled: bool = False
    command_output_text: str | None = None
    speech_played: bool = False
    tts_played: bool = False
    error_stage: str | None = None
    error_message: str | None = None
    audio_duration_ms: int | None = None
    asr_provider: str | None = None
    asr_latency_ms: int | None = None
    tts_provider: str | None = None
    tts_latency_ms: int | None = None
    playback_latency_ms: int | None = None
    voice_profile_id: str | None = None
    speech_text_preview: str | None = None
    speech_render_rules: tuple[str, ...] = field(default_factory=tuple)
    style_id: str | None = None
    streaming_playback_used: bool = False
    first_audio_latency_ms: int | None = None
    speech_chunk_count: int | None = None
    debug_saved_paths: tuple[str, ...] = field(default_factory=tuple)
