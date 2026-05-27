from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class AvatarEvent:
    event_type: str
    payload: dict[str, object] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )


class AvatarEventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[AvatarEvent], None]] = []
        self.events: list[AvatarEvent] = []

    def subscribe(self, callback: Callable[[AvatarEvent], None]) -> None:
        self._subscribers.append(callback)

    def emit(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        event = AvatarEvent(event_type=event_type, payload=payload or {})
        self.events.append(event)
        for callback in list(self._subscribers):
            callback(event)
