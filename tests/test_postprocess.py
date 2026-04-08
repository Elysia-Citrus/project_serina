from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dialogue.postprocess import postprocess_response


class PostprocessTests(unittest.TestCase):
    def test_strips_role_prefix_and_ai_disclaimer(self) -> None:
        result = postprocess_response(
            "Serina：作为AI助手，我在。",
            fallback_text="老师，我在。",
        )
        self.assertEqual(result.final_text, "我在。")
        self.assertIn("strip_role_prefix", result.applied_rules)
        self.assertIn("strip_ai_disclaimer", result.applied_rules)

    def test_fallback_for_empty_response(self) -> None:
        result = postprocess_response("   \n  ", fallback_text="老师，我在。")
        self.assertEqual(result.final_text, "老师，我在。")
        self.assertTrue(result.used_fallback)
        self.assertIn("fallback_empty_response", result.applied_rules)


if __name__ == "__main__":
    unittest.main()
