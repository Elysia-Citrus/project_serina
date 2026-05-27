from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Iterable, Protocol

from src.voice.models import AudioChunkLike, PlaybackResult, SynthesizedAudio


@dataclass(frozen=True)
class InterruptState:
    interrupted: bool = False
    reason: str | None = None


class InterruptToken:
    def __init__(self) -> None:
        self._event = Event()
        self._reason: str | None = None

    def interrupt(self, reason: str = "interrupt") -> None:
        self._reason = reason
        self._event.set()

    def is_interrupted(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def state(self) -> InterruptState:
        return InterruptState(interrupted=self.is_interrupted(), reason=self.reason)


class AudioPlayer(Protocol):
    def play(
        self,
        synthesized_audio: SynthesizedAudio,
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        ...

    def play_stream(
        self,
        audio_chunks: Iterable[AudioChunkLike],
        *,
        output_device: str | int | None = None,
        interrupt_token: InterruptToken | None = None,
    ) -> PlaybackResult:
        ...

    def stop(self, reason: str = "interrupt") -> None:
        ...
