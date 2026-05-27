from __future__ import annotations

from dataclasses import dataclass

from src.config.loader import VoiceConfig
from src.voice.microphone_stream import AudioChunk


@dataclass(frozen=True)
class BargeInUpdate:
    interrupted: bool
    rms: float
    reason: str | None = None


class BargeInDetector:
    def __init__(self, config: VoiceConfig) -> None:
        self.threshold = config.interrupt_rms_threshold
        self.enabled = config.interrupt_enabled and config.microphone_interrupt_enabled

    def consume(self, chunk: AudioChunk) -> BargeInUpdate:
        rms = float(chunk.rms)
        if self.enabled and rms >= self.threshold:
            return BargeInUpdate(
                interrupted=True,
                rms=rms,
                reason=f"microphone_rms:{int(rms)}",
            )
        return BargeInUpdate(interrupted=False, rms=rms)
