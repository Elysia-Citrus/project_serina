from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.microphone_stream import resolve_input_stream_settings
from src.voice.recorder import BlockingWavRecorder, describe_audio_devices
from tests.support import TemporaryWorkspace, build_test_config


def _pcm_chunk(sample_value: int, frames: int, channels: int = 1) -> bytes:
    samples = [sample_value] * frames * channels
    return struct.pack("<" + ("h" * len(samples)), *samples)


class _FakeRawInputStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.index = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, frames: int):
        if self.index >= len(self.chunks):
            return (_pcm_chunk(0, frames), False)
        chunk = self.chunks[self.index]
        self.index += 1
        return (chunk, False)


class _FakeSoundDeviceModule:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.kwargs = None
        self.default = type("_Default", (), {"device": (1, 2)})()
        self.invalid_sample_rates: set[int] = set()

    def RawInputStream(self, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        return _FakeRawInputStream(self.chunks)

    def check_input_settings(self, **kwargs):  # type: ignore[no-untyped-def]
        samplerate = int(kwargs.get("samplerate"))
        if samplerate in self.invalid_sample_rates:
            raise RuntimeError(
                f"Error opening RawInputStream: Invalid sample rate [PaErrorCode -9997] ({samplerate})"
            )

    def query_devices(self):  # type: ignore[no-untyped-def]
        return [
            {
                "name": "Built-in Output",
                "max_input_channels": 0,
                "default_samplerate": 48000,
            },
            {
                "name": "USB Mic",
                "max_input_channels": 1,
                "default_samplerate": 16000,
            },
            {
                "name": "Headset Mic",
                "max_input_channels": 2,
                "default_samplerate": 44100,
            },
        ]


class VoiceRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_recorder_writes_wav_after_speech_then_silence(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            enabled=True,
            temp_audio_dir=str(self.workspace.root),
            chunk_ms=200,
            record_timeout_s=2.0,
            silence_timeout_s=0.4,
            silence_rms_threshold=300,
        )
        chunk_frames = int(config.sample_rate * config.chunk_ms / 1000)
        fake_sounddevice = _FakeSoundDeviceModule(
            [
                _pcm_chunk(0, chunk_frames),
                _pcm_chunk(800, chunk_frames),
                _pcm_chunk(900, chunk_frames),
                _pcm_chunk(0, chunk_frames),
                _pcm_chunk(0, chunk_frames),
            ]
        )
        recorder = BlockingWavRecorder(
            config,
            sounddevice_module=fake_sounddevice,
        )

        recorded_audio = recorder.capture_to_wav()

        self.assertTrue(Path(recorded_audio.file_path).exists())
        self.assertEqual(recorded_audio.container_format, "wav")
        self.assertGreater(recorded_audio.duration_ms, 0)
        self.assertEqual(fake_sounddevice.kwargs["device"], config.input_device)

    def test_recorder_raises_when_no_speech_detected(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            enabled=True,
            temp_audio_dir=str(self.workspace.root),
            chunk_ms=200,
            record_timeout_s=1.0,
            silence_timeout_s=0.4,
            silence_rms_threshold=300,
        )
        chunk_frames = int(config.sample_rate * config.chunk_ms / 1000)
        fake_sounddevice = _FakeSoundDeviceModule(
            [_pcm_chunk(0, chunk_frames) for _ in range(5)]
        )
        recorder = BlockingWavRecorder(
            config,
            sounddevice_module=fake_sounddevice,
        )

        with self.assertRaises(VoicePipelineError) as context:
            recorder.capture_to_wav()

        self.assertEqual(context.exception.stage, VoiceErrorStage.RECORDING)

    def test_fixed_duration_recording_saves_audio_without_local_speech_gate(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            enabled=True,
            temp_audio_dir=str(self.workspace.root),
            recording_mode="fixed_duration",
            fixed_record_seconds=0.6,
            chunk_ms=200,
        )
        chunk_frames = int(config.sample_rate * config.chunk_ms / 1000)
        fake_sounddevice = _FakeSoundDeviceModule(
            [_pcm_chunk(0, chunk_frames) for _ in range(4)]
        )
        recorder = BlockingWavRecorder(
            config,
            sounddevice_module=fake_sounddevice,
        )

        recorded_audio = recorder.capture_to_wav()

        self.assertTrue(Path(recorded_audio.file_path).exists())
        self.assertGreater(recorded_audio.duration_ms, 0)
        self.assertEqual(recorded_audio.container_format, "wav")

    def test_describe_audio_devices_lists_input_capable_devices(self) -> None:
        fake_sounddevice = _FakeSoundDeviceModule([])

        description = describe_audio_devices(sounddevice_module=fake_sounddevice)

        self.assertIn("Available input devices:", description)
        self.assertIn("[1] USB Mic", description)
        self.assertIn("[2] Headset Mic", description)
        self.assertIn("[default]", description)

    def test_open_chunk_source_yields_pcm_chunks(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            chunk_ms=200,
        )
        chunk_frames = int(config.sample_rate * config.chunk_ms / 1000)
        fake_sounddevice = _FakeSoundDeviceModule([_pcm_chunk(600, chunk_frames)])
        recorder = BlockingWavRecorder(
            config,
            sounddevice_module=fake_sounddevice,
        )

        chunk = next(recorder.open_chunk_source().iter_chunks())

        self.assertEqual(chunk.sample_rate, config.sample_rate)
        self.assertEqual(chunk.channels, config.channels)
        self.assertEqual(chunk.chunk_ms, config.chunk_ms)
        self.assertGreater(chunk.rms, 0)

    def test_input_stream_settings_fall_back_to_device_default_sample_rate(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            input_device=2,
            sample_rate=16000,
            channels=1,
            chunk_ms=100,
        )
        fake_sounddevice = _FakeSoundDeviceModule([])
        fake_sounddevice.invalid_sample_rates.add(16000)

        settings = resolve_input_stream_settings(
            config,
            sounddevice=fake_sounddevice,
        )

        self.assertEqual(settings.stream_sample_rate, 44100)
        self.assertEqual(settings.target_sample_rate, 16000)
        self.assertTrue(settings.requires_resample)


if __name__ == "__main__":
    unittest.main()
