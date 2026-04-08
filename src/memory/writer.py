from __future__ import annotations

from datetime import datetime

from src.memory.models import (
    CandidateWriteResult,
    MemoryCandidate,
    MemoryItem,
    MemoryTurnInput,
    MemoryWriteResult,
)
from src.memory.rules import (
    extract_candidates,
    merge_candidate_with_existing,
    should_merge_episodic_candidate,
)
from src.memory.store import SQLiteMemoryStore
from src.utils.text_utils import safe_preview


class MemoryWriter:
    def __init__(
        self,
        store: SQLiteMemoryStore,
        episodic_ttl_days: int,
        merge_time_window_hours: int,
    ) -> None:
        self.store = store
        self.episodic_ttl_days = max(3, min(14, episodic_ttl_days))
        self.merge_time_window_hours = max(6, merge_time_window_hours)

    def extract_turn_candidates(
        self,
        turn: MemoryTurnInput,
        *,
        now: datetime,
    ) -> list[MemoryCandidate]:
        return extract_candidates(
            user_input=turn.user_input,
            source_turn=turn.turn_id,
            episodic_ttl_days=self.episodic_ttl_days,
            now=now,
            scene=turn.scene,
        )

    def write_turn(
        self,
        turn: MemoryTurnInput,
        *,
        now: datetime,
    ) -> MemoryWriteResult:
        extracted_candidates = self.extract_turn_candidates(turn, now=now)
        if not extracted_candidates:
            return MemoryWriteResult(skipped_reason="no_high_signal_candidate")

        stored_items: list[MemoryItem] = []
        decisions: list[CandidateWriteResult] = []
        now_iso = now.isoformat(timespec="seconds")
        active_episodic = self.store.list_items(memory_type="episodic", status="active")

        for candidate in extracted_candidates:
            resolved_candidate = self._resolve_candidate_merge(
                candidate,
                active_episodic,
                now=now,
            )
            item, action = self.store.upsert_candidate(resolved_candidate, now_iso)
            stored_items.append(item)
            decisions.append(
                CandidateWriteResult(
                    candidate_preview=safe_preview(candidate.content, 60),
                    accepted=True,
                    action=action,
                    reason=self._build_reason(candidate, resolved_candidate, action),
                    memory_id=item.id,
                    candidate_reason=candidate.candidate_reason,
                )
            )
            active_episodic = [
                memory for memory in active_episodic if memory.id != item.id
            ] + ([item] if item.memory_type == "episodic" else [])

        return MemoryWriteResult(
            stored_items=tuple(stored_items),
            decisions=tuple(decisions),
        )

    def _resolve_candidate_merge(
        self,
        candidate: MemoryCandidate,
        active_episodic: list[MemoryItem],
        *,
        now: datetime,
    ) -> MemoryCandidate:
        if candidate.memory_type != "episodic":
            return candidate

        for existing in active_episodic:
            if should_merge_episodic_candidate(
                candidate,
                existing,
                now=now,
                merge_window_hours=self.merge_time_window_hours,
            ):
                return merge_candidate_with_existing(candidate, existing)
        return candidate

    def _build_reason(
        self,
        original: MemoryCandidate,
        resolved: MemoryCandidate,
        action: str,
    ) -> str:
        if action == "merged" and resolved.match_id:
            return f"{original.candidate_reason or 'merged'} -> {resolved.match_id}"
        return original.candidate_reason or action
