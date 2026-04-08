from __future__ import annotations

from datetime import datetime

from src.memory.models import MemoryReadResult
from src.memory.rules import (
    format_memory_for_prompt,
    score_memory_for_query,
    sort_memory_selections,
)
from src.memory.store import SQLiteMemoryStore


class MemoryReader:
    def __init__(self, store: SQLiteMemoryStore, max_injection_items: int) -> None:
        self.store = store
        self.max_injection_items = max(2, min(4, max_injection_items))

    def retrieve(
        self,
        *,
        user_input: str,
        scene: str,
        now: datetime,
    ) -> MemoryReadResult:
        memories = self.store.list_active_items()
        if not memories:
            return MemoryReadResult(skipped_reason="empty_store")

        selections = []
        for memory in memories:
            selection = score_memory_for_query(
                memory,
                user_input=user_input,
                scene=scene,
                now=now,
            )
            if selection is not None:
                selections.append(selection)

        if not selections:
            return MemoryReadResult(skipped_reason="no_relevant_memory")

        ranked = []
        seen_topics: set[str] = set()
        for selection in sort_memory_selections(selections):
            topic_key = selection.item.topic_key or selection.item.id
            if topic_key in seen_topics:
                continue
            seen_topics.add(topic_key)
            ranked.append(selection)
            if len(ranked) >= self.max_injection_items:
                break
        return MemoryReadResult(
            selected_items=tuple(selection.item for selection in ranked),
            prompt_items=tuple(
                format_memory_for_prompt(selection.item) for selection in ranked
            ),
            debug_selections=tuple(ranked),
        )
