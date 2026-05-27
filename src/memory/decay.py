from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.memory.models import (
    DEFAULT_SESSION_GRACE_HOURS_PROMOTED,
    DEFAULT_SESSION_GRACE_HOURS_SKIPPED,
    SessionMemoryItem,
)
from src.memory.store import SQLiteMemoryStore
from src.memory.summarizer import should_run_final_consolidation_attempt


@dataclass(frozen=True)
class SessionDecaySweep:
    final_attempt_items: tuple[SessionMemoryItem, ...] = ()
    archived_ids: tuple[str, ...] = ()
    expired_count: int = 0


class SessionDecayService:
    def __init__(
        self,
        store: SQLiteMemoryStore,
        *,
        promoted_grace_hours: int = DEFAULT_SESSION_GRACE_HOURS_PROMOTED,
        skipped_grace_hours: int = DEFAULT_SESSION_GRACE_HOURS_SKIPPED,
    ) -> None:
        self.store = store
        self.promoted_grace_hours = max(12, promoted_grace_hours)
        self.skipped_grace_hours = max(4, skipped_grace_hours)

    def sweep(
        self,
        *,
        now: datetime,
        session_id: str | None = None,
        final_attempt_limit: int = 1,
    ) -> SessionDecaySweep:
        now_iso = now.isoformat(timespec="seconds")
        expired_count = self.store.expire_session_entries(now_iso)
        final_attempt_items = self._select_final_attempt_items(
            now=now,
            session_id=session_id,
            limit=final_attempt_limit,
        )
        archived_ids = self._archive_ready_items(
            now=now,
            session_id=session_id,
        )
        return SessionDecaySweep(
            final_attempt_items=tuple(final_attempt_items),
            archived_ids=tuple(archived_ids),
            expired_count=expired_count,
        )

    def _select_final_attempt_items(
        self,
        *,
        now: datetime,
        session_id: str | None,
        limit: int,
    ) -> list[SessionMemoryItem]:
        if limit <= 0:
            return []
        candidates = self.store.list_session_items(
            session_id=session_id,
            status="active",
            consolidation_states=("pending",),
        )
        selected = [
            item
            for item in candidates
            if should_run_final_consolidation_attempt(item, now=now)
        ]
        selected.sort(
            key=lambda item: (
                item.expires_at or "",
                item.updated_at,
            )
        )
        return selected[:limit]

    def _archive_ready_items(
        self,
        *,
        now: datetime,
        session_id: str | None,
    ) -> list[str]:
        archived: list[str] = []
        candidates = self.store.list_session_items(
            session_id=session_id,
            status=None,
        )
        now_iso = now.isoformat(timespec="seconds")
        for item in candidates:
            if item.consolidation_state == "archived" or item.status == "archived":
                continue
            if self._should_archive(item, now=now):
                updated = self.store.update_session_item(
                    item.id,
                    now_iso=now_iso,
                    status="archived",
                    consolidation_state="archived",
                    archived_at=now_iso,
                )
                if updated is not None:
                    archived.append(updated.id)
        return archived

    def _should_archive(
        self,
        item: SessionMemoryItem,
        *,
        now: datetime,
    ) -> bool:
        touched_at = datetime.fromisoformat(item.last_touched_at or item.updated_at)
        if item.status == "expired":
            return touched_at <= now - timedelta(hours=1)
        if item.consolidation_state == "promoted":
            return touched_at <= now - timedelta(hours=self.promoted_grace_hours)
        if item.consolidation_state == "skipped":
            return touched_at <= now - timedelta(hours=self.skipped_grace_hours)
        if item.consolidation_state == "summarized" and item.expires_at is not None:
            return datetime.fromisoformat(item.expires_at) <= now
        return False
