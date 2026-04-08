from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config.loader import AppConfig
from src.memory.models import (
    MemoryCandidate,
    MemoryItem,
    MemoryReadResult,
    MemoryStoreStats,
    MemoryTurnInput,
    MemoryWriteResult,
    now_timestamp,
)
from src.memory.reader import MemoryReader
from src.memory.store import SQLiteMemoryStore
from src.memory.writer import MemoryWriter
from src.observability.trace import TurnTrace
from src.utils.logger import log_event
from src.utils.text_utils import safe_preview

_UNSET = object()


@dataclass(frozen=True)
class MemoryManagerConfig:
    enabled: bool
    write_enabled: bool
    store_type: str
    store_path: Path
    max_injection_items: int
    episodic_ttl_days: int
    merge_time_window_hours: int


class MemoryManager:
    def __init__(self, config: MemoryManagerConfig) -> None:
        self.config = config
        self.store = (
            self._build_store(config.store_type, config.store_path)
            if config.enabled or config.write_enabled
            else None
        )
        self.reader = (
            MemoryReader(self.store, config.max_injection_items)
            if self.store is not None
            else None
        )
        self.writer = (
            MemoryWriter(
                self.store,
                config.episodic_ttl_days,
                config.merge_time_window_hours,
            )
            if self.store is not None
            else None
        )

    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> "MemoryManager":
        project_root = app_config.config_dir.parent.parent
        runtime = app_config.runtime
        return cls(
            MemoryManagerConfig(
                enabled=runtime.memory_enabled,
                write_enabled=runtime.memory_write_enabled,
                store_type=runtime.memory_store_type,
                store_path=_resolve_store_path(project_root, runtime.memory_store_path),
                max_injection_items=runtime.max_memory_injection_items,
                episodic_ttl_days=runtime.episodic_memory_ttl_days,
                merge_time_window_hours=runtime.merge_time_window_hours,
            )
        )

    def preview_write_candidates(
        self,
        turn: MemoryTurnInput,
        *,
        now: datetime | None = None,
    ) -> tuple[MemoryCandidate, ...]:
        if self.store is None or self.writer is None:
            return ()
        current_time = now or now_timestamp()
        return tuple(self.writer.extract_turn_candidates(turn, now=current_time))

    def retrieve(
        self,
        *,
        user_input: str,
        scene: str,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryReadResult:
        if not self.config.enabled or self.store is None or self.reader is None:
            result = MemoryReadResult(skipped_reason="memory_disabled")
            log_event(
                "memory_retrieval_skipped",
                level="DEBUG",
                turn_trace=turn_trace,
                skipped_reason=result.skipped_reason,
            )
            return result

        current_time = now or now_timestamp()
        expired_count = self.store.expire_episodic_entries(
            current_time.isoformat(timespec="seconds")
        )
        result = self.reader.retrieve(user_input=user_input, scene=scene, now=current_time)
        log_event(
            "memory_retrieval_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            expired_count=expired_count,
            memory_selected_ids=result.selected_ids,
            memory_selected_count=len(result.selected_ids),
            memory_selection_reasons=[
                {
                    "id": selection.item.id,
                    "score": round(selection.score, 2),
                    "reason": selection.reason,
                }
                for selection in result.debug_selections
            ],
            skipped_reason=result.skipped_reason,
        )
        return result

    def write_turn(
        self,
        turn: MemoryTurnInput,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryWriteResult:
        if not self.config.write_enabled or self.store is None or self.writer is None:
            result = MemoryWriteResult(skipped_reason="memory_write_disabled")
            log_event(
                "memory_write_skipped",
                level="DEBUG",
                turn_trace=turn_trace,
                skipped_reason=result.skipped_reason,
            )
            return result

        current_time = now or now_timestamp()
        self.store.expire_episodic_entries(current_time.isoformat(timespec="seconds"))
        extracted_candidates = self.writer.extract_turn_candidates(turn, now=current_time)
        log_event(
            "memory_candidates_extracted",
            level="DEBUG",
            turn_trace=turn_trace,
            candidate_count=len(extracted_candidates),
            candidate_previews=[
                {
                    "reason": candidate.candidate_reason,
                    "type": candidate.memory_type,
                    "preview": safe_preview(candidate.content, 60),
                    "topic_key": candidate.topic_key,
                    "followup_enabled": candidate.followup_enabled,
                }
                for candidate in extracted_candidates
            ],
        )
        result = self.writer.write_turn(turn, now=current_time)
        log_event(
            "memory_write_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            memory_written_ids=result.stored_ids,
            memory_written_count=len(result.stored_ids),
            candidate_decisions=[
                {
                    "preview": decision.candidate_preview,
                    "accepted": decision.accepted,
                    "action": decision.action,
                    "reason": decision.reason,
                    "memory_id": decision.memory_id,
                    "candidate_reason": decision.candidate_reason,
                }
                for decision in result.decisions
            ],
            skipped_reason=result.skipped_reason,
        )
        if not extracted_candidates:
            log_event(
                "memory_candidate_rejected",
                level="DEBUG",
                turn_trace=turn_trace,
                reason="no_high_signal_candidate",
            )
        return result

    def list_memories(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = "active",
        limit: int | None = None,
    ) -> tuple[MemoryItem, ...]:
        if self.store is None:
            return ()
        return tuple(
            self.store.list_items(
                memory_type=memory_type,
                status=status,
                limit=limit,
            )
        )

    def get_memory(self, memory_id: str) -> MemoryItem | None:
        if self.store is None:
            return None
        return self.store.get_item(memory_id)

    def delete_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
    ) -> bool:
        if self.store is None:
            return False
        deleted = self.store.delete_item(memory_id)
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action="delete",
            memory_id=memory_id,
            success=deleted,
        )
        return deleted

    def archive_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        return self._status_action(
            action="archive",
            memory_id=memory_id,
            turn_trace=turn_trace,
            now=now,
        )

    def expire_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        return self._status_action(
            action="expire",
            memory_id=memory_id,
            turn_trace=turn_trace,
            now=now,
        )

    def activate_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        return self._status_action(
            action="activate",
            memory_id=memory_id,
            turn_trace=turn_trace,
            now=now,
        )

    def set_pinned(
        self,
        memory_id: str,
        pinned: bool,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        item = self.store.set_pinned(
            memory_id,
            pinned=pinned,
            now_iso=current_time.isoformat(timespec="seconds"),
        )
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action="pin" if pinned else "unpin",
            memory_id=memory_id,
            success=item is not None,
        )
        return item

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | object = _UNSET,
        confidence: float | object = _UNSET,
        expires_at: str | None | object = _UNSET,
        summary: str | None | object = _UNSET,
        status: str | object = _UNSET,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        update_kwargs: dict[str, object] = {
            "now_iso": current_time.isoformat(timespec="seconds")
        }
        if content is not _UNSET:
            update_kwargs["content"] = content
        if confidence is not _UNSET:
            update_kwargs["confidence"] = confidence
        if expires_at is not _UNSET:
            update_kwargs["expires_at"] = expires_at
        if summary is not _UNSET:
            update_kwargs["summary"] = summary
        if status is not _UNSET:
            update_kwargs["status"] = status
        item = self.store.update_item(
            memory_id,
            **update_kwargs,
        )
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action="update",
            memory_id=memory_id,
            success=item is not None,
        )
        return item

    def mark_followup_sent(
        self,
        memory_id: str,
        *,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        return self.store.mark_followup_sent(
            memory_id,
            current_time.isoformat(timespec="seconds"),
        )

    def get_store_stats(self) -> MemoryStoreStats:
        if self.store is None:
            return MemoryStoreStats()
        return self.store.get_stats()

    def _build_store(self, store_type: str, store_path: Path) -> SQLiteMemoryStore:
        if store_type.lower() != "sqlite":
            raise ValueError(f"Unsupported memory store type: {store_type}")
        return SQLiteMemoryStore(store_path)

    def _status_action(
        self,
        *,
        action: str,
        memory_id: str,
        turn_trace: TurnTrace | None,
        now: datetime | None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        now_iso = current_time.isoformat(timespec="seconds")
        if action == "archive":
            item = self.store.archive_item(memory_id, now_iso)
        elif action == "expire":
            item = self.store.expire_item(memory_id, now_iso)
        else:
            item = self.store.activate_item(memory_id, now_iso)
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action=action,
            memory_id=memory_id,
            success=item is not None,
        )
        return item


def _resolve_store_path(project_root: Path, store_path: str) -> Path:
    candidate = Path(store_path)
    return candidate if candidate.is_absolute() else project_root / candidate
