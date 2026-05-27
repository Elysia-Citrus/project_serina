from __future__ import annotations

from typing import Protocol

from src.voice.models import ASRResult, RecordedAudio


class STTService(Protocol):
    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        ...
