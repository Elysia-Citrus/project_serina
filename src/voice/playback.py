from __future__ import annotations

import io
from threading import Lock
from time import sleep
from time import monotonic
from typing import Iterable, Protocol
import wave

from src.config.loader import VoiceConfig
from src.voice.audio_player import InterruptToken
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.models import AudioChunkLike, PlaybackResult, SynthesizedAudio


class AudioPlayback(Protocol):
    def play(
        self,
        synthesized_audio: SynthesizedAudio,
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        ...

    def play_stream(
        self,
        audio_chunks: Iterable[AudioChunkLike],
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        ...

    def stop(self, reason: str = "interrupt") -> None:
        ...


class NullAudioPlayback:
    def play(
        self,
        synthesized_audio: SynthesizedAudio,
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        interrupted = interrupt_token.is_interrupted() if interrupt_token else False
        return PlaybackResult(
            latency_ms=0,
            first_chunk_latency_ms=0,
            chunk_count=0 if interrupted else 1,
            interrupted=interrupted,
            stop_reason=interrupt_token.reason if interrupt_token else None,
        )

    def play_stream(
        self,
        audio_chunks: Iterable[AudioChunkLike],
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        if interrupt_token is not None and interrupt_token.is_interrupted():
            return PlaybackResult(
                latency_ms=0,
                first_chunk_latency_ms=0,
                chunk_count=0,
                streamed=True,
                interrupted=True,
                stop_reason=interrupt_token.reason,
            )
        return PlaybackResult(
            latency_ms=0,
            first_chunk_latency_ms=0,
            chunk_count=0,
            streamed=True,
        )

    def stop(self, reason: str = "interrupt") -> None:
        return None


class BlockingAudioPlayback:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._lock = Lock()
        self._current_play_obj = None
        self._stop_reason: str | None = None

    def play(
        self,
        synthesized_audio: SynthesizedAudio,
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        if interrupt_token is not None and interrupt_token.is_interrupted():
            return PlaybackResult(
                latency_ms=0,
                first_chunk_latency_ms=0,
                chunk_count=0,
                interrupted=True,
                stop_reason=interrupt_token.reason,
            )
        simpleaudio = self._load_simpleaudio()
        frames, channels, sample_width, sample_rate = self._decode_audio(
            audio_bytes=synthesized_audio.audio_bytes,
            container_format=synthesized_audio.container_format,
            sample_rate=synthesized_audio.sample_rate,
            channels=synthesized_audio.channels,
            sample_width=synthesized_audio.sample_width,
        )
        started_at = monotonic()
        play_obj = simpleaudio.play_buffer(frames, channels, sample_width, sample_rate)
        with self._lock:
            self._current_play_obj = play_obj
            self._stop_reason = None
        self._wait_for_playback(play_obj, interrupt_token=interrupt_token)
        interrupted = interrupt_token.is_interrupted() if interrupt_token else False
        stop_reason = interrupt_token.reason if interrupt_token else self._stop_reason
        with self._lock:
            self._current_play_obj = None
        return PlaybackResult(
            latency_ms=int((monotonic() - started_at) * 1000),
            first_chunk_latency_ms=0,
            chunk_count=0 if interrupted else 1,
            interrupted=interrupted,
            stop_reason=stop_reason,
        )

    def play_stream(
        self,
        audio_chunks: Iterable[AudioChunkLike],
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        if interrupt_token is not None and interrupt_token.is_interrupted():
            return PlaybackResult(
                latency_ms=0,
                first_chunk_latency_ms=0,
                chunk_count=0,
                streamed=True,
                interrupted=True,
                stop_reason=interrupt_token.reason,
            )
        simpleaudio = self._load_simpleaudio()
        started_at = monotonic()
        first_chunk_latency_ms: int | None = None
        chunk_count = 0

        for audio_chunk in audio_chunks:
            if interrupt_token is not None and interrupt_token.is_interrupted():
                break
            if first_chunk_latency_ms is None:
                first_chunk_latency_ms = int((monotonic() - started_at) * 1000)
            frames, channels, sample_width, sample_rate = self._decode_audio(
                audio_bytes=audio_chunk.audio_bytes,
                container_format=audio_chunk.container_format,
                sample_rate=audio_chunk.sample_rate,
                channels=audio_chunk.channels,
                sample_width=audio_chunk.sample_width,
            )
            play_obj = simpleaudio.play_buffer(frames, channels, sample_width, sample_rate)
            with self._lock:
                self._current_play_obj = play_obj
                self._stop_reason = None
            self._wait_for_playback(play_obj, interrupt_token=interrupt_token)
            with self._lock:
                self._current_play_obj = None
            chunk_count += 1
            if interrupt_token is not None and interrupt_token.is_interrupted():
                break

        interrupted = interrupt_token.is_interrupted() if interrupt_token else False
        if chunk_count == 0 and not interrupted:
            raise VoicePipelineError(
                VoiceErrorStage.PLAYBACK,
                "Streaming playback did not receive any audio chunks.",
            )

        return PlaybackResult(
            latency_ms=int((monotonic() - started_at) * 1000),
            first_chunk_latency_ms=first_chunk_latency_ms,
            chunk_count=chunk_count,
            streamed=True,
            interrupted=interrupted,
            stop_reason=interrupt_token.reason if interrupt_token else self._stop_reason,
        )

    def stop(self, reason: str = "interrupt") -> None:
        with self._lock:
            self._stop_reason = reason
            play_obj = self._current_play_obj
        if play_obj is not None and hasattr(play_obj, "stop"):
            play_obj.stop()

    def _wait_for_playback(
        self,
        play_obj,
        *,
        interrupt_token: InterruptToken | None,
    ) -> None:
        while True:
            if interrupt_token is not None and interrupt_token.is_interrupted():
                if hasattr(play_obj, "stop"):
                    play_obj.stop()
                return
            if hasattr(play_obj, "is_playing"):
                if not play_obj.is_playing():
                    return
                sleep(0.02)
                continue
            play_obj.wait_done()
            return

    def _load_simpleaudio(self):
        try:
            import simpleaudio  # type: ignore
        except ModuleNotFoundError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.PLAYBACK,
                "simpleaudio is required for audio playback. Install it before using voice mode.",
            ) from exc
        return simpleaudio

    def _decode_audio(
        self,
        *,
        audio_bytes: bytes,
        container_format: str,
        sample_rate: int | None,
        channels: int | None,
        sample_width: int | None,
    ) -> tuple[bytes, int, int, int]:
        normalized_format = (container_format or "wav").lower()
        if normalized_format == "wav":
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
                    return (
                        wav_file.readframes(wav_file.getnframes()),
                        wav_file.getnchannels(),
                        wav_file.getsampwidth(),
                        wav_file.getframerate(),
                    )
            except wave.Error as exc:
                raise VoicePipelineError(
                    VoiceErrorStage.PLAYBACK,
                    "Playback only supports valid WAV audio or raw PCM chunks.",
                ) from exc

        if normalized_format in {"pcm", "pcm_s16le", "raw"}:
            return (
                audio_bytes,
                channels or self.config.channels,
                sample_width or 2,
                sample_rate or self.config.sample_rate,
            )

        raise VoicePipelineError(
            VoiceErrorStage.PLAYBACK,
            f"Unsupported audio container for playback: {container_format}",
        )


def build_audio_playback(config: VoiceConfig) -> AudioPlayback:
    if config.tts_provider.lower() == "none":
        return NullAudioPlayback()
    return BlockingAudioPlayback(config)
