from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.memory.manager import MemoryManager
from src.memory.models import MemoryTurnInput, SessionMemoryItem, format_timestamp, now_timestamp
from tests.support import TemporaryWorkspace, build_test_config


class SessionFinalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(self.workspace.db_path)
        self.manager = MemoryManager.from_app_config(self.config)
        self.now = now_timestamp()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_finalize_session_promotes_open_loop_and_updates_continuity_summary(self) -> None:
        session_id = "session-finalize"
        self.manager.register_session(
            session_id=session_id,
            started_at=self.now,
        )
        self.manager.record_session_turn(
            session_id=session_id,
            turn=MemoryTurnInput(
                user_input="下次继续问我 startup memory 的回归测试，顺便提醒我把 consolidation 收口。",
                assistant_reply="好，我记着。",
                scene="casual_chat",
                turn_id="turn-1",
            ),
            stored_items=(),
            now=self.now,
        )

        result = self.manager.finalize_session(
            session_id=session_id,
            now=self.now + timedelta(minutes=5),
        )

        self.assertTrue(result.consolidation_triggered)
        self.assertTrue(result.continuity_updated)
        self.assertGreaterEqual(result.promoted_memory_count, 1)
        self.assertGreaterEqual(len(result.open_loop_memory_ids), 1)

        continuity = self.manager.list_session_continuity(limit=1)[0]
        self.assertIsNotNone(continuity.summary_text)
        self.assertIn("Last session", continuity.summary_text or "")

        promoted = self.manager.list_memories(memory_class="task", status="active")
        self.assertTrue(promoted)
        self.assertTrue(promoted[0].cross_session_visible)

    def test_finalize_session_skips_noise_only_session(self) -> None:
        session_id = "session-noise"
        self.manager.register_session(
            session_id=session_id,
            started_at=self.now,
        )
        self.manager.store.seed_session_items(  # type: ignore[union-attr]
            [
                SessionMemoryItem(
                    id="noise-session-item",
                    session_id=session_id,
                    representation="abstract",
                    namespace="user_memory",
                    owner_kind="user",
                    canonical_text="哈哈，刚吃完饭，准备睡了。",
                    source_turn="turn-noise",
                    created_at=format_timestamp(self.now),
                    updated_at=format_timestamp(self.now),
                    expires_at=format_timestamp(self.now + timedelta(days=2)),
                    carryover_kind="session",
                    origin_kind="session_only",
                )
            ]
        )

        result = self.manager.finalize_session(
            session_id=session_id,
            now=self.now + timedelta(minutes=2),
        )

        self.assertEqual(result.promoted_memory_ids, ())
        self.assertIn(result.skipped_reason or "", {"", "empty_session"})
        self.assertEqual(self.manager.list_memories(status="active"), ())


if __name__ == "__main__":
    unittest.main()
