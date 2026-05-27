from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VoiceErrorStage(str, Enum):
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    PLAYBACK = "playback"


@dataclass(frozen=True)
class VoicePipelineError(RuntimeError):
    stage: VoiceErrorStage
    message: str

    def __str__(self) -> str:
        return self.message
