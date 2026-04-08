from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemorySeed:
    id: str
    memory_type: str
    content: str
    source_turn: str = "seed-turn"
    source_message_excerpt: str = ""
    confidence: float = 0.9
    ttl_days: int | None = None
    status: str = "active"
    dedupe_key: str | None = None
    topic_key: str | None = None
    tags: tuple[str, ...] = ()
    summary: str | None = None
    pinned: bool = False
    merge_count: int = 1
    followup_enabled: bool = False
    created_hours_ago: int = 48
    updated_hours_ago: int = 6
    expires_in_hours: int | None = None
    followup_due_in_hours: int | None = None
    last_followup_hours_ago: int | None = None


@dataclass(frozen=True)
class RegressionCase:
    case_id: str
    input_history: tuple[dict[str, str], ...] = ()
    user_input: str = ""
    existing_memories: tuple[MemorySeed, ...] = ()
    expected_write_candidates: tuple[str, ...] = ()
    expected_written_memory_types: tuple[str, ...] = ()
    expected_injected_memory_ids: tuple[str, ...] = ()
    expected_guard_flags: tuple[str, ...] = ()
    expected_guard_action: str | None = None
    expected_guard_initial_action: str | None = None
    expected_retry_attempted: bool | None = None
    expected_final_contains: tuple[str, ...] = ()
    expected_final_not_contains: tuple[str, ...] = ()
    expected_followup_candidate_ids: tuple[str, ...] = ()
    gateway_responses: tuple[str, ...] = ()
    expected_behavior_notes: str = ""
    scene: str | None = None
    extra: dict[str, object] = field(default_factory=dict)
