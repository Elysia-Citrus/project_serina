from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Iterable
from uuid import uuid4
import json
import sqlite3

from src.memory.models import (
    MemoryCandidate,
    MemoryItem,
    MemoryStoreStats,
    format_timestamp,
    parse_timestamp,
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_turn TEXT NOT NULL,
    source_message_excerpt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confidence REAL NOT NULL,
    ttl_days INTEGER,
    expires_at TEXT,
    decay_policy TEXT NOT NULL,
    status TEXT NOT NULL,
    dedupe_key TEXT,
    topic_key TEXT,
    tags_json TEXT,
    summary TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    merge_count INTEGER NOT NULL DEFAULT 1,
    followup_enabled INTEGER NOT NULL DEFAULT 0,
    followup_due_at TEXT,
    last_followup_at TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_status_type
ON memory_entries(status, memory_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_expires_at
ON memory_entries(expires_at);

CREATE INDEX IF NOT EXISTS idx_memory_dedupe_key
ON memory_entries(dedupe_key);

CREATE INDEX IF NOT EXISTS idx_memory_topic_key
ON memory_entries(topic_key, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_followup_due_at
ON memory_entries(followup_enabled, followup_due_at);
"""

MISSING_COLUMNS = {
    "topic_key": "TEXT",
    "tags_json": "TEXT",
    "summary": "TEXT",
    "pinned": "INTEGER NOT NULL DEFAULT 0",
    "merge_count": "INTEGER NOT NULL DEFAULT 1",
    "followup_enabled": "INTEGER NOT NULL DEFAULT 0",
    "followup_due_at": "TEXT",
    "last_followup_at": "TEXT",
    "metadata_json": "TEXT",
}

_UNSET = object()


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
                WHERE memory_type = 'episodic'
                  AND status = 'active'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                """,
                (now_iso, now_iso),
            )
            return cursor.rowcount

    def list_active_items(self) -> list[MemoryItem]:
        return self.list_items(status="active")

    def list_items(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = "active",
        limit: int | None = None,
    ) -> list[MemoryItem]:
        query = ["SELECT * FROM memory_entries WHERE 1 = 1"]
        params: list[object] = []
        if memory_type is not None:
            query.append("AND memory_type = ?")
            params.append(memory_type)
        if status is not None:
            query.append("AND status = ?")
            params.append(status)
        query.append("ORDER BY pinned DESC, updated_at DESC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(" ".join(query), params).fetchall()
        return [self._row_to_item(row) for row in rows]

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
        confidence: float | object = _UNSET,
        expires_at: str | None | object = _UNSET,
        summary: str | None | object = _UNSET,
        status: str | object = _UNSET,
    ) -> MemoryItem | None:
        updates: list[str] = ["updated_at = ?"]
        params: list[object] = [now_iso]
        if content is not _UNSET:
            updates.append("content = ?")
            params.append(content)
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

    def upsert_candidate(
        self,
        candidate: MemoryCandidate,
        now_iso: str,
    ) -> tuple[MemoryItem, str]:
        with self._connect() as conn:
            existing = self._find_existing(conn, candidate)
            expires_at = _expires_at_from_candidate(candidate, now_iso)
            tags_json = _serialize_tags(candidate.tags)
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
                merge_count = max(
                    candidate.merge_count,
                    int(existing["merge_count"] or 1),
                )
                followup_enabled = int(
                    candidate.followup_enabled or bool(existing["followup_enabled"])
                )
                followup_due_at = candidate.followup_due_at or (
                    str(existing["followup_due_at"]) if existing["followup_due_at"] else None
                )
                metadata_json = candidate.metadata_json or (
                    str(existing["metadata_json"]) if existing["metadata_json"] else None
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
                        source_turn = ?,
                        source_message_excerpt = ?,
                        updated_at = ?,
                        confidence = ?,
                        ttl_days = ?,
                        expires_at = ?,
                        decay_policy = ?,
                        status = 'active',
                        dedupe_key = ?,
                        topic_key = ?,
                        tags_json = ?,
                        summary = ?,
                        pinned = ?,
                        merge_count = ?,
                        followup_enabled = ?,
                        followup_due_at = ?,
                        metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        candidate.content,
                        candidate.source_turn,
                        candidate.source_message_excerpt,
                        now_iso,
                        candidate.confidence,
                        resolved_ttl_days,
                        resolved_expires_at,
                        candidate.decay_policy,
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

            memory_id = uuid4().hex
            conn.execute(
                """
                INSERT INTO memory_entries (
                    id,
                    memory_type,
                    content,
                    source_turn,
                    source_message_excerpt,
                    created_at,
                    updated_at,
                    confidence,
                    ttl_days,
                    expires_at,
                    decay_policy,
                    status,
                    dedupe_key,
                    topic_key,
                    tags_json,
                    summary,
                    pinned,
                    merge_count,
                    followup_enabled,
                    followup_due_at,
                    last_followup_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    candidate.memory_type,
                    candidate.content,
                    candidate.source_turn,
                    candidate.source_message_excerpt,
                    now_iso,
                    now_iso,
                    candidate.confidence,
                    candidate.ttl_days,
                    expires_at,
                    candidate.decay_policy,
                    candidate.dedupe_key,
                    candidate.topic_key,
                    tags_json,
                    candidate.summary,
                    int(candidate.pinned),
                    max(1, candidate.merge_count),
                    int(candidate.followup_enabled),
                    candidate.followup_due_at,
                    None,
                    candidate.metadata_json,
                ),
            )
            row = conn.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (memory_id,),
            ).fetchone()

        if row is None:
            raise RuntimeError("Inserted memory row was not found.")
        return self._row_to_item(row), "inserted"

    def seed_items(self, items: Iterable[MemoryItem]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO memory_entries (
                    id,
                    memory_type,
                    content,
                    source_turn,
                    source_message_excerpt,
                    created_at,
                    updated_at,
                    confidence,
                    ttl_days,
                    expires_at,
                    decay_policy,
                    status,
                    dedupe_key,
                    topic_key,
                    tags_json,
                    summary,
                    pinned,
                    merge_count,
                    followup_enabled,
                    followup_due_at,
                    last_followup_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.memory_type,
                        item.content,
                        item.source_turn,
                        item.source_message_excerpt,
                        item.created_at,
                        item.updated_at,
                        item.confidence,
                        item.ttl_days,
                        item.expires_at,
                        item.decay_policy,
                        item.status,
                        item.dedupe_key,
                        item.topic_key,
                        _serialize_tags(item.tags),
                        item.summary,
                        int(item.pinned),
                        item.merge_count,
                        int(item.followup_enabled),
                        item.followup_due_at,
                        item.last_followup_at,
                        item.metadata_json,
                    )
                    for item in items
                ],
            )

    def get_stats(self) -> MemoryStoreStats:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, memory_type, COUNT(*) AS count
                FROM memory_entries
                GROUP BY status, memory_type
                """
            ).fetchall()

        stats = {("active", "profile"): 0, ("active", "episodic"): 0}
        expired_count = 0
        archived_count = 0
        for row in rows:
            status = str(row["status"])
            memory_type = str(row["memory_type"])
            count = int(row["count"])
            if status == "expired":
                expired_count += count
                continue
            if status == "archived":
                archived_count += count
                continue
            stats[(status, memory_type)] = count

        return MemoryStoreStats(
            active_profile_count=stats[("active", "profile")],
            active_episodic_count=stats[("active", "episodic")],
            expired_count=expired_count,
            archived_count=archived_count,
        )

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._ensure_columns(conn)

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
            conn.execute(
                f"ALTER TABLE memory_entries ADD COLUMN {name} {definition}"
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
              AND content = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (candidate.memory_type, candidate.content),
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
        )


def _expires_at_from_candidate(candidate: MemoryCandidate, now_iso: str) -> str | None:
    if candidate.ttl_days is None:
        return None
    return format_timestamp(parse_timestamp(now_iso) + timedelta(days=candidate.ttl_days))


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


def _merge_tags(existing: Iterable[str], incoming: Iterable[str]) -> tuple[str, ...]:
    merged = [*existing, *incoming]
    return tuple(sorted({tag for tag in merged if tag}))


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
    )
