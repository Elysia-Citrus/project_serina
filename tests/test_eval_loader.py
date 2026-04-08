from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evals.loader import load_eval_cases


class EvalLoaderTests(unittest.TestCase):
    def test_loader_filters_disabled_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.jsonl"
            rows = [
                {
                    "id": "enabled",
                    "input": "你好",
                    "expected_scene": "greeting",
                    "expected_length_band": "short",
                    "enabled": True,
                },
                {
                    "id": "disabled",
                    "input": "这条不跑",
                    "expected_scene": "casual_chat",
                    "expected_length_band": "short",
                    "enabled": False,
                },
            ]
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            cases = load_eval_cases(path, enabled_only=True)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, "enabled")


if __name__ == "__main__":
    unittest.main()
