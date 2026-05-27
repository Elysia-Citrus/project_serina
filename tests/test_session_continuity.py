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
from src.memory.models import SessionContinuityRecord, format_timestamp, now_timestamp
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


class SessionContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(self.workspace.db_path)
        self.now = now_timestamp()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_first_session_query_can_read_persisted_start_time(self) -> None:
        gateway = DummyGateway(["好，我先记着。"])
        engine = DialogueEngine(self.config, gateway)
        coordinator = Coordinator(self.config, engine=engine)

        coordinator.process_user_message("这周我在准备期中汇报，下次可以继续问我进度。")

        next_engine = DialogueEngine(self.config, DummyGateway(["继续。"]))
        next_coordinator = Coordinator(self.config, engine=next_engine)

        result = next_coordinator.memory_service.retrieve(
            user_input="我们第一次会话是什么时候？",
            scene="casual_chat",
            session_id=next_coordinator.session.session_id,
            now=self.now + timedelta(minutes=5),
        )

        self.assertTrue(result.hit)
        self.assertTrue(result.prompt_items[0].startswith("[continuity] 已记录的第一次会话开始于"))
        self.assertTrue(result.selected_ids[0].startswith("continuity:"))

    def test_previous_session_query_prefers_summary_over_full_history(self) -> None:
        manager = Coordinator(
            self.config,
            engine=DialogueEngine(self.config, DummyGateway(["好。"])),
        ).memory_service
        manager.store.seed_session_continuity(  # type: ignore[union-attr]
            [
                SessionContinuityRecord(
                    session_id="session-old",
                    started_at=format_timestamp(self.now - timedelta(days=1, hours=2)),
                    last_active_at=format_timestamp(self.now - timedelta(days=1)),
                    turn_count=3,
                    first_user_message="我昨天讲了很多关于考试和报告的细节。",
                    last_user_message="我们最后在聊汇报收口和发言顺序。",
                    last_assistant_message="我会记着。",
                    last_scene="casual_chat",
                    summary_text="这轮主要聊到：汇报收口和发言顺序。",
                )
            ]
        )

        result = manager.retrieve(
            user_input="我们上次聊到哪了？",
            scene="casual_chat",
            session_id="session-current",
            now=self.now,
        )

        self.assertTrue(result.hit)
        self.assertIn("汇报收口和发言顺序", result.prompt_items[0])
        self.assertNotIn("讲了很多关于考试和报告的细节", result.prompt_items[0])

    def test_relevant_topic_can_pull_recent_session_summary(self) -> None:
        manager = Coordinator(
            self.config,
            engine=DialogueEngine(self.config, DummyGateway(["好。"])),
        ).memory_service
        manager.store.seed_session_continuity(  # type: ignore[union-attr]
            [
                SessionContinuityRecord(
                    session_id="session-schema",
                    started_at=format_timestamp(self.now - timedelta(hours=6)),
                    last_active_at=format_timestamp(self.now - timedelta(hours=4)),
                    turn_count=2,
                    first_user_message="我在处理 schema 收口。",
                    last_user_message="继续看 schema 收口和测试补齐。",
                    last_assistant_message="好。",
                    last_scene="casual_chat",
                    summary_text="这轮主要聊到：schema 收口和测试补齐。",
                )
            ]
        )

        result = manager.retrieve(
            user_input="继续看看 schema 收口吧。",
            scene="casual_chat",
            session_id="session-current",
            now=self.now,
        )

        self.assertTrue(result.hit)
        self.assertTrue(any(item.startswith("[continuity]") for item in result.prompt_items))
        self.assertIn("schema 收口和测试补齐", result.prompt_items[0])


if __name__ == "__main__":
    unittest.main()
