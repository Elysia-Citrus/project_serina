from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.memory.startup import detect_continuation_cue


class ContinuationCueTests(unittest.TestCase):
    def test_short_continuation_phrases_are_detected(self) -> None:
        self.assertTrue(detect_continuation_cue("继续"))
        self.assertTrue(detect_continuation_cue("上次那个问题"))
        self.assertTrue(detect_continuation_cue("那然后呢"))
        self.assertTrue(detect_continuation_cue("我们继续"))

    def test_plain_greeting_does_not_trigger_continuation(self) -> None:
        self.assertFalse(detect_continuation_cue("你好"))
        self.assertFalse(detect_continuation_cue("晚上好"))


if __name__ == "__main__":
    unittest.main()
