from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


LengthBand = str


@dataclass(frozen=True)
class EvalCase:
    id: str
    input: str
    expected_scene: str
    expected_length_band: LengthBand
    forbidden_patterns: tuple[str, ...] = ()
    preferred_patterns: tuple[str, ...] = ()
    notes: str | None = None
    tags: tuple[str, ...] = ()
    should_follow_up: bool | None = None
    should_avoid_advice: bool | None = None
    should_feel_warm: bool | None = None
    enabled: bool = True
    history_messages: tuple[dict[str, str], ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "EvalCase":
        return cls(
            id=str(data["id"]).strip(),
            input=str(data["input"]).strip(),
            expected_scene=str(data["expected_scene"]).strip(),
            expected_length_band=str(data["expected_length_band"]).strip(),
            forbidden_patterns=_as_string_tuple(data.get("forbidden_patterns")),
            preferred_patterns=_as_string_tuple(data.get("preferred_patterns")),
            notes=_optional_string(data.get("notes")),
            tags=_as_string_tuple(data.get("tags")),
            should_follow_up=_optional_bool(data.get("should_follow_up")),
            should_avoid_advice=_optional_bool(data.get("should_avoid_advice")),
            should_feel_warm=_optional_bool(data.get("should_feel_warm")),
            enabled=_optional_bool(data.get("enabled"), default=True) is not False,
            history_messages=_as_history_tuple(data.get("history_messages")),
        )


@dataclass(frozen=True)
class ResponseCheck:
    response_length: int
    actual_length_band: LengthBand
    length_band_match: bool
    forbidden_hits: tuple[str, ...]
    preferred_hits: tuple[str, ...]
    ai_disclaimer_detected: bool
    pseudo_memory_detected: bool
    template_style_detected: bool
    advicey_detected: bool
    follow_up_detected: bool
    warmth_signal_detected: bool
    empty_response: bool
    manual_review_needed: bool
    failure_reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    input: str
    turn_id: str | None
    expected_scene: str
    actual_scene: str | None
    scene_match: bool
    response_text: str
    response_preview: str
    response_length: int
    expected_length_band: LengthBand
    actual_length_band: LengthBand | None
    length_band_match: bool
    forbidden_hits: tuple[str, ...]
    preferred_hits: tuple[str, ...]
    latency_ms: int | None
    success: bool
    error_type: str | None
    error_message: str | None
    provider_name: str | None
    model_name: str | None
    tags: tuple[str, ...] = ()
    notes: str | None = None
    manual_review_needed: bool = False
    failure_reasons: tuple[str, ...] = ()
    postprocess_applied_rules: tuple[str, ...] = ()
    used_fallback: bool = False
    prompt_block_count: int = 0
    prompt_message_count: int = 0
    memory_write_candidate_present: bool = False
    proactive_followup_candidate_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalRunSummary:
    total_cases: int
    success_count: int
    failure_count: int
    scene_match_rate: float
    length_band_match_rate: float
    forbidden_hit_case_count: int
    empty_response_count: int
    avg_latency_ms: float
    p95_latency_ms: int
    by_tag: dict[str, dict[str, Any]]
    output_dir: str
    mode: str
    suite_name: str
    trace_log_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("Expected a list of strings.")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _optional_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError("Expected a boolean value.")
    return value


def _as_history_tuple(value: Any) -> tuple[dict[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("Expected history_messages to be a list.")

    cleaned: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each history message must be a mapping.")
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            cleaned.append({"role": role, "content": content})
    return tuple(cleaned)
