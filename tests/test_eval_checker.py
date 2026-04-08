from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evals.checker import classify_length_band, run_response_checks
from src.evals.models import EvalCase


class EvalCheckerTests(unittest.TestCase):
    def test_classify_length_band(self) -> None:
        self.assertEqual(classify_length_band("你好"), "short")
        self.assertEqual(classify_length_band("你" * 50), "medium")
        self.assertEqual(classify_length_band("你" * 140), "long")

    def test_forbidden_and_ai_disclosure_checks(self) -> None:
        case = EvalCase(
            id="demo",
            input="test",
            expected_scene="casual_chat",
            expected_length_band="short",
            forbidden_patterns=("作为(?:一个)?(?:AI|人工智能|语言模型)",),
        )

        check = run_response_checks(case, "作为AI助手，我来帮你。")

        self.assertTrue(check.length_band_match)
        self.assertTrue(check.ai_disclaimer_detected)
        self.assertTrue(check.forbidden_hits)
        self.assertIn("forbidden_pattern_hit", check.failure_reasons)


if __name__ == "__main__":
    unittest.main()
