from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from uuid import uuid4

from src.utils.text_utils import safe_preview


@dataclass
class TurnTrace:
    turn_id: str
    started_at: str
    debug_max_preview_chars: int
    started_monotonic: float = field(default_factory=monotonic)
    scene: str | None = None
    user_input_preview: str | None = None
    cleaned_input_preview: str | None = None
    history_message_count: int = 0
    model_name: str | None = None
    request_latency_ms: int | None = None
    response_preview: str | None = None
    postprocessed_response_preview: str | None = None

    @classmethod
    def create(cls, preview_chars: int) -> "TurnTrace":
        return cls(
            turn_id=uuid4().hex[:12],
            started_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
            debug_max_preview_chars=max(40, preview_chars),
        )

    def set_user_input(
        self,
        raw_input: str,
        cleaned_input: str,
        history_message_count: int,
    ) -> None:
        self.user_input_preview = safe_preview(raw_input, self.debug_max_preview_chars)
        self.cleaned_input_preview = safe_preview(cleaned_input, self.debug_max_preview_chars)
        self.history_message_count = history_message_count

    def set_scene(self, scene: str) -> None:
        self.scene = scene

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name

    def set_request_latency(self, latency_ms: int) -> None:
        self.request_latency_ms = latency_ms

    def set_response_preview(self, text: str) -> None:
        self.response_preview = safe_preview(text, self.debug_max_preview_chars)

    def set_postprocessed_response_preview(self, text: str) -> None:
        self.postprocessed_response_preview = safe_preview(
            text, self.debug_max_preview_chars
        )

    def elapsed_ms(self) -> int:
        return int((monotonic() - self.started_monotonic) * 1000)

    def as_log_fields(self) -> dict[str, object]:
        return {
            "turn_id": self.turn_id,
            "scene": self.scene,
            "user_input_preview": self.user_input_preview,
            "cleaned_input_preview": self.cleaned_input_preview,
            "history_message_count": self.history_message_count,
            "model_name": self.model_name,
            "request_latency_ms": self.request_latency_ms,
            "response_preview": self.response_preview,
            "postprocessed_response_preview": self.postprocessed_response_preview,
        }
