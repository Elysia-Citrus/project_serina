from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.chunking import SpeechChunker


class SpeechChunkerTests(unittest.TestCase):
    def test_chunker_groups_one_to_two_sentences(self) -> None:
        chunker = SpeechChunker(max_sentences_per_chunk=2, max_chars_per_chunk=40)

        chunks = chunker.chunk("第一句。第二句！第三句？第四句。")

        self.assertEqual(chunks, ("第一句。第二句！", "第三句？第四句。"))

    def test_chunker_splits_long_sentence_deterministically(self) -> None:
        chunker = SpeechChunker(max_sentences_per_chunk=2, max_chars_per_chunk=12)

        chunks = chunker.chunk("这一句非常非常长，需要在逗号这里，和后面的部分拆开。")

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(chunk.strip() for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
