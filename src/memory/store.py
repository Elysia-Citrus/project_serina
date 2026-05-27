from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4
import json
import sqlite3

from src.memory.models import (
    DEFAULT_NAMESPACE,
    DEFAULT_OWNER_KIND,
    DEFAULT_REVIEW_STATE,
    ConversationTurn,
    MemoryCandidate,
    MemoryItem,
    MemoryStoreStats,
    SessionContinuityRecord,
    SessionMemoryCandidate,
    SessionMemoryItem,
    derive_cross_session_visible,
    derive_memory_class,
    derive_preference_fields,
    derive_representation,
    format_timestamp,
    parse_timestamp,
    validate_namespace_owner,
)


SCHEMA_VERSION = 6
_UNSET = object()

META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    canonical_text TEXT,
    memory_class TEXT,
    representation TEXT,
    namespace TEXT,
    owner_kind TEXT,
    structured_payload_json TEXT,
    evidence_json TEXT,
    source_kind TEXT,
    source_ref TEXT,
    source_turn TEXT NOT NULL,
    source_message_excerpt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_confirmed_at TEXT,
    last_used_at TEXT,
    confidence REAL NOT NULL,
    strength REAL,
    useful_score REAL NOT NULL DEFAULT 0,
    cross_session_visible INTEGER NOT NULL DEFAULT 0,
    ttl_days INTEGER,
    expires_at TEXT,
    decay_policy TEXT NOT NULL,
    status TEXT NOT NULL,
    review_state TEXT,
    stale_reason TEXT,
    supersedes_id TEXT,
    contradicts_id TEXT,
    dedupe_key TEXT,
    topic_key TEXT,
    tags_json TEXT,
    summary TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    merge_count INTEGER NOT NULL DEFAULT 1,
    followup_enabled INTEGER NOT NULL DEFAULT 0,
    followup_due_at TEXT,
    last_followup_at TEXT,
    preference_target TEXT,
    preference_value TEXT,
    preference_strength REAL,
    preference_context TEXT,
    preference_polarity TEXT,
    metadata_json TEXT
);
"""

SESSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS session_memory_entries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    source_role TEXT,
    category TEXT,
    content TEXT,
    content_summary TEXT,
    importance REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    representation TEXT NOT NULL,
    namespace TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    canonical_text TEXT NOT NULL,
    source_turn TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_touched_at TEXT,
    expires_at TEXT,
    status TEXT NOT NULL,
    consolidation_state TEXT NOT NULL DEFAULT 'pending',
    origin_kind TEXT NOT NULL DEFAULT 'session_only',
    topic_key TEXT,
    carryover_kind TEXT,
    summary_text TEXT,
    structured_payload_json TEXT,
    metadata_json TEXT,
    source_turn_range TEXT,
    last_confirmed_at TEXT,
    last_consolidated_at TEXT,
    archived_at TEXT,
    promotion_fingerprint TEXT,
    produced_memory_refs_json TEXT
);
"""

SESSION_CONTINUITY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS session_continuity_entries (
    session_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    first_user_message TEXT,
    last_user_message TEXT,
    last_assistant_message TEXT,
    last_scene TEXT,
    summary_text TEXT,
    metadata_json TEXT
);
"""

CONVERSATION_TURNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    source_channel TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    raw_asr_text TEXT,
    scene TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    llm_provider TEXT,
    llm_model TEXT,
    asr_provider TEXT,
    tts_provider TEXT,
    latency_json TEXT,
    metadata_json TEXT
);
"""

INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_memory_status_type
    ON memory_entries(status, memory_type, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_class_review
    ON memory_entries(status, memory_class, review_state, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_namespace_owner
    ON memory_entries(namespace, owner_kind, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_expires_at
    ON memory_entries(expires_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_dedupe_key
    ON memory_entries(dedupe_key)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_topic_key
    ON memory_entries(topic_key, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_followup_due_at
    ON memory_entries(followup_enabled, followup_due_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memory_cross_session_visible
    ON memory_entries(cross_session_visible, status, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_memory_session_status
    ON session_memory_entries(session_id, status, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_memory_topic
    ON session_memory_entries(session_id, topic_key, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_memory_pending
    ON session_memory_entries(status, consolidation_state, expires_at, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_continuity_last_active
    ON session_continuity_entries(last_active_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_continuity_started
    ON session_continuity_entries(started_at ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_turns_session
    ON conversation_turns(session_id, turn_index)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_turns_created
    ON conversation_turns(completed_at DESC)
    """,
)

MISSING_COLUMNS = {
    "canonical_text": "TEXT",
    "memory_class": "TEXT",
    "representation": "TEXT",
    "namespace": "TEXT",
    "owner_kind": "TEXT",
    "structured_payload_json": "TEXT",
    "evidence_json": "TEXT",
    "source_kind": "TEXT",
    "source_ref": "TEXT",
    "last_confirmed_at": "TEXT",
    "last_used_at": "TEXT",
    "strength": "REAL",
    "useful_score": "REAL NOT NULL DEFAULT 0",
    "cross_session_visible": "INTEGER NOT NULL DEFAULT 0",
    "review_state": "TEXT",
    "stale_reason": "TEXT",
    "supersedes_id": "TEXT",
    "contradicts_id": "TEXT",
    "topic_key": "TEXT",
    "tags_json": "TEXT",
    "summary": "TEXT",
    "pinned": "INTEGER NOT NULL DEFAULT 0",
    "merge_count": "INTEGER NOT NULL DEFAULT 1",
    "followup_enabled": "INTEGER NOT NULL DEFAULT 0",
    "followup_due_at": "TEXT",
    "last_followup_at": "TEXT",
    "preference_target": "TEXT",
    "preference_value": "TEXT",
    "preference_strength": "REAL",
    "preference_context": "TEXT",
    "preference_polarity": "TEXT",
    "metadata_json": "TEXT",
}

SESSION_MISSING_COLUMNS = {
    "turn_id": "TEXT",
    "source_role": "TEXT",
    "category": "TEXT",
    "content": "TEXT",
    "content_summary": "TEXT",
    "importance": "REAL NOT NULL DEFAULT 0",
    "confidence": "REAL NOT NULL DEFAULT 0",
    "last_touched_at": "TEXT",
    "consolidation_state": "TEXT NOT NULL DEFAULT 'pending'",
    "origin_kind": "TEXT NOT NULL DEFAULT 'session_only'",
    "summary_text": "TEXT",
    "source_turn_range": "TEXT",
    "last_consolidated_at": "TEXT",
    "archived_at": "TEXT",
    "promotion_fingerprint": "TEXT",
    "produced_memory_refs_json": "TEXT",
}

MEMORY_ENTRY_COLUMNS = (
    "id",
    "memory_type",
    "content",
    "canonical_text",
    "memory_class",
    "representation",
    "namespace",
    "owner_kind",
    "structured_payload_json",
    "evidence_json",
    "source_kind",
    "source_ref",
    "source_turn",
    "source_message_excerpt",
    "created_at",
    "updated_at",
    "last_confirmed_at",
    "last_used_at",
    "confidence",
    "strength",
    "useful_score",
    "cross_session_visible",
    "ttl_days",
    "expires_at",
    "decay_policy",
    "status",
    "review_state",
    "stale_reason",
    "supersedes_id",
    "contradicts_id",
    "dedupe_key",
    "topic_key",
    "tags_json",
    "summary",
    "pinned",
    "merge_count",
    "followup_enabled",
    "followup_due_at",
    "last_followup_at",
    "preference_target",
    "preference_value",
    "preference_strength",
    "preference_context",
    "preference_polarity",
    "metadata_json",
)

SESSION_ENTRY_COLUMNS = (
    "id",
    "session_id",
    "turn_id",
    "source_role",
    "category",
    "content",
    "content_summary",
    "importance",
    "confidence",
    "representation",
    "namespace",
    "owner_kind",
    "canonical_text",
    "source_turn",
    "created_at",
    "updated_at",
    "last_touched_at",
    "expires_at",
    "status",
    "consolidation_state",
    "origin_kind",
    "topic_key",
    "carryover_kind",
    "summary_text",
    "structured_payload_json",
    "metadata_json",
    "source_turn_range",
    "last_confirmed_at",
    "last_consolidated_at",
    "archived_at",
    "promotion_fingerprint",
    "produced_memory_refs_json",
)

SESSION_CONTINUITY_COLUMNS = (
    "session_id",
    "started_at",
    "last_active_at",
    "turn_count",
    "first_user_message",
    "last_user_message",
    "last_assistant_message",
    "last_scene",
    "summary_text",
    "metadata_json",
)


class SQLiteMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def expire_episodic_entries(self, now_iso: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_entries
                SET status = 'expired', updated_at = ?
                WHERE status = 'active'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                  AND memory_class IN ('episodic', 'task')
                """,
                (now_iso, now_iso),
            )
            return cursor.rowcount

    def expire_session_entries(self, now_iso: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE session_memory_entries
                SET status = 'expired',
                    consolidation_state = CASE
                        WHEN consolidation_state = 'archived' THEN consolidation_state
                        ELSE consolidation_state
                    END,
                    updated_at = ?
                WHERE status = 'active'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                """,
                (now_iso, now_iso),
            )
            return cursor.rowcount

    def list_active_items(self) -> list[MemoryItem]:
        return self.list_items(
            status="active",
            review_states=("active", "pending_review", "stale"),
        )

    def list_items(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = "active",
        limit: int | None = None,
        memory_class: str | None = None,
        representation: str | None = None,
        namespace: str | None = None,
        owner_kind: str | None = None,
        review_states: Sequence[str] | None = None,
    ) -> list[MemoryItem]:
        query = ["SELECT * FROM memory_entries WHERE 1 = 1"]
        params: list[object] = []
        if memory_type is not None:
            query.append("AND memory_type = ?")
            params.append(memory_type)
        if status is not None:
            query.append("AND status = ?")
            params.append(status)
        if memory_class is not None:
            query.append("AND memory_class = ?")
            params.append(memory_class)
        if representation is not None:
            query.append("AND representation = ?")
            params.append(representation)
        if namespace is not None:
            query.append("AND namespace = ?")
            params.append(namespace)
        if owner_kind is not None:
            query.append("AND owner_kind = ?")
            params.append(owner_kind)
        if review_states:
            placeholders = ", ".join("?" for _ in review_states)
            query.append(f"AND review_state IN ({placeholders})")
            params.extend(review_states)
        query.append(
            """
            ORDER BY pinned DESC,
                     CASE review_state
                         WHEN 'active' THEN 0
                         WHEN 'pending_review' THEN 1
                         WHEN 'stale' THEN 2
                         ELSE 3
                     END,
                     updated_at DESC
            """
        )
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(" ".join(query), params).fetchall()
        return [self._row_to_item(row) for row in rows]

    def list_session_items(
        self,
        *,
        session_id: str | None = None,
        status: str | None = "active",
        consolidation_states: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[SessionMemoryItem]:
        query = ["SELECT * FROM session_memory_entries WHERE 1 = 1"]
        params: list[object] = []
        if session_id is not None:
            query.append("AND session_id = ?")
            params.append(session_id)
        if status is not None:
            query.append("AND status = ?")
            params.append(status)
        if consolidation_states:
            placeholders = ", ".join("?" for _ in consolidation_states)
            query.append(f"AND consolidation_state IN ({placeholders})")
            params.extend(consolidation_states)
        query.append("ORDER BY last_touched_at DESC, updated_at DESC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(" ".join(query), params).fetchall()
        return [self._row_to_session_item(row) for row in rows]

    def register_session(
        self,
        *,
        session_id: str,
        started_at: str,
        metadata_json: str | None = None,
    ) -> SessionContinuityRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO session_continuity_entries (
                    session_id,
                    started_at,
                    last_active_at,
                    turn_count,
                    metadata_json
                ) VALUES (?, ?, ?, 0, ?)
                """,
                (session_id, started_at, started_at, metadata_json),
            )
            row = conn.execute(
                "SELECT * FROM session_continuity_entries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Registered session continuity row was not found.")
        return self._row_to_session_continuity(row)

    def save_conversation_turn(self, turn: ConversationTurn) -> str:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO conversation_turns (
                    id,
                    session_id,
                    turn_index,
                    source_channel,
                    user_text,
                    assistant_text,
                    raw_asr_text,
                    scene,
                    started_at,
                    completed_at,
                    llm_provider,
                    llm_model,
                    asr_provider,
                    tts_provider,
                    latency_json,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.id,
                    turn.session_id,
                    turn.turn_index,
                    turn.source_channel,
                    turn.user_text,
                    turn.assistant_text,
                    turn.raw_asr_text,
                    turn.scene,
                    turn.started_at,
                    turn.completed_at,
                    turn.llm_provider,
                    turn.llm_model,
                    turn.asr_provider,
                    turn.tts_provider,
                    turn.latency_json,
                    turn.metadata_json,
                ),
            )
        return turn.id

    def list_conversation_turns(
        self,
        *,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[ConversationTurn]:
        query = ["SELECT * FROM conversation_turns WHERE 1 = 1"]
        params: list[object] = []
        if session_id is not None:
            query.append("AND session_id = ?")
            params.append(session_id)
        query.append("ORDER BY completed_at DESC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(" ".join(query), params).fetchall()
        return [self._row_to_conversation_turn(row) for row in rows]

    def update_session_continuity(
        self,
        *,
        session_id: str,
        started_at: str,
        last_active_at: str,
        user_message: str,
        assistant_message: str,
        scene: str | None = None,
        summary_text: str | None = None,
        metadata_json: str | None = None,
    ) -> SessionContinuityRecord:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM session_continuity_entries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO session_continuity_entries (
                        session_id,
                        started_at,
                        last_active_at,
                        turn_count,
                        first_user_message,
                        last_user_message,
                        last_assistant_message,
                        last_scene,
                        summary_text,
                        metadata_json
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        started_at,
                        last_active_at,
                        user_message,
                        user_message,
                        assistant_message,
                        scene,
                        summary_text,
                        metadata_json,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE session_continuity_entries
                    SET started_at = COALESCE(NULLIF(started_at, ''), ?),
                        last_active_at = ?,
                        turn_count = ?,
                        first_user_message = COALESCE(NULLIF(first_user_message, ''), ?),
                        last_user_message = ?,
                        last_assistant_message = ?,
                        last_scene = ?,
                        summary_text = ?,
                        metadata_json = ?
                    WHERE session_id = ?
                    """,
                    (
                        started_at,
                        last_active_at,
                        max(1, int(existing["turn_count"] or 0) + 1),
                        user_message,
                        user_message,
                        assistant_message,
                        scene,
                        summary_text if summary_text else existing["summary_text"],
                        metadata_json if metadata_json else existing["metadata_json"],
                        session_id,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM session_continuity_entries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Updated session continuity row was not found.")
        return self._row_to_session_continuity(row)

    def update_session_continuity_snapshot(
        self,
        *,
        session_id: str,
        last_active_at: str,
        summary_text: str | None = None,
        metadata_json: str | None = None,
        minimum_turn_count: int | None = None,
    ) -> SessionContinuityRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE session_continuity_entries
                SET last_active_at = ?,
                    turn_count = CASE
                        WHEN ? IS NULL THEN turn_count
                        ELSE MAX(turn_count, ?)
                    END,
                    summary_text = COALESCE(?, summary_text),
                    metadata_json = COALESCE(?, metadata_json)
                WHERE session_id = ?
                """,
                (
                    last_active_at,
                    minimum_turn_count,
                    max(0, minimum_turn_count or 0),
                    summary_text,
                    metadata_json,
                    session_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM session_continuity_entries WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_session_continuity(row) if row is not None else None

    def list_session_continuity(
        self,
        *,
        exclude_session_id: str | None = None,
        min_turn_count: int = 1,
        limit: int | None = None,
    ) -> list[SessionContinuityRecord]:
        query = ["SELECT * FROM session_continuity_entries WHERE turn_count >= ?"]
        params: list[object] = [max(0, min_turn_count)]
        if exclude_session_id is not None:
            query.append("AND session_id != ?")
            params.append(exclude_session_id)
        query.append("ORDER BY last_active_at DESC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(" ".join(query), params).fetchall()
        return [self._row_to_session_continuity(row) for row in rows]

    def get_first_session_continuity(
        self,
        *,
        exclude_session_id: str | None = None,
        min_turn_count: int = 1,
    ) -> SessionContinuityRecord | None:
        query = ["SELECT * FROM session_continuity_entries WHERE turn_count >= ?"]
        params: list[object] = [max(0, min_turn_count)]
        if exclude_session_id is not None:
            query.append("AND session_id != ?")
            params.append(exclude_session_id)
        query.append("ORDER BY started_at ASC LIMIT 1")
        with self._connect() as conn:
            row = conn.execute(" ".join(query), params).fetchone()
        return self._row_to_session_continuity(row) if row is not None else None

    def get_session_item(self, session_item_id: str) -> SessionMemoryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM session_memory_entries WHERE id = ?",
                (session_item_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session_item(row)

    def update_session_item(
        self,
        session_item_id: str,
        *,
        now_iso: str,
        canonical_text: str | object = _UNSET,
        summary_text: str | None | object = _UNSET,
        expires_at: str | None | object = _UNSET,
        status: str | object = _UNSET,
        consolidation_state: str | object = _UNSET,
        topic_key: str | None | object = _UNSET,
        carryover_kind: str | None | object = _UNSET,
        structured_payload_json: str | None | object = _UNSET,
        metadata_json: str | None | object = _UNSET,
        last_confirmed_at: str | None | object = _UNSET,
        last_touched_at: str | None | object = _UNSET,
        last_consolidated_at: str | None | object = _UNSET,
        archived_at: str | None | object = _UNSET,
        promotion_fingerprint: str | None | object = _UNSET,
        produced_memory_refs: Sequence[str] | object = _UNSET,
    ) -> SessionMemoryItem | None:
        updates: list[str] = ["updated_at = ?"]
        params: list[object] = [now_iso]
        if canonical_text is not _UNSET:
            updates.append("canonical_text = ?")
            params.append(canonical_text)
        if summary_text is not _UNSET:
            updates.append("summary_text = ?")
            params.append(summary_text)
        if expires_at is not _UNSET:
            updates.append("expires_at = ?")
            params.append(expires_at)
        if status is not _UNSET:
            updates.append("status = ?")
            params.append(status)
        if consolidation_state is not _UNSET:
            updates.append("consolidation_state = ?")
            params.append(consolidation_state)
        if topic_key is not _UNSET:
            updates.append("topic_key = ?")
            params.append(topic_key)
        if carryover_kind is not _UNSET:
            updates.append("carryover_kind = ?")
            params.append(carryover_kind)
        if structured_payload_json is not _UNSET:
            updates.append("structured_payload_json = ?")
            params.append(structured_payload_json)
        if metadata_json is not _UNSET:
            updates.append("metadata_json = ?")
            params.append(metadata_json)
        if last_confirmed_at is not _UNSET:
            updates.append("last_confirmed_at = ?")
            params.append(last_confirmed_at)
        if last_touched_at is not _UNSET:
            updates.append("last_touched_at = ?")
            params.append(last_touched_at)
        if last_consolidated_at is not _UNSET:
            updates.append("last_consolidated_at = ?")
            params.append(last_consolidated_at)
        if archived_at is not _UNSET:
            updates.append("archived_at = ?")
            params.append(archived_at)
        if promotion_fingerprint is not _UNSET:
            updates.append("promotion_fingerprint = ?")
            params.append(promotion_fingerprint)
        if produced_memory_refs is not _UNSET:
            updates.append("produced_memory_refs_json = ?")
            params.append(_serialize_string_values(produced_memory_refs))
        params.append(session_item_id)

        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE session_memory_entries SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM session_memory_entries WHERE id = ?",
                (session_item_id,),
            ).fetchone()
        return self._row_to_session_item(row) if row is not None else None

    def touch_session_items(
        self,
        session_item_ids: Sequence[str],
        *,
        now_iso: str,
    ) -> int:
        cleaned_ids = [session_item_id for session_item_id in session_item_ids if session_item_id]
        if not cleaned_ids:
            return 0
        placeholders = ", ".join("?" for _ in cleaned_ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE session_memory_entries
                SET last_touched_at = ?
                WHERE id IN ({placeholders})
                """,
                [now_iso, *cleaned_ids],
            )
            return cursor.rowcount

    def touch_items(
        self,
        memory_ids: Sequence[str],
        *,
        now_iso: str,
    ) -> int:
        cleaned_ids = [memory_id for memory_id in memory_ids if memory_id]
        if not cleaned_ids:
            return 0
        placeholders = ", ".join("?" for _ in cleaned_ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE memory_entries
                SET last_used_at = ?
                WHERE id IN ({placeholders})
                """,
                [now_iso, *cleaned_ids],
            )
            return cursor.rowcount

    def get_item(self, memory_id: str) -> MemoryItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def delete_item(self, memory_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM memory_entries WHERE id = ?",
                (memory_id,),
            )
            return cursor.rowcount > 0

    def archive_item(self, memory_id: str, now_iso: str) -> MemoryItem | None:
        return self._set_status(memory_id, status="archived", now_iso=now_iso)

    def expire_item(self, memory_id: str, now_iso: str) -> MemoryItem | None:
        return self._set_status(memory_id, status="expired", now_iso=now_iso)

    def activate_item(self, memory_id: str, now_iso: str) -> MemoryItem | None:
        return self._set_status(memory_id, status="active", now_iso=now_iso)

    def set_pinned(self, memory_id: str, pinned: bool, now_iso: str) -> MemoryItem | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_entries
                SET pinned = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(pinned), now_iso, memory_id),
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def update_item(
        self,
        memory_id: str,
        *,
        now_iso: str,
        content: str | object = _UNSET,
        canonical_text: str | None | object = _UNSET,
        confidence: float | object = _UNSET,
        expires_at: str | None | object = _UNSET,
        summary: str | None | object = _UNSET,
        status: str | object = _UNSET,
        review_state: str | object = _UNSET,
        stale_reason: str | None | object = _UNSET,
        last_confirmed_at: str | None | object = _UNSET,
        last_used_at: str | None | object = _UNSET,
        cross_session_visible: bool | object = _UNSET,
        supersedes_id: str | None | object = _UNSET,
        contradicts_id: str | None | object = _UNSET,
    ) -> MemoryItem | None:
        updates: list[str] = ["updated_at = ?"]
        params: list[object] = [now_iso]
        if content is not _UNSET:
            updates.append("content = ?")
            params.append(content)
        if canonical_text is not _UNSET:
            updates.append("canonical_text = ?")
            params.append(canonical_text)
        if confidence is not _UNSET:
            updates.append("confidence = ?")
            params.append(confidence)
        if expires_at is not _UNSET:
            updates.append("expires_at = ?")
            params.append(expires_at)
        if summary is not _UNSET:
            updates.append("summary = ?")
            params.append(summary)
        if status is not _UNSET:
            updates.append("status = ?")
            params.append(status)
        if review_state is not _UNSET:
            updates.append("review_state = ?")
            params.append(review_state)
        if stale_reason is not _UNSET:
            updates.append("stale_reason = ?")
            params.append(stale_reason)
        if last_confirmed_at is not _UNSET:
            updates.append("last_confirmed_at = ?")
            params.append(last_confirmed_at)
        if last_used_at is not _UNSET:
            updates.append("last_used_at = ?")
            params.append(last_used_at)
        if cross_session_visible is not _UNSET:
            updates.append("cross_session_visible = ?")
            params.append(int(bool(cross_session_visible)))
        if supersedes_id is not _UNSET:
            updates.append("supersedes_id = ?")
            params.append(supersedes_id)
        if contradicts_id is not _UNSET:
            updates.append("contradicts_id = ?")
            params.append(contradicts_id)
        params.append(memory_id)

        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE memory_entries SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def mark_followup_sent(self, memory_id: str, now_iso: str) -> MemoryItem | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_entries
                SET last_followup_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now_iso, now_iso, memory_id),
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def upsert_session_candidate(
        self,
        candidate: SessionMemoryCandidate,
        now_iso: str,
    ) -> SessionMemoryItem:
        namespace, owner_kind = validate_namespace_owner(
            candidate.namespace,
            candidate.owner_kind,
        )
        expires_at = format_timestamp(
            parse_timestamp(now_iso) + timedelta(days=max(1, candidate.ttl_days))
        )
        with self._connect() as conn:
            existing = self._find_existing_session(conn, candidate)
            if existing is not None:
                memory_id = str(existing["id"])
                changed = _session_candidate_changed(existing, candidate)
                existing_state = str(existing["consolidation_state"] or "pending")
                existing_fingerprint = (
                    str(existing["promotion_fingerprint"])
                    if existing["promotion_fingerprint"]
                    else None
                )
                existing_refs = _deserialize_strings(existing["produced_memory_refs_json"])
                consolidation_state = (
                    candidate.consolidation_state if changed else existing_state
                )
                last_consolidated_at = None
                promotion_fingerprint = None
                produced_memory_refs = None
                if not changed:
                    last_consolidated_at = (
                        str(existing["last_consolidated_at"])
                        if existing["last_consolidated_at"]
                        else None
                    )
                    promotion_fingerprint = existing_fingerprint
                    produced_memory_refs = _serialize_string_values(existing_refs)
                conn.execute(
                    """
                    UPDATE session_memory_entries
                    SET turn_id = ?,
                        source_role = ?,
                        category = ?,
                        content = ?,
                        content_summary = ?,
                        importance = ?,
                        confidence = ?,
                        representation = ?,
                        namespace = ?,
                        owner_kind = ?,
                        canonical_text = ?,
                        source_turn = ?,
                        updated_at = ?,
                        last_touched_at = ?,
                        expires_at = ?,
                        status = 'active',
                        consolidation_state = ?,
                        origin_kind = ?,
                        topic_key = ?,
                        carryover_kind = ?,
                        summary_text = ?,
                        structured_payload_json = ?,
                        metadata_json = ?,
                        source_turn_range = ?,
                        last_confirmed_at = ?,
                        last_consolidated_at = ?,
                        archived_at = NULL,
                        promotion_fingerprint = ?,
                        produced_memory_refs_json = ?
                    WHERE id = ?
                    """,
                    (
                        candidate.turn_id,
                        candidate.source_role,
                        candidate.category,
                        candidate.content,
                        candidate.content_summary,
                        candidate.importance,
                        candidate.confidence,
                        candidate.representation,
                        namespace,
                        owner_kind,
                        candidate.canonical_text,
                        candidate.source_turn,
                        now_iso,
                        now_iso,
                        expires_at,
                        consolidation_state,
                        candidate.origin_kind,
                        candidate.topic_key,
                        candidate.carryover_kind,
                        candidate.summary_text,
                        candidate.structured_payload_json,
                        candidate.metadata_json,
                        candidate.source_turn_range,
                        candidate.last_confirmed_at or now_iso,
                        last_consolidated_at,
                        promotion_fingerprint,
                        produced_memory_refs,
                        memory_id,
                    ),
                )
            else:
                memory_id = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO session_memory_entries (
                        id,
                        session_id,
                        turn_id,
                        source_role,
                        category,
                        content,
                        content_summary,
                        importance,
                        confidence,
                        representation,
                        namespace,
                        owner_kind,
                        canonical_text,
                        source_turn,
                        created_at,
                        updated_at,
                        last_touched_at,
                        expires_at,
                        status,
                        consolidation_state,
                        origin_kind,
                        topic_key,
                        carryover_kind,
                        summary_text,
                        structured_payload_json,
                        metadata_json,
                        source_turn_range,
                        last_confirmed_at,
                        last_consolidated_at,
                        archived_at,
                        promotion_fingerprint,
                        produced_memory_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        memory_id,
                        candidate.session_id,
                        candidate.turn_id,
                        candidate.source_role,
                        candidate.category,
                        candidate.content,
                        candidate.content_summary,
                        candidate.importance,
                        candidate.confidence,
                        candidate.representation,
                        namespace,
                        owner_kind,
                        candidate.canonical_text,
                        candidate.source_turn,
                        now_iso,
                        now_iso,
                        now_iso,
                        expires_at,
                        candidate.status,
                        candidate.consolidation_state,
                        candidate.origin_kind,
                        candidate.topic_key,
                        candidate.carryover_kind,
                        candidate.summary_text,
                        candidate.structured_payload_json,
                        candidate.metadata_json,
                        candidate.source_turn_range,
                        candidate.last_confirmed_at or now_iso,
                        None,
                        candidate.promotion_fingerprint,
                        _serialize_string_values(candidate.produced_memory_refs),
                    ),
                )
            row = conn.execute(
                "SELECT * FROM session_memory_entries WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Upserted session memory row was not found.")
        return self._row_to_session_item(row)

    def upsert_candidate(
        self,
        candidate: MemoryCandidate,
        now_iso: str,
    ) -> tuple[MemoryItem, str]:
        with self._connect() as conn:
            existing = self._find_existing(conn, candidate)
            expires_at = _expires_at_from_candidate(candidate, now_iso)
            if existing is not None and _should_insert_revision(existing, candidate):
                item = self._insert_revision(conn, existing, candidate, now_iso, expires_at)
                return item, "revised"

            if existing is not None:
                memory_id = str(existing["id"])
                created_at = str(existing["created_at"])
                merged_tags = _merge_tags(
                    _deserialize_tags(existing["tags_json"]),
                    candidate.tags,
                )
                merged_summary = (
                    candidate.summary
                    if candidate.summary is not None
                    else str(existing["summary"]) if existing["summary"] else None
                )
                merged_topic_key = candidate.topic_key or (
                    str(existing["topic_key"]) if existing["topic_key"] else None
                )
                pinned = int(candidate.pinned or bool(existing["pinned"]))
                merge_count = max(candidate.merge_count, int(existing["merge_count"] or 1))
                followup_enabled = int(
                    candidate.followup_enabled or bool(existing["followup_enabled"])
                )
                followup_due_at = candidate.followup_due_at or (
                    str(existing["followup_due_at"]) if existing["followup_due_at"] else None
                )
                metadata_json = candidate.metadata_json or (
                    str(existing["metadata_json"]) if existing["metadata_json"] else None
                )
                last_used_at = (
                    candidate.last_used_at
                    or (str(existing["last_used_at"]) if existing["last_used_at"] else None)
                )
                cross_session_visible = int(
                    candidate.cross_session_visible or bool(existing["cross_session_visible"])
                )
                resolved_expires_at = expires_at or (
                    str(existing["expires_at"]) if existing["expires_at"] else None
                )
                resolved_ttl_days = candidate.ttl_days
                if resolved_ttl_days is None and existing["ttl_days"] is not None:
                    resolved_ttl_days = int(existing["ttl_days"])

                conn.execute(
                    """
                    UPDATE memory_entries
                    SET content = ?,
                        canonical_text = ?,
                        memory_class = ?,
                        representation = ?,
                        namespace = ?,
                        owner_kind = ?,
                        structured_payload_json = ?,
                        evidence_json = ?,
                        source_kind = ?,
                        source_ref = ?,
                        source_turn = ?,
                        source_message_excerpt = ?,
                        updated_at = ?,
                        last_confirmed_at = ?,
                        last_used_at = ?,
                        confidence = ?,
                        strength = ?,
                        useful_score = ?,
                        cross_session_visible = ?,
                        ttl_days = ?,
                        expires_at = ?,
                        decay_policy = ?,
                        status = 'active',
                        review_state = ?,
                        stale_reason = ?,
                        supersedes_id = ?,
                        contradicts_id = ?,
                        dedupe_key = ?,
                        topic_key = ?,
                        tags_json = ?,
                        summary = ?,
                        pinned = ?,
                        merge_count = ?,
                        followup_enabled = ?,
                        followup_due_at = ?,
                        preference_target = ?,
                        preference_value = ?,
                        preference_strength = ?,
                        preference_context = ?,
                        preference_polarity = ?,
                        metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        candidate.content,
                        candidate.canonical_text or candidate.content,
                        candidate.memory_class,
                        candidate.representation,
                        candidate.namespace,
                        candidate.owner_kind,
                        candidate.structured_payload_json,
                        candidate.evidence_json,
                        candidate.source_kind,
                        candidate.source_ref,
                        candidate.source_turn,
                        candidate.source_message_excerpt,
                        now_iso,
                        candidate.last_confirmed_at or now_iso,
                        last_used_at,
                        candidate.confidence,
                        candidate.strength if candidate.strength is not None else candidate.confidence,
                        candidate.useful_score,
                        cross_session_visible,
                        resolved_ttl_days,
                        resolved_expires_at,
                        candidate.decay_policy,
                        candidate.review_state,
                        candidate.stale_reason,
                        candidate.supersedes_id,
                        candidate.contradicts_id,
                        candidate.dedupe_key or (
                            str(existing["dedupe_key"]) if existing["dedupe_key"] else None
                        ),
                        merged_topic_key,
                        _serialize_tags(merged_tags),
                        merged_summary,
                        pinned,
                        merge_count,
                        followup_enabled,
                        followup_due_at,
                        candidate.preference_target,
                        candidate.preference_value,
                        candidate.preference_strength,
                        candidate.preference_context,
                        candidate.preference_polarity,
                        metadata_json,
                        memory_id,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM memory_entries WHERE id = ?",
                    (memory_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Updated memory row was not found.")
                item = self._row_to_item(row)
                if item.created_at != created_at:
                    item = _replace_created_at(item, created_at)
                action = "merged" if candidate.match_id or candidate.merge_count > 1 else "updated"
                return item, action

            row = self._insert_memory_row(conn, candidate, now_iso, expires_at)
            if row is None:
                raise RuntimeError("Inserted memory row was not found.")
            return self._row_to_item(row), "inserted"

    def seed_items(self, items: Iterable[MemoryItem]) -> None:
        with self._connect() as conn:
            conn.executemany(
                f"""
                INSERT OR REPLACE INTO memory_entries (
                    {", ".join(MEMORY_ENTRY_COLUMNS)}
                ) VALUES ({", ".join("?" for _ in MEMORY_ENTRY_COLUMNS)})
                """,
                [_memory_item_to_record(item) for item in items],
            )

    def seed_session_items(self, items: Iterable[SessionMemoryItem]) -> None:
        with self._connect() as conn:
            conn.executemany(
                f"""
                INSERT OR REPLACE INTO session_memory_entries (
                    {", ".join(SESSION_ENTRY_COLUMNS)}
                ) VALUES ({", ".join("?" for _ in SESSION_ENTRY_COLUMNS)})
                """,
                [_session_item_to_record(item) for item in items],
            )

    def seed_session_continuity(self, items: Iterable[SessionContinuityRecord]) -> None:
        with self._connect() as conn:
            conn.executemany(
                f"""
                INSERT OR REPLACE INTO session_continuity_entries (
                    {", ".join(SESSION_CONTINUITY_COLUMNS)}
                ) VALUES ({", ".join("?" for _ in SESSION_CONTINUITY_COLUMNS)})
                """,
                [_session_continuity_to_record(item) for item in items],
            )

    def get_stats(self) -> MemoryStoreStats:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, memory_class, representation, review_state, COUNT(*) AS count
                FROM memory_entries
                GROUP BY status, memory_class, representation, review_state
                """
            ).fetchall()
            session_row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM session_memory_entries
                WHERE status = 'active'
                """
            ).fetchone()

        stats = {
            "active_profile_count": 0,
            "active_episodic_count": 0,
            "active_task_count": 0,
            "active_semantic_count": 0,
            "active_preference_count": 0,
            "expired_count": 0,
            "archived_count": 0,
            "stale_count": 0,
        }
        for row in rows:
            status = str(row["status"])
            memory_class = str(row["memory_class"] or "")
            representation = str(row["representation"] or "")
            review_state = str(row["review_state"] or "")
            count = int(row["count"])

            if status == "expired":
                stats["expired_count"] += count
                continue
            if status == "archived":
                stats["archived_count"] += count
                continue
            if review_state == "stale":
                stats["stale_count"] += count
            if review_state in {"rejected", "archived"}:
                continue
            if memory_class == "profile":
                stats["active_profile_count"] += count
            elif memory_class == "task":
                stats["active_task_count"] += count
            elif memory_class == "semantic":
                stats["active_semantic_count"] += count
            elif memory_class == "episodic":
                stats["active_episodic_count"] += count
            if representation == "preference":
                stats["active_preference_count"] += count

        return MemoryStoreStats(
            active_profile_count=stats["active_profile_count"],
            active_episodic_count=stats["active_episodic_count"],
            active_task_count=stats["active_task_count"],
            active_semantic_count=stats["active_semantic_count"],
            active_preference_count=stats["active_preference_count"],
            expired_count=stats["expired_count"],
            archived_count=stats["archived_count"],
            stale_count=stats["stale_count"],
            session_active_count=int(session_row["count"]) if session_row is not None else 0,
        )

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(META_TABLE_SQL)
            conn.executescript(TABLE_SQL)
            conn.executescript(SESSION_TABLE_SQL)
            conn.executescript(SESSION_CONTINUITY_TABLE_SQL)
            conn.executescript(CONVERSATION_TURNS_TABLE_SQL)
            self._ensure_columns(conn)
            self._ensure_session_columns(conn)
            self._ensure_indexes(conn)
            self._backfill_entries(conn)
            self._backfill_session_entries(conn)
            self._set_schema_version(conn, SCHEMA_VERSION)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(memory_entries)").fetchall()
        }
        for name, definition in MISSING_COLUMNS.items():
            if name in existing_columns:
                continue
            conn.execute(f"ALTER TABLE memory_entries ADD COLUMN {name} {definition}")

    def _ensure_session_columns(self, conn: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(session_memory_entries)").fetchall()
        }
        for name, definition in SESSION_MISSING_COLUMNS.items():
            if name in existing_columns:
                continue
            conn.execute(f"ALTER TABLE session_memory_entries ADD COLUMN {name} {definition}")

    def _ensure_indexes(self, conn: sqlite3.Connection) -> None:
        for statement in INDEX_STATEMENTS:
            conn.execute(statement)

    def _backfill_entries(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE memory_entries
            SET canonical_text = COALESCE(NULLIF(canonical_text, ''), content),
                namespace = COALESCE(NULLIF(namespace, ''), ?),
                owner_kind = COALESCE(NULLIF(owner_kind, ''), ?),
                source_kind = COALESCE(NULLIF(source_kind, ''), 'conversation_turn'),
                source_ref = COALESCE(NULLIF(source_ref, ''), source_turn),
                review_state = COALESCE(
                    NULLIF(review_state, ''),
                    CASE
                        WHEN status = 'archived' THEN 'archived'
                        ELSE ?
                    END
                ),
                last_confirmed_at = COALESCE(NULLIF(last_confirmed_at, ''), updated_at),
                last_used_at = NULLIF(last_used_at, ''),
                strength = COALESCE(strength, confidence)
            """,
            (DEFAULT_NAMESPACE, DEFAULT_OWNER_KIND, DEFAULT_REVIEW_STATE),
        )

        rows = conn.execute("SELECT * FROM memory_entries").fetchall()
        for row in rows:
            tags = _deserialize_tags(row["tags_json"])
            try:
                namespace, owner_kind = validate_namespace_owner(
                    str(row["namespace"] or DEFAULT_NAMESPACE),
                    str(row["owner_kind"] or DEFAULT_OWNER_KIND),
                )
            except ValueError:
                namespace, owner_kind = (DEFAULT_NAMESPACE, DEFAULT_OWNER_KIND)

            memory_class = str(row["memory_class"] or "").strip() or derive_memory_class(
                memory_type=str(row["memory_type"]),
                tags=tags,
                dedupe_key=str(row["dedupe_key"]) if row["dedupe_key"] else None,
                followup_enabled=bool(row["followup_enabled"]),
                topic_key=str(row["topic_key"]) if row["topic_key"] else None,
            )
            representation = str(row["representation"] or "").strip() or derive_representation(
                memory_type=str(row["memory_type"]),
                memory_class=memory_class,
                tags=tags,
                dedupe_key=str(row["dedupe_key"]) if row["dedupe_key"] else None,
                summary=str(row["summary"]) if row["summary"] else None,
                merge_count=max(1, int(row["merge_count"] or 1)),
                preference_target=str(row["preference_target"])
                if row["preference_target"]
                else None,
                preference_value=str(row["preference_value"])
                if row["preference_value"]
                else None,
            )
            canonical_text = str(row["canonical_text"] or row["content"])
            (
                preference_target,
                preference_value,
                preference_context,
                preference_polarity,
            ) = derive_preference_fields(
                canonical_text=canonical_text,
                tags=tags,
                preference_target=str(row["preference_target"])
                if row["preference_target"]
                else None,
                preference_value=str(row["preference_value"])
                if row["preference_value"]
                else None,
                preference_context=str(row["preference_context"])
                if row["preference_context"]
                else None,
                preference_polarity=str(row["preference_polarity"])
                if row["preference_polarity"]
                else None,
            )
            cross_session_visible = int(
                bool(row["cross_session_visible"])
                or derive_cross_session_visible(
                    memory_class=memory_class,
                    representation=representation,
                    tags=tags,
                    followup_enabled=bool(row["followup_enabled"]),
                    source_kind=str(row["source_kind"] or "conversation_turn"),
                )
            )
            conn.execute(
                """
                UPDATE memory_entries
                SET memory_class = ?,
                    representation = ?,
                    namespace = ?,
                    owner_kind = ?,
                    cross_session_visible = ?,
                    preference_target = ?,
                    preference_value = ?,
                    preference_strength = COALESCE(preference_strength, CASE WHEN ? = 'preference' THEN confidence END),
                    preference_context = ?,
                    preference_polarity = ?
                WHERE id = ?
                """,
                (
                    memory_class,
                    representation,
                    namespace,
                    owner_kind,
                    cross_session_visible,
                    preference_target,
                    preference_value,
                    representation,
                    preference_context,
                    preference_polarity,
                    str(row["id"]),
                ),
            )

    def _backfill_session_entries(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE session_memory_entries
            SET namespace = COALESCE(NULLIF(namespace, ''), ?),
                owner_kind = COALESCE(NULLIF(owner_kind, ''), ?),
                last_touched_at = COALESCE(NULLIF(last_touched_at, ''), updated_at),
                consolidation_state = COALESCE(
                    NULLIF(consolidation_state, ''),
                    CASE
                        WHEN status = 'archived' THEN 'archived'
                        ELSE 'pending'
                    END
                ),
                origin_kind = COALESCE(NULLIF(origin_kind, ''), 'session_only'),
                last_confirmed_at = COALESCE(NULLIF(last_confirmed_at, ''), updated_at)
            """,
            (DEFAULT_NAMESPACE, DEFAULT_OWNER_KIND),
        )

        rows = conn.execute("SELECT * FROM session_memory_entries").fetchall()
        for row in rows:
            try:
                namespace, owner_kind = validate_namespace_owner(
                    str(row["namespace"] or DEFAULT_NAMESPACE),
                    str(row["owner_kind"] or DEFAULT_OWNER_KIND),
                )
            except ValueError:
                namespace, owner_kind = (DEFAULT_NAMESPACE, DEFAULT_OWNER_KIND)
            conn.execute(
                """
                UPDATE session_memory_entries
                SET namespace = ?,
                    owner_kind = ?,
                    produced_memory_refs_json = COALESCE(
                        NULLIF(produced_memory_refs_json, ''),
                        CASE
                            WHEN promotion_fingerprint IS NOT NULL AND promotion_fingerprint != ''
                                THEN '[]'
                            ELSE produced_memory_refs_json
                        END
                    )
                WHERE id = ?
                """,
                (
                    namespace,
                    owner_kind,
                    str(row["id"]),
                ),
            )

    def _set_schema_version(self, conn: sqlite3.Connection, version: int) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO memory_store_meta (key, value)
            VALUES ('schema_version', ?)
            """,
            (str(version),),
        )

    def _find_existing(
        self,
        conn: sqlite3.Connection,
        candidate: MemoryCandidate,
    ) -> sqlite3.Row | None:
        if candidate.match_id:
            return conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (candidate.match_id,),
            ).fetchone()

        if candidate.dedupe_key:
            row = conn.execute(
                """
                SELECT *
                FROM memory_entries
                WHERE dedupe_key = ?
                  AND status != 'archived'
                  AND review_state != 'rejected'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (candidate.dedupe_key,),
            ).fetchone()
            if row is not None:
                return row

        return conn.execute(
            """
            SELECT *
            FROM memory_entries
            WHERE memory_type = ?
              AND canonical_text = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (candidate.memory_type, candidate.canonical_text or candidate.content),
        ).fetchone()

    def _find_existing_session(
        self,
        conn: sqlite3.Connection,
        candidate: SessionMemoryCandidate,
    ) -> sqlite3.Row | None:
        if candidate.topic_key:
            row = conn.execute(
                """
                SELECT *
                FROM session_memory_entries
                WHERE session_id = ?
                  AND origin_kind = ?
                  AND topic_key = ?
                  AND status != 'archived'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (candidate.session_id, candidate.origin_kind, candidate.topic_key),
            ).fetchone()
            if row is not None:
                return row
        return conn.execute(
            """
            SELECT *
            FROM session_memory_entries
            WHERE session_id = ?
              AND origin_kind = ?
              AND canonical_text = ?
              AND status != 'archived'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (candidate.session_id, candidate.origin_kind, candidate.canonical_text),
        ).fetchone()

    def _insert_revision(
        self,
        conn: sqlite3.Connection,
        existing: sqlite3.Row,
        candidate: MemoryCandidate,
        now_iso: str,
        expires_at: str | None,
    ) -> MemoryItem:
        old_id = str(existing["id"])
        row = self._insert_memory_row(
            conn,
            _candidate_with_revision_link(candidate, old_id),
            now_iso,
            expires_at,
        )
        if row is None:
            raise RuntimeError("Inserted revision row was not found.")
        new_id = str(row["id"])
        conn.execute(
            """
            UPDATE memory_entries
            SET review_state = 'stale',
                stale_reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (f"superseded_by:{new_id}", now_iso, old_id),
        )
        return self._row_to_item(row)

    def _insert_memory_row(
        self,
        conn: sqlite3.Connection,
        candidate: MemoryCandidate,
        now_iso: str,
        expires_at: str | None,
    ) -> sqlite3.Row | None:
        memory_id = uuid4().hex
        conn.execute(
            f"""
            INSERT INTO memory_entries (
                {", ".join(MEMORY_ENTRY_COLUMNS)}
            ) VALUES ({", ".join("?" for _ in MEMORY_ENTRY_COLUMNS)})
            """,
            _memory_candidate_to_record(candidate, memory_id, now_iso, expires_at),
        )
        return conn.execute(
            "SELECT * FROM memory_entries WHERE id = ?",
            (memory_id,),
        ).fetchone()

    def _set_status(self, memory_id: str, *, status: str, now_iso: str) -> MemoryItem | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE memory_entries
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now_iso, memory_id),
            )
            if cursor.rowcount <= 0:
                return None
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=str(row["id"]),
            memory_type=str(row["memory_type"]),
            content=str(row["content"]),
            source_turn=str(row["source_turn"]),
            source_message_excerpt=str(row["source_message_excerpt"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            confidence=float(row["confidence"]),
            ttl_days=int(row["ttl_days"]) if row["ttl_days"] is not None else None,
            expires_at=str(row["expires_at"]) if row["expires_at"] else None,
            decay_policy=str(row["decay_policy"]),
            status=str(row["status"]),
            dedupe_key=str(row["dedupe_key"]) if row["dedupe_key"] else None,
            topic_key=str(row["topic_key"]) if row["topic_key"] else None,
            tags=_deserialize_tags(row["tags_json"]),
            summary=str(row["summary"]) if row["summary"] else None,
            pinned=bool(row["pinned"]),
            merge_count=max(1, int(row["merge_count"] or 1)),
            followup_enabled=bool(row["followup_enabled"]),
            followup_due_at=str(row["followup_due_at"])
            if row["followup_due_at"]
            else None,
            last_followup_at=str(row["last_followup_at"])
            if row["last_followup_at"]
            else None,
            metadata_json=str(row["metadata_json"]) if row["metadata_json"] else None,
            memory_class=str(row["memory_class"]) if row["memory_class"] else None,
            representation=str(row["representation"]) if row["representation"] else None,
            namespace=str(row["namespace"]) if row["namespace"] else DEFAULT_NAMESPACE,
            owner_kind=str(row["owner_kind"]) if row["owner_kind"] else DEFAULT_OWNER_KIND,
            canonical_text=str(row["canonical_text"]) if row["canonical_text"] else None,
            structured_payload_json=str(row["structured_payload_json"])
            if row["structured_payload_json"]
            else None,
            evidence_json=str(row["evidence_json"]) if row["evidence_json"] else None,
            source_kind=str(row["source_kind"]) if row["source_kind"] else "conversation_turn",
            source_ref=str(row["source_ref"]) if row["source_ref"] else None,
            review_state=str(row["review_state"]) if row["review_state"] else DEFAULT_REVIEW_STATE,
            stale_reason=str(row["stale_reason"]) if row["stale_reason"] else None,
            last_confirmed_at=str(row["last_confirmed_at"])
            if row["last_confirmed_at"]
            else None,
            last_used_at=str(row["last_used_at"]) if row["last_used_at"] else None,
            supersedes_id=str(row["supersedes_id"]) if row["supersedes_id"] else None,
            contradicts_id=str(row["contradicts_id"]) if row["contradicts_id"] else None,
            strength=float(row["strength"]) if row["strength"] is not None else None,
            useful_score=float(row["useful_score"] or 0.0),
            cross_session_visible=bool(row["cross_session_visible"]),
            preference_target=str(row["preference_target"])
            if row["preference_target"]
            else None,
            preference_value=str(row["preference_value"])
            if row["preference_value"]
            else None,
            preference_strength=float(row["preference_strength"])
            if row["preference_strength"] is not None
            else None,
            preference_context=str(row["preference_context"])
            if row["preference_context"]
            else None,
            preference_polarity=str(row["preference_polarity"])
            if row["preference_polarity"]
            else None,
        )

    def _row_to_session_item(self, row: sqlite3.Row) -> SessionMemoryItem:
        return SessionMemoryItem(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"] or row["source_turn"]),
            source_role=str(row["source_role"] or "derived"),
            category=str(row["category"] or row["carryover_kind"] or "recent_event"),
            content=str(row["content"] or row["canonical_text"]),
            representation=str(row["representation"]),  # type: ignore[arg-type]
            namespace=str(row["namespace"]) if row["namespace"] else DEFAULT_NAMESPACE,  # type: ignore[arg-type]
            owner_kind=str(row["owner_kind"]) if row["owner_kind"] else DEFAULT_OWNER_KIND,  # type: ignore[arg-type]
            canonical_text=str(row["canonical_text"]),
            source_turn=str(row["source_turn"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_touched_at=str(row["last_touched_at"])
            if row["last_touched_at"]
            else None,
            expires_at=str(row["expires_at"]) if row["expires_at"] else None,
            importance=float(row["importance"] or 0.0),
            confidence=float(row["confidence"] or 0.0),
            status=str(row["status"]),  # type: ignore[arg-type]
            consolidation_state=str(row["consolidation_state"] or "pending"),  # type: ignore[arg-type]
            origin_kind=str(row["origin_kind"] or "session_only"),  # type: ignore[arg-type]
            topic_key=str(row["topic_key"]) if row["topic_key"] else None,
            carryover_kind=str(row["carryover_kind"]) if row["carryover_kind"] else None,
            content_summary=str(row["content_summary"])
            if row["content_summary"]
            else None,
            summary_text=str(row["summary_text"]) if row["summary_text"] else None,
            structured_payload_json=str(row["structured_payload_json"])
            if row["structured_payload_json"]
            else None,
            metadata_json=str(row["metadata_json"]) if row["metadata_json"] else None,
            source_turn_range=str(row["source_turn_range"])
            if row["source_turn_range"]
            else None,
            last_confirmed_at=str(row["last_confirmed_at"])
            if row["last_confirmed_at"]
            else None,
            last_consolidated_at=str(row["last_consolidated_at"])
            if row["last_consolidated_at"]
            else None,
            archived_at=str(row["archived_at"]) if row["archived_at"] else None,
            promotion_fingerprint=str(row["promotion_fingerprint"])
            if row["promotion_fingerprint"]
            else None,
            produced_memory_refs=_deserialize_strings(row["produced_memory_refs_json"]),
        )

    def _row_to_session_continuity(
        self,
        row: sqlite3.Row,
    ) -> SessionContinuityRecord:
        return SessionContinuityRecord(
            session_id=str(row["session_id"]),
            started_at=str(row["started_at"]),
            last_active_at=str(row["last_active_at"]),
            turn_count=max(0, int(row["turn_count"] or 0)),
            first_user_message=str(row["first_user_message"])
            if row["first_user_message"]
            else None,
            last_user_message=str(row["last_user_message"])
            if row["last_user_message"]
            else None,
            last_assistant_message=str(row["last_assistant_message"])
            if row["last_assistant_message"]
            else None,
            last_scene=str(row["last_scene"]) if row["last_scene"] else None,
            summary_text=str(row["summary_text"]) if row["summary_text"] else None,
            metadata_json=str(row["metadata_json"]) if row["metadata_json"] else None,
        )

    def _row_to_conversation_turn(self, row: sqlite3.Row) -> ConversationTurn:
        return ConversationTurn(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            turn_index=int(row["turn_index"]),
            source_channel=str(row["source_channel"]),
            user_text=str(row["user_text"]),
            assistant_text=str(row["assistant_text"]),
            raw_asr_text=str(row["raw_asr_text"]) if row["raw_asr_text"] else None,
            scene=str(row["scene"]) if row["scene"] else None,
            started_at=str(row["started_at"]),
            completed_at=str(row["completed_at"]),
            llm_provider=str(row["llm_provider"]) if row["llm_provider"] else None,
            llm_model=str(row["llm_model"]) if row["llm_model"] else None,
            asr_provider=str(row["asr_provider"]) if row["asr_provider"] else None,
            tts_provider=str(row["tts_provider"]) if row["tts_provider"] else None,
            latency_json=str(row["latency_json"]) if row["latency_json"] else None,
            metadata_json=str(row["metadata_json"]) if row["metadata_json"] else None,
        )


def _expires_at_from_candidate(candidate: MemoryCandidate, now_iso: str) -> str | None:
    if candidate.ttl_days is None:
        return None
    return format_timestamp(parse_timestamp(now_iso) + timedelta(days=candidate.ttl_days))


def _memory_candidate_to_record(
    candidate: MemoryCandidate,
    memory_id: str,
    now_iso: str,
    expires_at: str | None,
) -> tuple[object, ...]:
    return (
        memory_id,
        candidate.memory_type,
        candidate.content,
        candidate.canonical_text or candidate.content,
        candidate.memory_class,
        candidate.representation,
        candidate.namespace,
        candidate.owner_kind,
        candidate.structured_payload_json,
        candidate.evidence_json,
        candidate.source_kind,
        candidate.source_ref or candidate.source_turn,
        candidate.source_turn,
        candidate.source_message_excerpt,
        now_iso,
        now_iso,
        candidate.last_confirmed_at or now_iso,
        candidate.last_used_at,
        candidate.confidence,
        candidate.strength if candidate.strength is not None else candidate.confidence,
        candidate.useful_score,
        int(candidate.cross_session_visible),
        candidate.ttl_days,
        expires_at,
        candidate.decay_policy,
        "active",
        candidate.review_state,
        candidate.stale_reason,
        candidate.supersedes_id,
        candidate.contradicts_id,
        candidate.dedupe_key,
        candidate.topic_key,
        _serialize_tags(candidate.tags),
        candidate.summary,
        int(candidate.pinned),
        max(1, candidate.merge_count),
        int(candidate.followup_enabled),
        candidate.followup_due_at,
        None,
        candidate.preference_target,
        candidate.preference_value,
        candidate.preference_strength,
        candidate.preference_context,
        candidate.preference_polarity,
        candidate.metadata_json,
    )


def _memory_item_to_record(item: MemoryItem) -> tuple[object, ...]:
    return (
        item.id,
        item.memory_type,
        item.content,
        item.canonical_text or item.content,
        item.memory_class,
        item.representation,
        item.namespace,
        item.owner_kind,
        item.structured_payload_json,
        item.evidence_json,
        item.source_kind,
        item.source_ref or item.source_turn,
        item.source_turn,
        item.source_message_excerpt,
        item.created_at,
        item.updated_at,
        item.last_confirmed_at,
        item.last_used_at,
        item.confidence,
        item.strength if item.strength is not None else item.confidence,
        item.useful_score,
        int(item.cross_session_visible),
        item.ttl_days,
        item.expires_at,
        item.decay_policy,
        item.status,
        item.review_state,
        item.stale_reason,
        item.supersedes_id,
        item.contradicts_id,
        item.dedupe_key,
        item.topic_key,
        _serialize_tags(item.tags),
        item.summary,
        int(item.pinned),
        item.merge_count,
        int(item.followup_enabled),
        item.followup_due_at,
        item.last_followup_at,
        item.preference_target,
        item.preference_value,
        item.preference_strength,
        item.preference_context,
        item.preference_polarity,
        item.metadata_json,
    )


def _session_item_to_record(item: SessionMemoryItem) -> tuple[object, ...]:
    return (
        item.id,
        item.session_id,
        item.turn_id,
        item.source_role,
        item.category,
        item.content,
        item.content_summary,
        item.importance,
        item.confidence,
        item.representation,
        item.namespace,
        item.owner_kind,
        item.canonical_text,
        item.source_turn,
        item.created_at,
        item.updated_at,
        item.last_touched_at,
        item.expires_at,
        item.status,
        item.consolidation_state,
        item.origin_kind,
        item.topic_key,
        item.carryover_kind,
        item.summary_text,
        item.structured_payload_json,
        item.metadata_json,
        item.source_turn_range,
        item.last_confirmed_at,
        item.last_consolidated_at,
        item.archived_at,
        item.promotion_fingerprint,
        _serialize_string_values(item.produced_memory_refs),
    )


def _session_continuity_to_record(item: SessionContinuityRecord) -> tuple[object, ...]:
    return (
        item.session_id,
        item.started_at,
        item.last_active_at,
        max(0, item.turn_count),
        item.first_user_message,
        item.last_user_message,
        item.last_assistant_message,
        item.last_scene,
        item.summary_text,
        item.metadata_json,
    )


def _deserialize_tags(raw_value: object) -> tuple[str, ...]:
    if raw_value is None or raw_value == "":
        return ()
    try:
        payload = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(str(item).strip() for item in payload if str(item).strip())


def _serialize_tags(tags: Iterable[str]) -> str | None:
    cleaned = [str(tag).strip() for tag in tags if str(tag).strip()]
    if not cleaned:
        return None
    return json.dumps(sorted(set(cleaned)), ensure_ascii=False)


def _deserialize_strings(raw_value: object) -> tuple[str, ...]:
    if raw_value is None or raw_value == "":
        return ()
    try:
        payload = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(str(item).strip() for item in payload if str(item).strip())


def _serialize_string_values(values: object) -> str | None:
    if values is None:
        return None
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def _merge_tags(existing: Iterable[str], incoming: Iterable[str]) -> tuple[str, ...]:
    merged = [*existing, *incoming]
    return tuple(sorted({tag for tag in merged if tag}))


def _session_candidate_changed(
    existing: sqlite3.Row,
    candidate: SessionMemoryCandidate,
) -> bool:
    if str(existing["canonical_text"] or "") != candidate.canonical_text:
        return True
    if str(existing["source_turn"] or "") != candidate.source_turn:
        return True
    if str(existing["representation"] or "") != candidate.representation:
        return True
    if str(existing["topic_key"] or "") != str(candidate.topic_key or ""):
        return True
    if str(existing["carryover_kind"] or "") != str(candidate.carryover_kind or ""):
        return True
    if str(existing["origin_kind"] or "session_only") != candidate.origin_kind:
        return True
    if candidate.summary_text is not None and str(existing["summary_text"] or "") != str(
        candidate.summary_text or ""
    ):
        return True
    if candidate.structured_payload_json is not None and str(
        existing["structured_payload_json"] or ""
    ) != str(candidate.structured_payload_json or ""):
        return True
    if candidate.metadata_json is not None and str(existing["metadata_json"] or "") != str(
        candidate.metadata_json or ""
    ):
        return True
    return False


def _same_preference_payload(existing: sqlite3.Row, candidate: MemoryCandidate) -> bool:
    existing_target = str(existing["preference_target"]) if existing["preference_target"] else None
    existing_value = str(existing["preference_value"]) if existing["preference_value"] else None
    existing_polarity = (
        str(existing["preference_polarity"]) if existing["preference_polarity"] else None
    )
    return (
        existing_target == candidate.preference_target
        and existing_value == candidate.preference_value
        and existing_polarity == candidate.preference_polarity
    )


def _should_insert_revision(existing: sqlite3.Row, candidate: MemoryCandidate) -> bool:
    if candidate.match_id:
        return False
    if candidate.dedupe_key is None:
        return False
    candidate_representation = str(candidate.representation or "")
    existing_representation = str(existing["representation"] or "")
    if candidate_representation not in {"fact", "preference"}:
        return False
    if existing_representation and existing_representation != candidate_representation:
        return True

    existing_text = str(existing["canonical_text"] or existing["content"]).strip()
    candidate_text = (candidate.canonical_text or candidate.content).strip()
    if existing_text == candidate_text and _same_preference_payload(existing, candidate):
        return False
    return True


def _candidate_with_revision_link(candidate: MemoryCandidate, supersedes_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        memory_type=candidate.memory_type,
        content=candidate.content,
        source_turn=candidate.source_turn,
        source_message_excerpt=candidate.source_message_excerpt,
        confidence=candidate.confidence,
        ttl_days=candidate.ttl_days,
        decay_policy=candidate.decay_policy,
        dedupe_key=candidate.dedupe_key,
        candidate_reason=candidate.candidate_reason,
        topic_key=candidate.topic_key,
        tags=candidate.tags,
        summary=candidate.summary,
        pinned=candidate.pinned,
        merge_count=candidate.merge_count,
        followup_enabled=candidate.followup_enabled,
        followup_due_at=candidate.followup_due_at,
        metadata_json=candidate.metadata_json,
        match_id=None,
        memory_class=candidate.memory_class,
        representation=candidate.representation,
        namespace=candidate.namespace,
        owner_kind=candidate.owner_kind,
        canonical_text=candidate.canonical_text,
        structured_payload_json=candidate.structured_payload_json,
        evidence_json=candidate.evidence_json,
        source_kind=candidate.source_kind,
        source_ref=candidate.source_ref,
        review_state=candidate.review_state,
        stale_reason=candidate.stale_reason,
        last_confirmed_at=candidate.last_confirmed_at,
        last_used_at=candidate.last_used_at,
        supersedes_id=supersedes_id,
        contradicts_id=candidate.contradicts_id,
        strength=candidate.strength,
        useful_score=candidate.useful_score,
        cross_session_visible=candidate.cross_session_visible,
        preference_target=candidate.preference_target,
        preference_value=candidate.preference_value,
        preference_strength=candidate.preference_strength,
        preference_context=candidate.preference_context,
        preference_polarity=candidate.preference_polarity,
    )


def _replace_created_at(item: MemoryItem, created_at: str) -> MemoryItem:
    return MemoryItem(
        id=item.id,
        memory_type=item.memory_type,
        content=item.content,
        source_turn=item.source_turn,
        source_message_excerpt=item.source_message_excerpt,
        created_at=created_at,
        updated_at=item.updated_at,
        confidence=item.confidence,
        ttl_days=item.ttl_days,
        expires_at=item.expires_at,
        decay_policy=item.decay_policy,
        status=item.status,
        dedupe_key=item.dedupe_key,
        topic_key=item.topic_key,
        tags=item.tags,
        summary=item.summary,
        pinned=item.pinned,
        merge_count=item.merge_count,
        followup_enabled=item.followup_enabled,
        followup_due_at=item.followup_due_at,
        last_followup_at=item.last_followup_at,
        metadata_json=item.metadata_json,
        memory_class=item.memory_class,
        representation=item.representation,
        namespace=item.namespace,
        owner_kind=item.owner_kind,
        canonical_text=item.canonical_text,
        structured_payload_json=item.structured_payload_json,
        evidence_json=item.evidence_json,
        source_kind=item.source_kind,
        source_ref=item.source_ref,
        review_state=item.review_state,
        stale_reason=item.stale_reason,
        last_confirmed_at=item.last_confirmed_at,
        last_used_at=item.last_used_at,
        supersedes_id=item.supersedes_id,
        contradicts_id=item.contradicts_id,
        strength=item.strength,
        useful_score=item.useful_score,
        cross_session_visible=item.cross_session_visible,
        preference_target=item.preference_target,
        preference_value=item.preference_value,
        preference_strength=item.preference_strength,
        preference_context=item.preference_context,
        preference_polarity=item.preference_polarity,
    )
