from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.memory.models import ConversationTurn
from src.memory.store import SCHEMA_VERSION, SQLiteMemoryStore
from tests.support import TemporaryWorkspace


OLD_SCHEMA_SQL = """
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


class MemoryStoreMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_initialize_migrates_old_schema_before_creating_indexes(self) -> None:
        with sqlite3.connect(self.workspace.db_path) as connection:
            connection.executescript(OLD_SCHEMA_SQL)
            connection.execute(
                """
                INSERT INTO memory_entries (
                    id, memory_type, content, source_turn, source_message_excerpt,
                    created_at, updated_at, confidence, ttl_days, expires_at,
                    decay_policy, status, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-1",
                    "episodic",
                    "用户最近在做旧项目。",
                    "legacy-turn",
                    "旧项目",
                    "2026-04-01T00:00:00+08:00",
                    "2026-04-01T00:00:00+08:00",
                    0.8,
                    7,
                    "2026-04-08T00:00:00+08:00",
                    "ttl_expiry",
                    "active",
                    "legacy",
                ),
            )

        store = SQLiteMemoryStore(self.workspace.db_path)
        item = store.get_item("legacy-1")

        self.assertIsNotNone(item)
        with sqlite3.connect(self.workspace.db_path) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(memory_entries)")
            }
            indexes = {
                row[1] for row in connection.execute("PRAGMA index_list(memory_entries)")
            }

        self.assertIn("topic_key", columns)
        self.assertIn("summary", columns)
        self.assertIn("idx_memory_topic_key", indexes)
        self.assertIn("idx_memory_followup_due_at", indexes)
        with sqlite3.connect(self.workspace.db_path) as connection:
            version = connection.execute(
                "SELECT value FROM memory_store_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
            turn_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(conversation_turns)")
            }

        self.assertEqual(version, str(SCHEMA_VERSION))
        self.assertIn("assistant_text", turn_columns)

    def test_conversation_turns_can_be_written_and_listed(self) -> None:
        store = SQLiteMemoryStore(self.workspace.db_path)

        turn_id = store.save_conversation_turn(
            ConversationTurn(
                id="turn-1",
                session_id="session-1",
                turn_index=1,
                source_channel="voice",
                user_text="hello",
                assistant_text="hi",
                raw_asr_text="hello",
                scene="casual_chat",
                started_at="2026-05-26T10:00:00+08:00",
                completed_at="2026-05-26T10:00:01+08:00",
                llm_provider="mock",
                llm_model="mock-model",
                asr_provider="myneuro_asr",
                tts_provider="gpt_sovits_v2",
            )
        )

        turns = store.list_conversation_turns(session_id="session-1")

        self.assertEqual(turn_id, "turn-1")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].source_channel, "voice")
        self.assertEqual(turns[0].assistant_text, "hi")


if __name__ == "__main__":
    unittest.main()
