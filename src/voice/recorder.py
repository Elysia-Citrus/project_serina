from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Protocol
from uuid import uuid4
import sys
import wave

from src.config.loader import VoiceConfig
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.microphone_stream import (
    AudioChunkSource,
    SounddeviceMicrophoneStream,
)
from src.voice.models import RecordedAudio


class AudioRecorder(Protocol):
    def capture_to_wav(self) -> RecordedAudio:
        ...

    def open_chunk_source(self) -> AudioChunkSource:
        ...


class BlockingWavRecorder:
    def __init__(
        self,
        config: VoiceConfig,
        *,
        sounddevice_module: object | None = None,
    ) -> None:
        self.config = config
        self.sounddevice_module = sounddevice_module

    def capture_to_wav(self) -> RecordedAudio:
        temp_dir = Path(self.config.temp_audio_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        if self.config.recording_mode == "fixed_duration":
            return self._capture_fixed_duration(temp_dir)
        return self._capture_silence_stop(temp_dir)

    def open_chunk_source(self) -> AudioChunkSource:
        return SounddeviceMicrophoneStream(
            self.config,
            sounddevice_module=self.sounddevice_module,
        )

    def _capture_fixed_duration(self, temp_dir: Path) -> RecordedAudio:
        target_frames = max(1, int(self.config.sample_rate * self.config.fixed_record_seconds))
        audio_chunks: list[bytes] = []
        total_frames = 0
        overflow_detected = False
        started_at = monotonic()
        chunk_source = self.open_chunk_source()
        for chunk in chunk_source.iter_chunks():
            audio_chunks.append(chunk.audio_bytes)
            total_frames += len(chunk.audio_bytes) // (self.config.channels * 2)
            overflow_detected = overflow_detected or chunk.overflow_detected
            if total_frames >= target_frames:
                break

        bytes_per_frame = self.config.channels * 2
        target_bytes = target_frames * bytes_per_frame
        merged_audio = b"".join(audio_chunks)[:target_bytes]
        elapsed_ms = int((monotonic() - started_at) * 1000)
        duration_ms = max(elapsed_ms, int(target_frames / self.config.sample_rate * 1000))
        return self._write_recording(
            temp_dir=temp_dir,
            audio_bytes=merged_audio,
            frame_count=target_frames,
            duration_ms=duration_ms,
            overflow_detected=overflow_detected,
        )

    def _capture_silence_stop(self, temp_dir: Path) -> RecordedAudio:
        max_total_chunks = max(
            1,
            int((self.config.record_timeout_s * 1000 + self.config.chunk_ms - 1) / self.config.chunk_ms),
        )
        max_silent_chunks = max(
            1,
            int((self.config.silence_timeout_s * 1000 + self.config.chunk_ms - 1) / self.config.chunk_ms),
        )

        audio_chunks: list[bytes] = []
        total_frames = 0
        heard_speech = False
        silent_chunks_after_speech = 0
        overflow_detected = False
        started_at = monotonic()
        chunk_source = self.open_chunk_source()
        for chunk_index, chunk in enumerate(chunk_source.iter_chunks(), start=1):
            audio_chunks.append(chunk.audio_bytes)
            total_frames += len(chunk.audio_bytes) // (self.config.channels * 2)
            overflow_detected = overflow_detected or chunk.overflow_detected

            if chunk.rms >= self.config.silence_rms_threshold:
                heard_speech = True
                silent_chunks_after_speech = 0
            elif heard_speech:
                silent_chunks_after_speech += 1
                if silent_chunks_after_speech >= max_silent_chunks:
                    break

            if chunk_index >= max_total_chunks:
                break

        duration_s = total_frames / float(self.config.sample_rate)
        if not heard_speech or duration_s < self.config.min_speech_s:
            raise VoicePipelineError(
                VoiceErrorStage.RECORDING,
                "No speech was detected from the microphone input.",
            )

        elapsed_ms = int((monotonic() - started_at) * 1000)
        return self._write_recording(
            temp_dir=temp_dir,
            audio_bytes=b"".join(audio_chunks),
            frame_count=total_frames,
            duration_ms=max(elapsed_ms, int(duration_s * 1000)),
            overflow_detected=overflow_detected,
        )

    def _write_recording(
        self,
        *,
        temp_dir: Path,
        audio_bytes: bytes,
        frame_count: int,
        duration_ms: int,
        overflow_detected: bool,
    ) -> RecordedAudio:
        file_path = temp_dir / f"input_{uuid4().hex}.wav"
        with wave.open(str(file_path), "wb") as wav_file:
            wav_file.setnchannels(self.config.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.config.sample_rate)
            wav_file.writeframes(audio_bytes)
        return RecordedAudio(
            file_path=str(file_path),
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            duration_ms=duration_ms,
            frame_count=frame_count,
            container_format="wav",
            overflow_detected=overflow_detected,
        )

    def _load_sounddevice(self) -> object:
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


def build_audio_recorder(config: VoiceConfig) -> AudioRecorder:
    return BlockingWavRecorder(config)


def describe_audio_devices(*, sounddevice_module: object | None = None) -> str:
    sounddevice = sounddevice_module
    if sounddevice is None:
        try:
            import sounddevice as imported_sounddevice  # type: ignore
        except ModuleNotFoundError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.RECORDING,
                (
                    "sounddevice is not available in the current Python interpreter: "
                    f"{sys.executable}. If you installed it inside your Conda environment, "
                    "start voice mode with `python src/app/main_voice.py` instead of `py -3 ...`."
                ),
            ) from exc
        sounddevice = imported_sounddevice

    raw_devices = sounddevice.query_devices()  # type: ignore[attr-defined]
    default_device = getattr(sounddevice, "default", None)
    default_input_index = None
    if default_device is not None and hasattr(default_device, "device"):
        device_pair = getattr(default_device, "device")
        if isinstance(device_pair, (list, tuple)) and device_pair:
            default_input_index = device_pair[0]

    input_lines: list[str] = []
    for index, raw_device in enumerate(raw_devices):
        if not isinstance(raw_device, dict):
            continue
        max_input_channels = int(raw_device.get("max_input_channels", 0) or 0)
        if max_input_channels <= 0:
            continue
        name = str(raw_device.get("name", f"device-{index}")).strip() or f"device-{index}"
        default_suffix = " [default]" if index == default_input_index else ""
        sample_rate = int(float(raw_device.get("default_samplerate", 0) or 0))
        input_lines.append(
            f"[{index}] {name} | in={max_input_channels} | default_sr={sample_rate}{default_suffix}"
        )

    if not input_lines:
        return "No input-capable audio devices were found."

    return "Available input devices:\n" + "\n".join(input_lines)
