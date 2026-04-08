from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dialogue.prompt_builder import infer_scene


class InferSceneTests(unittest.TestCase):
    def test_greeting_scene(self) -> None:
        self.assertEqual(infer_scene("你好"), "greeting")

    def test_comfort_scene(self) -> None:
        self.assertEqual(infer_scene("今天真的有点累。"), "comfort")

    def test_correction_scene(self) -> None:
        self.assertEqual(infer_scene("这事还是之后再说吧。"), "correction")

    def test_deep_discussion_scene(self) -> None:
        self.assertEqual(infer_scene("你怎么看长期主义？"), "deep_discussion")

    def test_default_scene(self) -> None:
        self.assertEqual(infer_scene("我刚吃完饭。"), "casual_chat")


if __name__ == "__main__":
    unittest.main()
