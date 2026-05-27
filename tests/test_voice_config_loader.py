from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_app_config, load_voice_config
from tests.support import TemporaryWorkspace


class VoiceConfigLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_default_voice_config_loads_from_repo(self) -> None:
        config = load_app_config()

        self.assertEqual(config.voice.language, "zh-CN")
        self.assertIsNone(config.voice.input_device)
        self.assertEqual(config.voice.recording_mode, "endpoint_once")
        self.assertEqual(config.voice.asr_provider, "myneuro_asr")
        self.assertEqual(config.voice.asr_compute_device, "cpu")
        self.assertEqual(
            config.voice.myneuro_asr_url,
            "http://127.0.0.1:1000/v1/upload_audio",
        )
        self.assertEqual(config.voice.tts_provider, "gpt_sovits_v2")
        self.assertEqual(config.voice.tts_model, "gpt-sovits-v2")
        self.assertFalse(config.voice.auto_listen_enabled)
        self.assertEqual(config.voice.default_voice_profile_id, "serina_main")
        self.assertEqual(config.voice.voice_profiles_path, "voice_profiles.yaml")
        self.assertTrue(config.voice.local_tts_enabled)
        self.assertTrue(config.voice.stream_playback_enabled)
        self.assertEqual(
            config.voice.gpt_sovits_v2_url,
            "http://127.0.0.1:5000/tts",
        )
        self.assertFalse(config.voice.tts_warmup_on_boot)
        self.assertTrue(config.voice.interrupt_enabled)
        self.assertTrue(config.voice.keyboard_interrupt_enabled)
        self.assertTrue(config.voice.microphone_interrupt_enabled)
        self.assertEqual(config.voice.interrupt_rms_threshold, 600)
        self.assertTrue(config.voice.asr_base_url.endswith("/v1"))
        self.assertTrue(config.voice.tts_base_url.endswith("/api/v1"))

    def test_custom_voice_config_supports_temp_directory_and_limits(self) -> None:
        config_path = self.workspace.root / "voice_config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "enabled: true",
                    "language: zh-CN",
                    "input_device: 3",
                    "output_device: Speaker A",
                    "sample_rate: 22050",
                    "channels: 1",
                    "chunk_ms: 150",
                    "record_timeout_s: 12",
                    "silence_timeout_s: 0.8",
                    "min_speech_s: 0.3",
                    "recording_mode: fixed_duration",
                    "fixed_record_seconds: 4",
                    "vad_enabled: true",
                    "partial_transcript_enabled: true",
                    "partial_commit_strategy: console_latest",
                    "asr_provider: dashscope",
                    "asr_model: paraformer-realtime-v2",
                    "asr_compute_device: auto",
                    "asr_api_key_env: TEST_ASR_KEY",
                    "asr_api_key: test-asr",
                    "asr_base_url: https://example.com/asr",
                    "myneuro_asr_url: http://127.0.0.1:1001/v1/upload_audio",
                    "myneuro_asr_timeout_s: 30",
                    "tts_provider: dashscope_tts",
                    "tts_model: cosyvoice-v3-flash",
                    "tts_voice_preset: longanyang",
                    "tts_api_key_env: TEST_TTS_KEY",
                    "tts_api_key: test-tts",
                    "tts_base_url: https://example.com/tts",
                    "gpt_sovits_v2_url: http://127.0.0.1:5001/tts",
                    "gpt_sovits_v2_ref_audio_path: role_voice_api/neuro/custom.wav",
                    "gpt_sovits_v2_prompt_text: custom ref text",
                    "gpt_sovits_v2_text_lang: zh",
                    "gpt_sovits_v2_prompt_lang: en",
                    "gpt_sovits_v2_text_split_method: cut5",
                    "gpt_sovits_v2_batch_size: 2",
                    "gpt_sovits_v2_streaming_mode: 2",
                    "gpt_sovits_v2_media_type: wav",
                    "gpt_sovits_v2_timeout_s: 40",
                    "myneuro_memos_base_url: http://127.0.0.1:8001",
                    "default_voice_profile_id: serina_main",
                    "voice_profiles_path: custom_voice_profiles.yaml",
                    "local_tts_enabled: true",
                    "primary_tts_runtime_url: http://127.0.0.1:6001",
                    "clone_tts_runtime_url: http://127.0.0.1:6002",
                    "stream_playback_enabled: false",
                    "tts_warmup_on_boot: true",
                    "allow_spoken_commands: true",
                    "echo_transcript_to_console: false",
                    "debug_save_input_audio: true",
                    "debug_save_output_audio: true",
                    "auto_listen_enabled: true",
                    "interrupt_enabled: true",
                    "keyboard_interrupt_enabled: false",
                    "microphone_interrupt_enabled: true",
                    "interrupt_rms_threshold: 900",
                    f"temp_audio_dir: {self.workspace.root.as_posix()}",
                ]
            ),
            encoding="utf-8",
        )

        voice = load_voice_config(config_path)

        self.assertTrue(voice.enabled)
        self.assertEqual(voice.input_device, 3)
        self.assertEqual(voice.output_device, "Speaker A")
        self.assertEqual(voice.recording_mode, "fixed_duration")
        self.assertEqual(voice.fixed_record_seconds, 4.0)
        self.assertEqual(voice.sample_rate, 22050)
        self.assertTrue(voice.vad_enabled)
        self.assertTrue(voice.partial_transcript_enabled)
        self.assertEqual(voice.partial_commit_strategy, "console_latest")
        self.assertEqual(voice.asr_compute_device, "auto")
        self.assertEqual(voice.myneuro_asr_url, "http://127.0.0.1:1001/v1/upload_audio")
        self.assertEqual(voice.myneuro_asr_timeout_s, 30.0)
        self.assertEqual(voice.gpt_sovits_v2_url, "http://127.0.0.1:5001/tts")
        self.assertEqual(voice.gpt_sovits_v2_ref_audio_path, "role_voice_api/neuro/custom.wav")
        self.assertEqual(voice.gpt_sovits_v2_prompt_text, "custom ref text")
        self.assertEqual(voice.gpt_sovits_v2_batch_size, 2)
        self.assertEqual(voice.gpt_sovits_v2_streaming_mode, 2)
        self.assertEqual(voice.myneuro_memos_base_url, "http://127.0.0.1:8001")
        self.assertEqual(voice.default_voice_profile_id, "serina_main")
        self.assertEqual(voice.voice_profiles_path, "custom_voice_profiles.yaml")
        self.assertTrue(voice.local_tts_enabled)
        self.assertEqual(voice.primary_tts_runtime_url, "http://127.0.0.1:6001")
        self.assertEqual(voice.clone_tts_runtime_url, "http://127.0.0.1:6002")
        self.assertFalse(voice.stream_playback_enabled)
        self.assertTrue(voice.tts_warmup_on_boot)
        self.assertTrue(voice.allow_spoken_commands)
        self.assertTrue(voice.debug_save_input_audio)
        self.assertTrue(voice.auto_listen_enabled)
        self.assertTrue(voice.interrupt_enabled)
        self.assertFalse(voice.keyboard_interrupt_enabled)
        self.assertTrue(voice.microphone_interrupt_enabled)
        self.assertEqual(voice.interrupt_rms_threshold, 900)
        self.assertEqual(voice.temp_audio_dir, self.workspace.root.as_posix())


if __name__ == "__main__":
    unittest.main()
