from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.asr import MyNeuroASRProvider, SiliconFlowSenseVoiceASRProvider, build_asr_provider
from src.voice.asr import LocalSherpaSenseVoiceASRProvider, _load_wav_as_float32
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.models import RecordedAudio
from tests.support import TemporaryWorkspace, build_test_config


class VoiceASRTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.audio_path = self.workspace.root / "input.wav"
        self.audio_path.write_bytes(b"RIFFfakewav")

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def _build_recorded_audio(self) -> RecordedAudio:
        return RecordedAudio(
            file_path=str(self.audio_path),
            sample_rate=16000,
            channels=1,
            duration_ms=1000,
            frame_count=16000,
        )

    def test_build_asr_provider_supports_siliconflow(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            asr_provider="siliconflow",
            asr_model="FunAudioLLM/SenseVoiceSmall",
            asr_api_key="test-key",
            asr_base_url="https://api.siliconflow.cn/v1",
        )

        provider = build_asr_provider(config)

        self.assertIsInstance(provider, SiliconFlowSenseVoiceASRProvider)

    def test_build_asr_provider_supports_myneuro(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            asr_provider="myneuro_asr",
            asr_model="my-neuro-asr-api",
        )

        provider = build_asr_provider(config)

        self.assertIsInstance(provider, MyNeuroASRProvider)

    def test_myneuro_provider_wraps_unexpected_client_error(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            asr_provider="myneuro_asr",
            asr_model="my-neuro-asr-api",
            myneuro_asr_url="http://127.0.0.1:1000/v1/upload_audio",
        )
        provider = MyNeuroASRProvider(config)
        provider.client.transcribe_file = lambda audio_path: (_ for _ in ()).throw(  # type: ignore[method-assign]
            ValueError("bad response shape")
        )

        with self.assertRaises(VoicePipelineError) as context:
            provider.transcribe(self._build_recorded_audio(), language="zh-CN")

        self.assertEqual(context.exception.stage, VoiceErrorStage.TRANSCRIBING)
        self.assertIn("http://127.0.0.1:1000/v1/upload_audio", str(context.exception))
        self.assertIn("ValueError", str(context.exception))

    def test_build_asr_provider_supports_local_sherpa(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            asr_provider="sherpa_onnx_sensevoice",
            asr_model="sensevoice-small-int8",
        )

        provider = build_asr_provider(config)

        self.assertIsInstance(provider, LocalSherpaSenseVoiceASRProvider)

    def test_siliconflow_provider_extracts_top_level_text(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            asr_provider="siliconflow",
            asr_model="FunAudioLLM/SenseVoiceSmall",
            asr_api_key="test-key",
            asr_base_url="https://api.siliconflow.cn/v1",
        )
        provider = SiliconFlowSenseVoiceASRProvider(config)
        provider._post_transcription_request = lambda audio_path: {  # type: ignore[method-assign]
            "text": "现在我们在测试一个新的版本。"
        }

        result = provider.transcribe(self._build_recorded_audio(), language="zh-CN")

        self.assertEqual(result.provider_name, "siliconflow")
        self.assertEqual(result.text, "现在我们在测试一个新的版本。")

    def test_siliconflow_provider_rejects_empty_transcript(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            asr_provider="siliconflow",
            asr_model="FunAudioLLM/SenseVoiceSmall",
            asr_api_key="test-key",
            asr_base_url="https://api.siliconflow.cn/v1",
        )
        provider = SiliconFlowSenseVoiceASRProvider(config)
        provider._post_transcription_request = lambda audio_path: {"text": ""}  # type: ignore[method-assign]

        with self.assertRaises(VoicePipelineError) as context:
            provider.transcribe(self._build_recorded_audio(), language="zh-CN")

        self.assertEqual(context.exception.stage, VoiceErrorStage.TRANSCRIBING)

    def test_local_sherpa_provider_extracts_text_from_mock_runtime(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            asr_provider="sherpa_onnx_sensevoice",
            asr_model="sensevoice-small-int8",
            asr_compute_device="cpu",
        )
        provider = LocalSherpaSenseVoiceASRProvider(config)

        class _FakeStream:
            def __init__(self) -> None:
                self.result = type("_Result", (), {"text": "本地模型已经接上了"})()

            def accept_waveform(self, sample_rate, samples) -> None:  # type: ignore[no-untyped-def]
                self.sample_rate = sample_rate
                self.samples = samples

        class _FakeRecognizer:
            def create_stream(self) -> _FakeStream:
                return _FakeStream()

            def decode_stream(self, stream) -> None:  # type: ignore[no-untyped-def]
                self.stream = stream

        provider._get_runtime = lambda: (_FakeRecognizer(), object())  # type: ignore[method-assign]

        from unittest.mock import patch

        with patch(
            "src.voice.asr._load_wav_as_float32",
            return_value=([0.0, 0.1, 0.0], 16000),
        ):
            result = provider.transcribe(self._build_recorded_audio(), language="zh-CN")

        self.assertEqual(result.provider_name, "sherpa_onnx_sensevoice")
        self.assertEqual(result.text, "本地模型已经接上了")

    def test_load_wav_prefers_dominant_stereo_channel(self) -> None:
        stereo_path = self.workspace.root / "stereo.wav"
        with wave.open(str(stereo_path), "wb") as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            frames = bytearray()
            for _ in range(320):
                frames.extend((0).to_bytes(2, "little", signed=True))
                frames.extend((2400).to_bytes(2, "little", signed=True))
            wav_file.writeframes(bytes(frames))

        try:
            import numpy as np
        except ModuleNotFoundError:
            self.skipTest("numpy is required for float32 WAV conversion checks.")

        samples, sample_rate = _load_wav_as_float32(stereo_path, np=np)

        self.assertEqual(sample_rate, 16000)
        self.assertEqual(len(samples), 320)
        self.assertGreater(float(np.mean(np.abs(samples))), 0.05)


if __name__ == "__main__":
    unittest.main()
