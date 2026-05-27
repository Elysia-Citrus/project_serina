from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evals.loader import load_eval_cases


class EvalLoaderTests(unittest.TestCase):
    def test_loader_filters_disabled_cases(self) -> None:
        temp_dir = PROJECT_ROOT / ".tmp_test_workspaces" / "eval_loader_case_1"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = temp_dir / "cases.jsonl"
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
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_accepts_memory_setup(self) -> None:
        temp_dir = PROJECT_ROOT / ".tmp_test_workspaces" / "eval_loader_case_2"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            path = temp_dir / "cases.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "id": "memory_case",
                        "input": "你还记得我上次提的项目吗",
                        "expected_scene": "deep_discussion",
                        "expected_length_band": "medium",
                        "memory_setup": [
                            {
                                "category": "task_commitment",
                                "content": "用户最近在推进评测框架",
                                "content_summary": "评测框架推进中",
                                "confidence": 0.9,
                            }
                        ],
                        "should_reference_recent_context": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cases = load_eval_cases(path, enabled_only=True)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0].memory_setup[0]["category"], "task_commitment")
            self.assertTrue(cases[0].should_reference_recent_context)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
