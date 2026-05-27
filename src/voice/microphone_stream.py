from __future__ import annotations

import audioop
from dataclasses import dataclass
from struct import iter_unpack
from typing import Iterator, Protocol
import sys

from src.config.loader import VoiceConfig
from src.voice.errors import VoiceErrorStage, VoicePipelineError


@dataclass(frozen=True)
class AudioChunk:
    audio_bytes: bytes
    sample_rate: int
    channels: int
    chunk_ms: int
    rms: int
    overflow_detected: bool = False


@dataclass(frozen=True)
class InputStreamSettings:
    device: str | int | None
    stream_sample_rate: int
    target_sample_rate: int
    channels: int
    chunk_ms: int
    blocksize_frames: int

    @property
    def requires_resample(self) -> bool:
        return self.stream_sample_rate != self.target_sample_rate


class AudioChunkSource(Protocol):
    def iter_chunks(self) -> Iterator[AudioChunk]:
        ...


class SounddeviceMicrophoneStream:
    def __init__(
        self,
        config: VoiceConfig,
        *,
        sounddevice_module: object | None = None,
    ) -> None:
        self.config = config
        self.sounddevice_module = sounddevice_module

    def iter_chunks(self) -> Iterator[AudioChunk]:
        sounddevice = self.sounddevice_module or _load_sounddevice()
        stream_settings = resolve_input_stream_settings(
            self.config,
            sounddevice=sounddevice,
        )
        resample_state = None
        stream = sounddevice.RawInputStream(
            samplerate=stream_settings.stream_sample_rate,
            channels=stream_settings.channels,
            dtype="int16",
            blocksize=stream_settings.blocksize_frames,
            device=stream_settings.device,
        )
        with stream:
            while True:
                chunk_bytes, overflowed = stream.read(stream_settings.blocksize_frames)
                if not isinstance(chunk_bytes, (bytes, bytearray)):
                    chunk_bytes = bytes(chunk_bytes)
                chunk = bytes(chunk_bytes)
                if stream_settings.requires_resample:
                    chunk, resample_state = audioop.ratecv(
                        chunk,
                        2,
                        stream_settings.channels,
                        stream_settings.stream_sample_rate,
                        stream_settings.target_sample_rate,
                        resample_state,
                    )
                yield AudioChunk(
                    audio_bytes=chunk,
                    sample_rate=stream_settings.target_sample_rate,
                    channels=stream_settings.channels,
                    chunk_ms=stream_settings.chunk_ms,
                    rms=pcm16_rms(chunk),
                    overflow_detected=bool(overflowed),
                )


def pcm16_rms(chunk: bytes) -> int:
    if not chunk:
        return 0

    total = 0
    sample_count = 0
    for (sample,) in iter_unpack("<h", chunk):
        total += sample * sample
        sample_count += 1

    if sample_count == 0:
        return 0
    return int((total / sample_count) ** 0.5)


def _load_sounddevice() -> object:
    try:
        import sounddevice  # type: ignore
    except ModuleNotFoundError as exc:
        raise VoicePipelineError(
            VoiceErrorStage.RECORDING,
            (
                "sounddevice is not available in the current Python interpreter: "
                f"{sys.executable}. If you installed it inside your Conda environment, "
                "start voice mode with `python src/app/main_voice.py` instead of `py -3 ...`."
            ),
        ) from exc
    return sounddevice


def resolve_input_stream_settings(
    config: VoiceConfig,
    *,
    sounddevice: object,
) -> InputStreamSettings:
    desired_sample_rate = int(config.sample_rate)
    desired_channels = int(config.channels)
    device = config.input_device

    primary_error = _check_input_settings(
        sounddevice,
        device=device,
        sample_rate=desired_sample_rate,
        channels=desired_channels,
    )
    if primary_error is None:
        return InputStreamSettings(
            device=device,
            stream_sample_rate=desired_sample_rate,
            target_sample_rate=desired_sample_rate,
            channels=desired_channels,
            chunk_ms=config.chunk_ms,
            blocksize_frames=max(1, int(desired_sample_rate * config.chunk_ms / 1000)),
        )

    fallback_sample_rate = _lookup_device_default_sample_rate(
        sounddevice,
        device=device,
    )
    if fallback_sample_rate is None or fallback_sample_rate == desired_sample_rate:
        raise VoicePipelineError(
            VoiceErrorStage.RECORDING,
            str(primary_error),
        ) from primary_error

    fallback_error = _check_input_settings(
        sounddevice,
        device=device,
        sample_rate=fallback_sample_rate,
        channels=desired_channels,
    )
    if fallback_error is not None:
        raise VoicePipelineError(
            VoiceErrorStage.RECORDING,
            (
                "Unable to open the microphone stream with either the configured sample rate "
                f"({desired_sample_rate}Hz) or the device default sample rate "
                f"({fallback_sample_rate}Hz). Last error: {fallback_error}"
            ),
        ) from fallback_error

    return InputStreamSettings(
        device=device,
        stream_sample_rate=fallback_sample_rate,
        target_sample_rate=desired_sample_rate,
        channels=desired_channels,
        chunk_ms=config.chunk_ms,
        blocksize_frames=max(1, int(fallback_sample_rate * config.chunk_ms / 1000)),
    )


def _check_input_settings(
    sounddevice: object,
    *,
    device: str | int | None,
    sample_rate: int,
    channels: int,
) -> Exception | None:
    checker = getattr(sounddevice, "check_input_settings", None)
    if checker is None:
        return None
    try:
        checker(
            device=device,
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
        )
    except Exception as exc:
        return exc
    return None


def _lookup_device_default_sample_rate(
    sounddevice: object,
    *,
    device: str | int | None,
) -> int | None:
    query_devices = getattr(sounddevice, "query_devices", None)
    if query_devices is None:
        return None

    try:
        if isinstance(device, int):
            raw_devices = query_devices()
            if (
                hasattr(raw_devices, "__len__")
                and hasattr(raw_devices, "__getitem__")
                and 0 <= device < len(raw_devices)
                and isinstance(raw_devices[device], dict)
            ):
                raw_rate = raw_devices[device].get("default_samplerate")
                if raw_rate:
                    return int(float(raw_rate))
        raw_device = query_devices(device)
        if isinstance(raw_device, dict):
            raw_rate = raw_device.get("default_samplerate")
            if raw_rate:
                return int(float(raw_rate))
    except Exception:
        return None

    return None
