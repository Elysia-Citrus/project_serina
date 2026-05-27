from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.local_runtime_server import LocalRuntimeConfig, WindowsSapiAdapter
from src.voice.models import TTSRequest


def _make_wav_bytes(duration_ms: int = 120, sample_rate: int = 24000) -> bytes:
    frame_count = max(1, int(sample_rate * duration_ms / 1000))
    frames = b"\x00\x00" * frame_count
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return buffer.getvalue()


class WindowsSapiAdapterTests(unittest.TestCase):
    def test_healthz_and_synthesize_use_powershell_helper(self) -> None:
        adapter = WindowsSapiAdapter()
        runtime_config = LocalRuntimeConfig(
            runtime_id="primary",
            bind_host="127.0.0.1",
            bind_port=51771,
            provider_name="cosyvoice_local",
            adapter="windows_sapi",
            model_name="windows-sapi-zh",
            voice_name="Microsoft Huihui Desktop - Chinese (Simplified)",
            rate=0,
            volume=100,
        )

        def _fake_run(command, capture_output, text, encoding, timeout, check):  # type: ignore[no-untyped-def]
            if "-Action" in command:
                action = command[command.index("-Action") + 1]
            else:
                action = ""
            if action == "list-voices":
                return _CompletedProcess(
                    0,
                    json.dumps(
                        {
                            "voices": [
                                "Microsoft Zira Desktop - English (United States)",
                                "Microsoft Huihui Desktop - Chinese (Simplified)",
                            ]
                        }
                    ),
                )
            if action == "synthesize":
                output_path = Path(command[command.index("-OutputPath") + 1])
                output_path.write_bytes(_make_wav_bytes())
                return _CompletedProcess(
                    0,
                    json.dumps(
                        {
                            "output_path": str(output_path),
                            "voice_name": "Microsoft Huihui Desktop - Chinese (Simplified)",
                        }
                    ),
                )
            return _CompletedProcess(1, "", "unexpected action")

        with patch("src.voice.local_runtime_server.subprocess.run", side_effect=_fake_run):
            health = adapter.healthz()
            self.assertEqual(health["status"], "ok")
            self.assertEqual(
                health["selected_voice"],
                "Microsoft Huihui Desktop - Chinese (Simplified)",
            )

            synthesized = adapter.synthesize(
                TTSRequest(text="你好，老师。", model_name="windows-sapi-zh"),
                runtime_config=runtime_config,
                profile=None,
            )
            self.assertEqual(synthesized.container_format, "wav")
            self.assertGreater(len(synthesized.audio_bytes), 100)


class _CompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


if __name__ == "__main__":
    unittest.main()
