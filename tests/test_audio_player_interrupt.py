from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.audio_player import InterruptToken
from src.voice.models import AudioChunkLike
from src.voice.playback import NullAudioPlayback


class AudioPlayerInterruptTests(unittest.TestCase):
    def test_preinterrupted_stream_does_not_consume_chunks(self) -> None:
        token = InterruptToken()
        token.interrupt("test_interrupt")
        consumed: list[int] = []

        def chunks():
            consumed.append(1)
            yield AudioChunkLike(
                audio_bytes=b"",
                provider_name="fake",
                model_name="fake",
            )

        result = NullAudioPlayback().play_stream(chunks(), interrupt_token=token)

        self.assertTrue(result.interrupted)
        self.assertEqual(result.stop_reason, "test_interrupt")
        self.assertEqual(result.chunk_count, 0)
        self.assertEqual(consumed, [])

    def test_interrupt_token_records_reason(self) -> None:
        token = InterruptToken()

        token.interrupt("keyboard_escape")

        self.assertTrue(token.is_interrupted())
        self.assertEqual(token.reason, "keyboard_escape")


if __name__ == "__main__":
    unittest.main()
