from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from uuid import uuid4
import wave

from src.config.loader import VoiceConfig
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.microphone_stream import AudioChunk
from src.voice.models import RecordedAudio


@dataclass(frozen=True)
class EndpointUpdate:
    speech_started: bool
    endpoint_detected: bool
    heard_speech: bool
    current_rms: int
    peak_rms: int
    voiced_duration_ms: int
    buffered_duration_ms: int
    trailing_silence_ms: int
    stop_reason: str | None = None


class RmsEndpointDetector:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.max_total_chunks = max(
            1,
            int(ceil(self.config.record_timeout_s * 1000 / self.config.chunk_ms)),
        )
        self.max_silent_chunks = max(
            1,
            int(ceil(self.config.silence_timeout_s * 1000 / self.config.chunk_ms)),
        )
        self.reset()

    def reset(self) -> None:
        self.audio_chunks: list[bytes] = []
        self.total_chunks = 0
        self.voiced_chunks = 0
        self.silent_chunks_after_speech = 0
        self.heard_speech = False
        self.overflow_detected = False
        self.peak_rms = 0
        self.pending_speech_chunks = 0
        self.speech_start_min_chunks = 2
        self.continue_speech_rms_threshold = max(
            100,
            int(self.config.silence_rms_threshold * 0.8),
        )

    def consume(self, chunk: AudioChunk) -> EndpointUpdate:
        self.audio_chunks.append(chunk.audio_bytes)
        self.total_chunks += 1
        self.overflow_detected = self.overflow_detected or chunk.overflow_detected
        self.peak_rms = max(self.peak_rms, chunk.rms)

        speech_started = False
        endpoint_detected = False
        stop_reason: str | None = None

        if not self.heard_speech:
            if chunk.rms >= self.config.silence_rms_threshold:
                self.pending_speech_chunks += 1
                if self.pending_speech_chunks >= self.speech_start_min_chunks:
                    speech_started = True
                    self.heard_speech = True
                    self.voiced_chunks += self.pending_speech_chunks
                    self.pending_speech_chunks = 0
                    self.silent_chunks_after_speech = 0
            else:
                self.pending_speech_chunks = 0
        elif chunk.rms >= self.continue_speech_rms_threshold:
            self.voiced_chunks += 1
            self.silent_chunks_after_speech = 0
        elif self.heard_speech:
            self.silent_chunks_after_speech += 1
            if self.silent_chunks_after_speech >= self.max_silent_chunks:
                endpoint_detected = True
                stop_reason = "silence_timeout"

        if self.total_chunks >= self.max_total_chunks and not endpoint_detected:
            endpoint_detected = True
            stop_reason = "record_timeout"

        return EndpointUpdate(
            speech_started=speech_started,
            endpoint_detected=endpoint_detected,
            heard_speech=self.heard_speech,
            current_rms=chunk.rms,
            peak_rms=self.peak_rms,
            voiced_duration_ms=self.voiced_chunks * self.config.chunk_ms,
            buffered_duration_ms=self.total_chunks * self.config.chunk_ms,
            trailing_silence_ms=self.silent_chunks_after_speech * self.config.chunk_ms,
            stop_reason=stop_reason,
        )

    def build_recorded_audio(self, temp_dir: str | Path) -> RecordedAudio:
        duration_s = (self.total_chunks * self.config.chunk_ms) / 1000.0
        voiced_duration_s = (self.voiced_chunks * self.config.chunk_ms) / 1000.0
        if not self.heard_speech:
            raise VoicePipelineError(
                VoiceErrorStage.RECORDING,
                "No speech was detected from the microphone input.",
            )
        if voiced_duration_s < self.config.min_speech_s:
            raise VoicePipelineError(
                VoiceErrorStage.RECORDING,
                (
                    "Speech onset was detected, but the voiced audio was too short for finalization. "
                    f"peak_rms={self.peak_rms}, voiced_ms={self.voiced_chunks * self.config.chunk_ms}, "
                    f"threshold={self.config.silence_rms_threshold}. "
                    "Try lowering silence_rms_threshold or min_speech_s."
                ),
            )

        temp_path = Path(temp_dir)
        temp_path.mkdir(parents=True, exist_ok=True)
        file_path = temp_path / f"input_{uuid4().hex}.wav"
        merged_audio = b"".join(self.audio_chunks)
        frame_count = max(
            0,
            len(merged_audio) // (self.config.channels * 2),
        )
        with wave.open(str(file_path), "wb") as wav_file:
            wav_file.setnchannels(self.config.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.config.sample_rate)
            wav_file.writeframes(merged_audio)
        return RecordedAudio(
            file_path=str(file_path),
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            duration_ms=max(1, int(duration_s * 1000)),
            frame_count=frame_count,
            container_format="wav",
            overflow_detected=self.overflow_detected,
        )
