from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.coordinator import Coordinator
from src.dialogue.engine import DialogueEngine
from src.memory.models import MemoryItem, SessionContinuityRecord, format_timestamp, now_timestamp
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


class StartupMemoryPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(
            self.workspace.db_path,
            reply_guard_enabled=False,
            assist_llm_enabled=False,
        )
        self.now = now_timestamp()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def _seed_cross_session_context(self, coordinator: Coordinator) -> None:
        coordinator.memory_service.store.seed_items(  # type: ignore[union-attr]
            [
                MemoryItem(
                    id="profile-1",
                    memory_type="profile",
                    content="用户偏好更自然、别太像说明书的回答。",
                    source_turn="turn-profile",
                    source_message_excerpt="更自然地回答",
                    created_at=format_timestamp(self.now - timedelta(days=8)),
                    updated_at=format_timestamp(self.now - timedelta(days=2)),
                    confidence=0.92,
                    ttl_days=None,
                    expires_at=None,
                    decay_policy="manual_override",
                    memory_class="profile",
                    representation="preference",
                    preference_target="interaction_style",
                    preference_value="自然回答",
                ),
                MemoryItem(
                    id="task-1",
                    memory_type="episodic",
                    content="近期要继续补 startup memory 的跨窗口回归测试。",
                    source_turn="turn-task",
                    source_message_excerpt="继续补回归测试",
                    created_at=format_timestamp(self.now - timedelta(hours=10)),
                    updated_at=format_timestamp(self.now - timedelta(hours=3)),
                    confidence=0.87,
                    ttl_days=7,
                    expires_at=format_timestamp(self.now + timedelta(days=5)),
                    decay_policy="ttl_expiry",
                    memory_class="task",
                    followup_enabled=True,
                    topic_key="startup|memory|test",
                ),
                MemoryItem(
                    id="episodic-1",
                    memory_type="episodic",
                    content="最近主线是把 startup memory pack 和 session consolidation 串起来。",
                    source_turn="turn-episodic",
                    source_message_excerpt="startup memory pack",
                    created_at=format_timestamp(self.now - timedelta(hours=8)),
                    updated_at=format_timestamp(self.now - timedelta(hours=2)),
                    confidence=0.82,
                    ttl_days=7,
                    expires_at=format_timestamp(self.now + timedelta(days=5)),
                    decay_policy="ttl_expiry",
                    memory_class="episodic",
                    source_kind="session_consolidation",
                    topic_key="startup|memory|consolidation",
                ),
            ]
        )
        coordinator.memory_service.store.seed_session_continuity(  # type: ignore[union-attr]
            [
                SessionContinuityRecord(
                    session_id="session-prev",
                    started_at=format_timestamp(self.now - timedelta(hours=6)),
                    last_active_at=format_timestamp(self.now - timedelta(hours=1)),
                    turn_count=4,
                    first_user_message="我们在收 startup memory 的方案。",
                    last_user_message="下次继续把 startup retrieval 和 consolidation 收口。",
                    last_assistant_message="好，我记着。",
                    last_scene="casual_chat",
                    summary_text="Last session focused on: startup retrieval and consolidation polish",
                )
            ]
        )

    def test_startup_pack_prioritizes_summary_and_open_loop_on_continuation_cue(self) -> None:
        coordinator = Coordinator(
            self.config,
            engine=DialogueEngine(self.config, DummyGateway(["好，我们继续把那条主线往前推。"])),
        )
        self._seed_cross_session_context(coordinator)

        result = coordinator.process_user_message("继续")

        self.assertTrue(result.startup_memory_pack_present)
        self.assertEqual(result.retrieval_mode, "startup")
        self.assertTrue(result.continuation_cue_detected)
        self.assertTrue(result.last_session_summary_used)
        self.assertLessEqual(result.startup_memory_pack_count, 6)
        self.assertIn("last_session_summary", result.startup_memory_categories)
        self.assertTrue(any(memory_id.startswith("continuity:") for memory_id in result.startup_memory_memory_ids))

    def test_startup_pack_stays_small_for_plain_greeting(self) -> None:
        coordinator = Coordinator(
            self.config,
            engine=DialogueEngine(self.config, DummyGateway(["老师，我在。"])),
        )
        self._seed_cross_session_context(coordinator)

        result = coordinator.process_user_message("你好")

        self.assertTrue(result.startup_memory_pack_present)
        self.assertEqual(result.retrieval_mode, "startup")
        self.assertFalse(result.continuation_cue_detected)
        self.assertLessEqual(result.startup_memory_pack_count, 2)
        self.assertTrue(all(category == "profile" for category in result.startup_memory_categories))

    def test_empty_startup_pack_falls_back_gracefully(self) -> None:
        coordinator = Coordinator(
            self.config,
            engine=DialogueEngine(self.config, DummyGateway(["老师，我在。"])),
        )

        result = coordinator.process_user_message("继续")

        self.assertFalse(result.startup_memory_pack_present)
        self.assertEqual(result.retrieval_mode, "query")
        self.assertEqual(result.startup_memory_pack_count, 0)


if __name__ == "__main__":
    unittest.main()
