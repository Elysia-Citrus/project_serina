from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sqlite3
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.coordinator import Coordinator
from src.dialogue.engine import DialogueEngine
from src.memory.manager import MemoryManager
from src.memory.models import MemoryItem, MemoryTurnInput, SessionMemoryItem, format_timestamp, now_timestamp
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


LEGACY_SCHEMA_SQL = """
CREATE TABLE memory_entries (
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
    dedupe_key TEXT
);
"""


class MemorySchemaV02Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(
            self.workspace.db_path,
            max_memory_injection_items=3,
        )
        self.manager = MemoryManager.from_app_config(self.config)

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_legacy_migration_backfills_v02_fields(self) -> None:
        self.workspace.cleanup()
        self.workspace = TemporaryWorkspace()
        with sqlite3.connect(self.workspace.db_path) as connection:
            connection.executescript(LEGACY_SCHEMA_SQL)
            connection.execute(
                """
                INSERT INTO memory_entries (
                    id, memory_type, content, source_turn, source_message_excerpt,
                    created_at, updated_at, confidence, ttl_days, expires_at,
                    decay_policy, status, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-pref",
                    "profile",
                    "用户偏好被称呼为阿泽。",
                    "legacy-turn",
                    "以后叫我阿泽",
                    "2026-04-01T00:00:00+08:00",
                    "2026-04-01T00:00:00+08:00",
                    0.92,
                    None,
                    None,
                    "manual_override",
                    "active",
                    "profile:address",
                ),
            )

        store = MemoryManager.from_app_config(
            build_test_config(self.workspace.db_path)
        ).store
        item = store.get_item("legacy-pref")  # type: ignore[union-attr]

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.memory_class, "profile")
        self.assertEqual(item.representation, "preference")
        self.assertEqual(item.canonical_text, "用户偏好被称呼为阿泽。")
        self.assertEqual(item.preference_target, "address")
        self.assertEqual(item.preference_value, "阿泽")
        self.assertEqual(item.review_state, "active")
        self.assertEqual(item.namespace, "user_memory")
        self.assertEqual(item.owner_kind, "user")
        with sqlite3.connect(self.workspace.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("session_memory_entries", tables)

    def test_memory_class_and_representation_mapping_for_task_like_legacy_item(self) -> None:
        now = now_timestamp()
        item = MemoryItem(
            id="legacy-task",
            memory_type="episodic",
            content="用户近期事项：用户这周在推进 memory schema 修正。",
            source_turn="turn-1",
            source_message_excerpt="这周在推进 memory schema 修正",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            confidence=0.84,
            ttl_days=7,
            expires_at=format_timestamp(now + timedelta(days=7)),
            decay_policy="ttl_expiry",
            status="active",
            tags=("task", "project"),
            summary="用户最近在做 memory schema 修正。",
            followup_enabled=True,
        )

        self.assertEqual(item.memory_class, "task")
        self.assertEqual(item.representation, "abstract")

    def test_preference_write_and_retrieval_use_explicit_preference_lane(self) -> None:
        result = self.manager.write_turn(
            MemoryTurnInput(
                user_input="以后叫我阿泽吧，我更喜欢你直接一点。",
                assistant_reply="好。",
                scene="casual_chat",
                turn_id="turn-pref",
            )
        )

        self.assertTrue(result.wrote_any)
        stored = self.manager.list_memories(status="active")
        self.assertTrue(any(item.representation == "preference" for item in stored))
        self.assertTrue(any(item.preference_target == "address" for item in stored))

        retrieve_result = self.manager.retrieve(
            user_input="你就直接一点回答我吧",
            scene="casual_chat",
        )

        self.assertTrue(retrieve_result.hit)
        self.assertTrue(any(item.startswith("[preference]") for item in retrieve_result.prompt_items))

    def test_supersedes_and_review_state_keep_old_record_in_history(self) -> None:
        first = self.manager.write_turn(
            MemoryTurnInput(
                user_input="以后叫我阿泽吧。",
                assistant_reply="好。",
                scene="casual_chat",
                turn_id="turn-a",
            )
        )
        old_item = first.stored_items[0]

        second = self.manager.write_turn(
            MemoryTurnInput(
                user_input="以后别叫我阿泽，叫我老师。",
                assistant_reply="记住了。",
                scene="casual_chat",
                turn_id="turn-b",
            )
        )
        new_item = second.stored_items[0]

        self.assertEqual(new_item.supersedes_id, old_item.id)
        stale_version = self.manager.get_memory(old_item.id)
        self.assertIsNotNone(stale_version)
        assert stale_version is not None
        self.assertEqual(stale_version.review_state, "stale")
        self.assertTrue((stale_version.stale_reason or "").startswith("superseded_by:"))

        updated = self.manager.update_memory(
            new_item.id,
            review_state="pending_review",
            contradicts_id=old_item.id,
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.review_state, "pending_review")
        self.assertEqual(updated.contradicts_id, old_item.id)

    def test_session_and_working_memory_stay_out_of_long_term_main_table(self) -> None:
        gateway = DummyGateway(["好的，我会记着。"])
        engine = DialogueEngine(
            self.config,
            gateway,
            memory_manager=self.manager,
        )
        coordinator = Coordinator(self.config, engine=engine)

        coordinator.process_user_message("这周我在重构 memory 模块，下周记得问我进度。")

        session_items = self.manager.list_session_memories(session_id=coordinator.session.session_id)
        self.assertGreaterEqual(len(session_items), 1)
        self.assertIsNotNone(coordinator.session.working.current_task_hint)
        long_term_items = self.manager.list_memories(status="active")
        self.assertFalse(any(item.memory_class == "session" for item in long_term_items))
        self.assertFalse(any(item.memory_class == "working" for item in long_term_items))

    def test_namespace_owner_kind_boundary_is_enforced(self) -> None:
        now = now_timestamp()
        with self.assertRaises(ValueError):
            MemoryItem(
                id="bad-owner",
                memory_type="profile",
                content="外部知识：SQLite 支持事务。",
                source_turn="ext-1",
                source_message_excerpt="SQLite 支持事务",
                created_at=format_timestamp(now),
                updated_at=format_timestamp(now),
                confidence=0.8,
                ttl_days=None,
                expires_at=None,
                decay_policy="manual_override",
                namespace="external_knowledge",  # type: ignore[arg-type]
                owner_kind="user",  # type: ignore[arg-type]
            )

        external = MemoryItem(
            id="ext-good",
            memory_type="profile",
            content="外部知识：SQLite 支持事务。",
            source_turn="ext-2",
            source_message_excerpt="SQLite 支持事务",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            confidence=0.8,
            ttl_days=None,
            expires_at=None,
            decay_policy="manual_override",
            memory_class="semantic",
            representation="note",
            namespace="external_knowledge",
            owner_kind="world",
        )
        self.assertEqual(external.namespace, "external_knowledge")
        self.assertEqual(external.owner_kind, "world")

    def test_impression_only_enters_prompt_as_soft_signal(self) -> None:
        now = now_timestamp()
        fact = MemoryItem(
            id="fact-1",
            memory_type="profile",
            content="用户是会计专业。",
            source_turn="turn-fact",
            source_message_excerpt="我是会计专业",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            confidence=0.95,
            ttl_days=None,
            expires_at=None,
            decay_policy="manual_override",
            memory_class="profile",
            representation="fact",
            topic_key="会计专业",
        )
        impression = MemoryItem(
            id="impression-1",
            memory_type="profile",
            content="关系软信号：用户最近似乎更信任直接风格。",
            source_turn="turn-impression",
            source_message_excerpt="最近似乎更信任直接风格",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            confidence=0.72,
            ttl_days=None,
            expires_at=None,
            decay_policy="manual_override",
            memory_class="impression",
            representation="abstract",
            topic_key="直接风格",
        )
        self.manager.store.seed_items([fact, impression])  # type: ignore[union-attr]

        result = self.manager.retrieve(
            user_input="你还记得我的专业吗，还有最近交流风格的变化吗？",
            scene="casual_chat",
        )

        self.assertTrue(result.hit)
        self.assertTrue(result.prompt_items[0].startswith("[profile]"))
        self.assertTrue(any("soft signal only" in item for item in result.prompt_items if item.startswith("[impression-soft]")))

    def test_retrieval_order_is_session_then_task_then_preference_with_budget(self) -> None:
        now = now_timestamp()
        task = MemoryItem(
            id="task-1",
            memory_type="episodic",
            content="用户近期事项：用户这周在推进 memory schema 修正。",
            source_turn="turn-task",
            source_message_excerpt="推进 memory schema 修正",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            confidence=0.9,
            ttl_days=7,
            expires_at=format_timestamp(now + timedelta(days=7)),
            decay_policy="ttl_expiry",
            memory_class="task",
            representation="abstract",
            topic_key="memory|schema",
            summary="用户最近在做 memory schema 修正。",
            followup_enabled=True,
        )
        preference = MemoryItem(
            id="pref-1",
            memory_type="profile",
            content="用户喜欢结构化回答。",
            source_turn="turn-pref",
            source_message_excerpt="喜欢结构化回答",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            confidence=0.88,
            ttl_days=None,
            expires_at=None,
            decay_policy="manual_override",
            memory_class="profile",
            representation="preference",
            topic_key="结构化回答",
            preference_target="interaction_style",
            preference_value="结构化回答",
        )
        external = MemoryItem(
            id="ext-1",
            memory_type="profile",
            content="外部知识：schema migration 通常需要回填策略。",
            source_turn="turn-ext",
            source_message_excerpt="schema migration 需要回填",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            confidence=0.75,
            ttl_days=None,
            expires_at=None,
            decay_policy="manual_override",
            memory_class="semantic",
            representation="note",
            namespace="external_knowledge",
            owner_kind="world",
            topic_key="schema|migration",
        )
        session = SessionMemoryItem(
            id="session-1",
            session_id="session-x",
            representation="abstract",
            namespace="user_memory",
            owner_kind="user",
            canonical_text="本次会话正在推进 memory schema 修正，并准备收口迁移与测试。",
            source_turn="turn-session",
            created_at=format_timestamp(now),
            updated_at=format_timestamp(now),
            expires_at=format_timestamp(now + timedelta(days=3)),
            topic_key="memory|schema",
            carryover_kind="task",
        )
        self.manager.store.seed_items([task, preference, external])  # type: ignore[union-attr]
        self.manager.store.seed_session_items([session])  # type: ignore[union-attr]

        result = self.manager.retrieve(
            user_input="继续看 memory schema、迁移和结构化回答的安排。",
            scene="casual_chat",
            session_id="session-x",
        )

        self.assertEqual(len(result.prompt_items), 3)
        self.assertTrue(result.prompt_items[0].startswith("[session]"))
        self.assertTrue(result.prompt_items[1].startswith("[task]"))
        self.assertTrue(result.prompt_items[2].startswith("[preference]"))


if __name__ == "__main__":
    unittest.main()
