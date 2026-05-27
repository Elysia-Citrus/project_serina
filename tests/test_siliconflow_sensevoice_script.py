from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "test_siliconflow_sensevoice.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "test_siliconflow_sensevoice_script_module",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load SiliconFlow test script module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


class SiliconFlowSenseVoiceScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _load_script_module()

    def test_extract_transcript_prefers_top_level_text(self) -> None:
        transcript = self.script.extract_transcript(
            {
                "text": "你好，这是测试转写。",
                "output": {"text": "ignored"},
            }
        )

        self.assertEqual(transcript, "你好，这是测试转写。")

    def test_extract_transcript_falls_back_to_nested_data(self) -> None:
        transcript = self.script.extract_transcript(
            {
                "data": {"transcript": "第二条测试结果"},
            }
        )

        self.assertEqual(transcript, "第二条测试结果")

    def test_coerce_device_selector_accepts_numeric_index(self) -> None:
        self.assertEqual(self.script._coerce_device_selector("35"), 35)
        self.assertEqual(self.script._coerce_device_selector("USB Mic"), "USB Mic")


if __name__ == "__main__":
    unittest.main()
