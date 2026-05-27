from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.endpoint import RmsEndpointDetector
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.microphone_stream import AudioChunk
from src.voice.transcript import TranscriptAggregator
from tests.support import TemporaryWorkspace, build_test_config


class VoiceEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_rms_endpoint_detector_finalizes_after_trailing_silence(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            temp_audio_dir=str(self.workspace.root),
            chunk_ms=100,
            silence_timeout_s=0.2,
            min_speech_s=0.2,
            silence_rms_threshold=300,
        )
        detector = RmsEndpointDetector(config)
        chunks = [
            AudioChunk(b"\x00\x00" * 1600, 16000, 1, 100, 0),
            AudioChunk(b"\x01\x00" * 1600, 16000, 1, 100, 900),
            AudioChunk(b"\x01\x00" * 1600, 16000, 1, 100, 850),
            AudioChunk(b"\x00\x00" * 1600, 16000, 1, 100, 0),
            AudioChunk(b"\x00\x00" * 1600, 16000, 1, 100, 0),
        ]

        final_update = None
        for chunk in chunks:
            final_update = detector.consume(chunk)
            if final_update.endpoint_detected:
                break

        assert final_update is not None
        self.assertTrue(final_update.endpoint_detected)
        recorded_audio = detector.build_recorded_audio(self.workspace.root)
        self.assertTrue(Path(recorded_audio.file_path).exists())
        self.assertGreater(recorded_audio.duration_ms, 0)

    def test_endpoint_detector_rejects_short_or_empty_audio(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            temp_audio_dir=str(self.workspace.root),
            chunk_ms=100,
            silence_timeout_s=0.2,
            min_speech_s=0.4,
            silence_rms_threshold=300,
        )
        detector = RmsEndpointDetector(config)
        detector.consume(AudioChunk(b"\x00\x00" * 1600, 16000, 1, 100, 0))
        detector.consume(AudioChunk(b"\x01\x00" * 1600, 16000, 1, 100, 900))
        detector.consume(AudioChunk(b"\x00\x00" * 1600, 16000, 1, 100, 0))
        detector.consume(AudioChunk(b"\x00\x00" * 1600, 16000, 1, 100, 0))

        with self.assertRaises(VoicePipelineError) as context:
            detector.build_recorded_audio(self.workspace.root)

        self.assertEqual(context.exception.stage, VoiceErrorStage.RECORDING)

    def test_transcript_aggregator_normalizes_and_dedupes_suffix(self) -> None:
        config = replace(
            build_test_config(self.workspace.db_path).voice,
            partial_transcript_enabled=True,
            partial_commit_strategy="stable_prefix",
        )
        aggregator = TranscriptAggregator(config)

        partial = aggregator.update_partial("你好世")
        stable = aggregator.update_partial("你好世界")
        final = aggregator.finalize("你好  世界界界")

        self.assertEqual(partial.normalized_text, "你好世")
        self.assertTrue(stable.display_text is not None)
        self.assertEqual(final.normalized_text, "你好 世界")


if __name__ == "__main__":
    unittest.main()
