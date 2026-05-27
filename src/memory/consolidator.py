from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from src.memory.models import MemoryItem, SessionMemoryItem, parse_timestamp
from src.utils.text_utils import normalize_whitespace, safe_preview


@dataclass(frozen=True)
class SessionConsolidationSnapshot:
    summary_text: str | None = None
    open_loop_memory_ids: tuple[str, ...] = ()


def build_session_consolidation_snapshot(
    *,
    session_items: Sequence[SessionMemoryItem],
    promoted_memories: Sequence[MemoryItem],
    now: datetime,
) -> SessionConsolidationSnapshot:
    summary_text = _build_last_session_summary(
        session_items=session_items,
        promoted_memories=promoted_memories,
        now=now,
    )
    open_loop_memory_ids = tuple(
        memory.id
        for memory in promoted_memories
        if memory.memory_class == "task" and memory.status == "active" and not memory.is_expired(now)
    )
    return SessionConsolidationSnapshot(
        summary_text=summary_text,
        open_loop_memory_ids=open_loop_memory_ids,
    )


def _build_last_session_summary(
    *,
    session_items: Sequence[SessionMemoryItem],
    promoted_memories: Sequence[MemoryItem],
    now: datetime,
) -> str | None:
    ranked_open_loops = [
        item
        for item in session_items
        if item.status == "active" and item.carryover_kind == "task"
    ]
    ranked_open_loops.sort(
        key=lambda item: (
            -item.importance,
            -item.confidence,
            -parse_timestamp(item.updated_at).timestamp(),
        )
    )
    if ranked_open_loops:
        text = _clip_summary(ranked_open_loops[0].summary_text or ranked_open_loops[0].display_text())
        return f"Last session ended with an open loop: {text}"

    ranked_promoted = [
        memory
        for memory in promoted_memories
        if memory.status == "active" and not memory.is_expired(now)
    ]
    ranked_promoted.sort(
        key=lambda item: (
            0 if item.memory_class == "task" else 1,
            0 if item.memory_class == "episodic" else 1,
            -item.confidence,
            -parse_timestamp(item.updated_at).timestamp(),
        )
    )
    if ranked_promoted:
        text = _clip_summary(ranked_promoted[0].summary or ranked_promoted[0].display_text())
        prefix = "Last session focused on"
        if ranked_promoted[0].memory_class == "task":
            prefix = "Last session committed to"
        return f"{prefix}: {text}"

    ranked_session = [
        item
        for item in session_items
        if item.status == "active" and item.origin_kind == "session_only"
    ]
    ranked_session.sort(
        key=lambda item: (
            0 if item.carryover_kind == "session" else 1,
            0 if item.carryover_kind == "episodic" else 1,
            -item.importance,
            -item.confidence,
            -parse_timestamp(item.updated_at).timestamp(),
        )
    )
    if ranked_session:
        return f"Last session focused on: {_clip_summary(ranked_session[0].summary_text or ranked_session[0].display_text())}"
    return None


def _clip_summary(text: str) -> str:
    return safe_preview(normalize_whitespace(text), 140).rstrip("。.!? ")
