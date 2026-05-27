from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import json
import sqlite3
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.memory.manager import MemoryManager
from src.memory.models import (
    MemoryItem,
    SessionMemoryCandidate,
    SessionMemoryItem,
    MemoryTurnInput,
    format_timestamp,
    now_timestamp,
)
from src.memory.summarizer import SessionSummarizer
from tests.support import TemporaryWorkspace, build_test_config


class SessionSummarizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summarizer = SessionSummarizer(episodic_ttl_days=7)
        self.now = now_timestamp()

    def _build_item(
        self,
        *,
        item_id: str,
        canonical_text: str,
        representation: str = "abstract",
        carryover_kind: str | None = None,
        namespace: str = "user_memory",
        owner_kind: str = "user",
        structured_payload_json: str | None = None,
    ) -> SessionMemoryItem:
        return SessionMemoryItem(
            id=item_id,
            session_id="session-test",
            representation=representation,  # type: ignore[arg-type]
            namespace=namespace,  # type: ignore[arg-type]
            owner_kind=owner_kind,  # type: ignore[arg-type]
            canonical_text=canonical_text,
            source_turn="turn-1",
            created_at=format_timestamp(self.now),
            updated_at=format_timestamp(self.now),
            expires_at=format_timestamp(self.now + timedelta(days=2)),
            carryover_kind=carryover_kind,
            origin_kind="session_only",
        )

    def test_small_talk_session_item_is_skipped(self) -> None:
        item = self._build_item(
            item_id="session-small-talk",
            canonical_text="哈哈，今天吃饭了，晚安。",
            carryover_kind="session",
        )

        result = self.summarizer.summarize(item, now=self.now)

        self.assertEqual(result.target_state, "skipped")
        self.assertEqual(result.promotion_candidates, ())

    def test_strong_event_session_item_promotes_to_episodic_candidate(self) -> None:
        item = self._build_item(
            item_id="session-episodic",
            canonical_text="今天已经完成 schema 迁移，并提交了测试结果。",
            carryover_kind="episodic",
        )

        result = self.summarizer.summarize(item, now=self.now)

        self.assertEqual(result.target_state, "promoted")
        self.assertEqual(result.promotion_candidates[0].candidate_kind, "episodic")
        self.assertEqual(result.promotion_candidates[0].memory_candidate.memory_class, "episodic")

    def test_followup_session_item_promotes_to_task_candidate(self) -> None:
        item = self._build_item(
            item_id="session-task",
            canonical_text="下次继续问我 schema 进度，顺便 reminder 我补测试。",
            carryover_kind="task",
        )

        result = self.summarizer.summarize(item, now=self.now)

        self.assertEqual(result.target_state, "promoted")
        self.assertEqual(result.promotion_candidates[0].candidate_kind, "task")
        self.assertTrue(result.promotion_candidates[0].memory_candidate.followup_enabled)

    def test_explicit_preference_session_item_promotes_to_preference_candidate(self) -> None:
        item = self._build_item(
            item_id="session-pref",
            canonical_text="当前会话里希望你继续用结构化回答。",
            representation="preference",
            carryover_kind="session",
            structured_payload_json=json.dumps(
                {
                    "preference_target": "interaction_style",
                    "preference_value": "结构化回答",
                    "preference_polarity": "prefer",
                },
                ensure_ascii=False,
            ),
        )

        result = self.summarizer.summarize(item, now=self.now)

        self.assertEqual(result.target_state, "promoted")
        self.assertEqual(result.promotion_candidates[0].candidate_kind, "preference")
        self.assertEqual(
            result.promotion_candidates[0].memory_candidate.preference_target,
            "interaction_style",
        )


class SessionConsolidationLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(
            self.workspace.db_path,
            max_memory_injection_items=3,
        )
        self.manager = MemoryManager.from_app_config(self.config)
        self.now = now_timestamp()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def _seed_session_item(
        self,
        *,
        item_id: str,
        canonical_text: str,
        representation: str = "abstract",
        carryover_kind: str | None = None,
        consolidation_state: str = "pending",
        origin_kind: str = "session_only",
        status: str = "active",
        expires_at: str | None = None,
        last_touched_at: str | None = None,
        namespace: str = "user_memory",
        owner_kind: str = "user",
        structured_payload_json: str | None = None,
    ) -> SessionMemoryItem:
        item = SessionMemoryItem(
            id=item_id,
            session_id="session-loop",
            representation=representation,  # type: ignore[arg-type]
            namespace=namespace,  # type: ignore[arg-type]
            owner_kind=owner_kind,  # type: ignore[arg-type]
            canonical_text=canonical_text,
            source_turn="turn-loop",
            created_at=format_timestamp(self.now),
            updated_at=format_timestamp(self.now),
            expires_at=expires_at or format_timestamp(self.now + timedelta(days=2)),
            status=status,  # type: ignore[arg-type]
            consolidation_state=consolidation_state,  # type: ignore[arg-type]
            origin_kind=origin_kind,  # type: ignore[arg-type]
            carryover_kind=carryover_kind,
            last_touched_at=last_touched_at or format_timestamp(self.now),
            structured_payload_json=structured_payload_json,
        )
        self.manager.store.seed_session_items([item])  # type: ignore[union-attr]
        return item

    def test_session_item_lifecycle_moves_pending_to_promoted_to_archived(self) -> None:
        self._seed_session_item(
            item_id="session-promote",
            canonical_text="下次继续问我 schema 进度，顺便 reminder 我补测试。",
            carryover_kind="task",
        )

        first = self.manager.run_session_maintenance(
            session_id="session-loop",
            now=self.now,
            limit=1,
        )

        self.assertEqual(first.processed_count, 1)
        self.assertEqual(first.processed[0].target_state, "promoted")
        session_item = self.manager.list_session_memories(
            session_id="session-loop",
            status="active",
        )[0]
        self.assertEqual(session_item.consolidation_state, "promoted")
        self.assertGreaterEqual(len(first.processed[0].produced_memory_refs), 1)

        second = self.manager.run_session_maintenance(
            session_id="session-loop",
            now=self.now + timedelta(hours=25),
            limit=1,
        )

        self.assertIn("session-promote", second.archived_session_ids)
        archived = self.manager.list_session_memories(
            session_id="session-loop",
            status="archived",
        )[0]
        self.assertEqual(archived.consolidation_state, "archived")

    def test_consolidation_promotion_path_is_idempotent_without_new_evidence(self) -> None:
        candidate = SessionMemoryCandidate(
            session_id="session-loop",
            canonical_text="下次继续问我 schema 进度，顺便 reminder 我补测试。",
            source_turn="turn-loop",
            representation="abstract",
            carryover_kind="task",
        )
        self.manager.store.upsert_session_candidate(  # type: ignore[union-attr]
            candidate,
            self.now.isoformat(timespec="seconds"),
        )

        first = self.manager.run_session_maintenance(
            session_id="session-loop",
            now=self.now,
            limit=1,
        )
        stored_count_after_first = len(self.manager.list_memories(status="active"))
        self.assertEqual(first.processed[0].target_state, "promoted")

        self.manager.store.upsert_session_candidate(  # type: ignore[union-attr]
            candidate,
            (self.now + timedelta(minutes=10)).isoformat(timespec="seconds"),
        )
        second = self.manager.run_session_maintenance(
            session_id="session-loop",
            now=self.now + timedelta(minutes=20),
            limit=1,
        )

        self.assertEqual(second.processed_count, 0)
        self.assertEqual(len(self.manager.list_memories(status="active")), stored_count_after_first)
        session_item = self.manager.list_session_memories(
            session_id="session-loop",
            status="active",
        )[0]
        self.assertEqual(session_item.consolidation_state, "promoted")
        self.assertGreaterEqual(len(session_item.produced_memory_refs), 1)

    def test_pending_session_item_gets_final_attempt_near_ttl(self) -> None:
        self._seed_session_item(
            item_id="session-final-attempt",
            canonical_text="下次继续问我 schema 进度，顺便 reminder 我补测试。",
            carryover_kind="task",
            expires_at=format_timestamp(self.now + timedelta(hours=1)),
        )

        result = self.manager.run_session_maintenance(
            session_id="session-loop",
            now=self.now,
            limit=1,
        )

        self.assertEqual(result.processed_count, 1)
        self.assertTrue(result.processed[0].final_attempt)
        self.assertEqual(result.processed[0].target_state, "promoted")

    def test_record_session_turn_only_adds_whitelisted_session_only_items(self) -> None:
        turn = MemoryTurnInput(
            user_input="这周我在重构 memory 模块，下周记得提醒我继续看 schema 迁移。我们先做 schema，再补测试。",
            assistant_reply="好。",
            scene="casual_chat",
            turn_id="turn-session-1",
        )

        session_items = self.manager.record_session_turn(
            session_id="session-loop",
            turn=turn,
            stored_items=(),
            now=self.now,
        )

        self.assertTrue(any(item.origin_kind == "session_only" for item in session_items))
        self.assertTrue(any(item.carryover_kind == "task" for item in session_items))
        self.assertTrue(any(item.carryover_kind == "session" for item in session_items))

        quiet_items = self.manager.record_session_turn(
            session_id="session-loop",
            turn=MemoryTurnInput(
                user_input="哈哈我刚吃完饭，准备睡了。",
                assistant_reply="晚安。",
                scene="casual_chat",
                turn_id="turn-session-2",
            ),
            stored_items=(),
            now=self.now + timedelta(minutes=1),
        )

        self.assertEqual(
            tuple(item.id for item in quiet_items if item.origin_kind == "session_only"),
            (),
        )

    def test_expired_or_archived_session_items_leave_retrieval_budget_to_long_term(self) -> None:
        self._seed_session_item(
            item_id="session-archive",
            canonical_text="下次继续问我 schema 进度。",
            carryover_kind="task",
            consolidation_state="promoted",
            last_touched_at=format_timestamp(self.now - timedelta(hours=30)),
        )
        self.manager.store.seed_items(  # type: ignore[union-attr]
            [
                MemoryItem(
                    id="pref-keep",
                    memory_type="profile",
                    content="用户喜欢结构化回答。",
                    source_turn="turn-pref",
                    source_message_excerpt="结构化回答",
                    created_at=format_timestamp(self.now),
                    updated_at=format_timestamp(self.now),
                    confidence=0.9,
                    ttl_days=None,
                    expires_at=None,
                    decay_policy="manual_override",
                    memory_class="profile",
                    representation="preference",
                    topic_key="schema|structured",
                    preference_target="interaction_style",
                    preference_value="结构化回答",
                )
            ]
        )

        before = self.manager.retrieve(
            user_input="继续看 schema 进度和结构化回答安排。",
            scene="casual_chat",
            session_id="session-loop",
            now=self.now,
        )
        self.assertTrue(before.prompt_items[0].startswith("[session]"))

        self.manager.run_session_maintenance(
            session_id="session-loop",
            now=self.now + timedelta(hours=25),
            limit=1,
        )
        after = self.manager.retrieve(
            user_input="继续看 schema 进度和结构化回答安排。",
            scene="casual_chat",
            session_id="session-loop",
            now=self.now + timedelta(hours=25),
        )

        self.assertTrue(after.hit)
        self.assertFalse(any(item.startswith("[session]") for item in after.prompt_items))
        self.assertTrue(any(item.startswith("[preference]") for item in after.prompt_items))

    def test_external_namespace_and_impression_do_not_promote(self) -> None:
        self._seed_session_item(
            item_id="session-external",
            canonical_text="外部资料说 SQLite 支持事务。",
            carryover_kind="episodic",
            namespace="external_knowledge",
            owner_kind="world",
        )
        self._seed_session_item(
            item_id="session-impression",
            canonical_text="关系温度似乎更高了。",
            carryover_kind="impression",
        )

        result = self.manager.run_session_maintenance(
            session_id="session-loop",
            now=self.now,
            limit=2,
        )

        reasons = {entry.session_item_id: entry.skipped_reason for entry in result.processed}
        self.assertEqual(reasons["session-external"], "non_user_namespace")
        self.assertEqual(reasons["session-impression"], "impression_soft_signal_only")
        self.assertEqual(self.manager.list_memories(memory_class="semantic"), ())


class SessionSchemaMigrationTests(unittest.TestCase):
    def test_legacy_session_schema_backfills_consolidation_columns(self) -> None:
        workspace = TemporaryWorkspace()
        try:
            with sqlite3.connect(workspace.db_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE session_memory_entries (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        representation TEXT NOT NULL,
                        namespace TEXT NOT NULL,
                        owner_kind TEXT NOT NULL,
                        canonical_text TEXT NOT NULL,
                        source_turn TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT,
                        status TEXT NOT NULL,
                        topic_key TEXT,
                        carryover_kind TEXT,
                        structured_payload_json TEXT,
                        metadata_json TEXT,
                        last_confirmed_at TEXT
                    );
                    """
                )
                connection.execute(
                    """
                    INSERT INTO session_memory_entries (
                        id, session_id, representation, namespace, owner_kind,
                        canonical_text, source_turn, created_at, updated_at,
                        expires_at, status, topic_key, carryover_kind,
                        structured_payload_json, metadata_json, last_confirmed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy-session",
                        "legacy-session-id",
                        "abstract",
                        "user_memory",
                        "user",
                        "下次继续问我 schema 进度。",
                        "turn-legacy",
                        "2026-04-01T00:00:00+08:00",
                        "2026-04-01T00:00:00+08:00",
                        "2026-04-03T00:00:00+08:00",
                        "active",
                        "schema|progress",
                        "task",
                        None,
                        None,
                        "2026-04-01T00:00:00+08:00",
                    ),
                )
            manager = MemoryManager.from_app_config(build_test_config(workspace.db_path))

            item = manager.list_session_memories(
                session_id="legacy-session-id",
                status="active",
            )[0]

            self.assertEqual(item.consolidation_state, "pending")
            self.assertEqual(item.origin_kind, "session_only")
            self.assertEqual(item.last_touched_at, "2026-04-01T00:00:00+08:00")
            with sqlite3.connect(workspace.db_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(session_memory_entries)")
                }
            self.assertIn("summary_text", columns)
            self.assertIn("promotion_fingerprint", columns)
        finally:
            workspace.cleanup()


if __name__ == "__main__":
    unittest.main()
