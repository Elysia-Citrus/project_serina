from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


MemoryType = Literal["profile", "episodic"]
MemoryStatus = Literal["active", "expired", "archived"]


@dataclass(frozen=True)
class MemoryItem:
    id: str
    memory_type: MemoryType
    content: str
    source_turn: str
    source_message_excerpt: str
    created_at: str
    updated_at: str
    confidence: float
    ttl_days: int | None
    expires_at: str | None
    decay_policy: str
    status: MemoryStatus = "active"
    dedupe_key: str | None = None
    topic_key: str | None = None
    tags: tuple[str, ...] = ()
    summary: str | None = None
    pinned: bool = False
    merge_count: int = 1
    followup_enabled: bool = False
    followup_due_at: str | None = None
    last_followup_at: str | None = None
    metadata_json: str | None = None

    def is_expired(self, now: datetime) -> bool:
        if self.status == "expired":
            return True
        if self.status != "active" or not self.expires_at:
            return False
        return parse_timestamp(self.expires_at) <= now

    def display_text(self) -> str:
        return (self.summary or self.content).strip()


@dataclass(frozen=True)
class MemoryCandidate:
    memory_type: MemoryType
    content: str
    source_turn: str
    source_message_excerpt: str
    confidence: float
    ttl_days: int | None
    decay_policy: str
    dedupe_key: str | None = None
    candidate_reason: str = ""
    topic_key: str | None = None
    tags: tuple[str, ...] = ()
    summary: str | None = None
    pinned: bool = False
    merge_count: int = 1
    followup_enabled: bool = False
    followup_due_at: str | None = None
    metadata_json: str | None = None
    match_id: str | None = None


@dataclass(frozen=True)
class CandidateWriteResult:
    candidate_preview: str
    accepted: bool
    action: str
    reason: str
    memory_id: str | None = None
    candidate_reason: str | None = None


@dataclass(frozen=True)
class MemorySelection:
    item: MemoryItem
    score: float
    reason: str


@dataclass(frozen=True)
class MemoryReadResult:
    selected_items: tuple[MemoryItem, ...] = ()
    prompt_items: tuple[str, ...] = ()
    debug_selections: tuple[MemorySelection, ...] = ()
    skipped_reason: str | None = None

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.selected_items)

    @property
    def hit(self) -> bool:
        return bool(self.selected_items)


@dataclass(frozen=True)
class MemoryWriteResult:
    stored_items: tuple[MemoryItem, ...] = ()
    decisions: tuple[CandidateWriteResult, ...] = ()
    skipped_reason: str | None = None

    @property
    def stored_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.stored_items)

    @property
    def wrote_any(self) -> bool:
        return bool(self.stored_items)


@dataclass(frozen=True)
class MemoryTurnInput:
    user_input: str
    assistant_reply: str
    scene: str
    turn_id: str


@dataclass(frozen=True)
class MemoryStoreStats:
    active_profile_count: int = 0
    active_episodic_count: int = 0
    expired_count: int = 0
    archived_count: int = 0


def now_timestamp() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def format_timestamp(value: datetime) -> str:
    return value.astimezone().replace(microsecond=0).isoformat()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
