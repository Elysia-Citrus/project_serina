from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.assist_llm import AssistLLMService
from src.dialogue.engine import DialogueEngine
from src.llm.gateway import GatewayError
from src.memory.manager import MemoryManager
from src.observability.trace import TurnTrace
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


class AssistLLMRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_guard_retry_rewrite_accepts_after_assist_rewrite(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(
            [
                "你应该立刻停下内耗，按下面三步马上执行。",
                '{"revised_reply":"先别急着逼自己。今晚先缓一缓，我们就只收拾眼前这一小块。"}',
            ]
        )
        memory_manager = MemoryManager.from_app_config(config)
        assist_service = AssistLLMService.from_app_config(config, gateway)
        engine = DialogueEngine(
            config,
            gateway,
            memory_manager=memory_manager,
            assist_service=assist_service,
        )
        turn_trace = TurnTrace.create(config.runtime.debug_max_preview_chars)

        result = engine.generate_reply(
            user_input="我今天真的有点撑不住。",
            conversation_history=[],
            turn_trace=turn_trace,
        )

        self.assertEqual(result.reply_guard_initial_action, "retry_once")
        self.assertEqual(result.reply_guard_action, "accept")
        self.assertTrue(result.reply_guard_retry_attempted)
        self.assertIsNotNone(result.assist_llm_record)
        self.assertEqual(result.assist_llm_record.task, "guard_retry_rewrite")  # type: ignore[union-attr]
        self.assertTrue(result.assist_llm_record.success)  # type: ignore[union-attr]
        self.assertEqual(result.assist_llm_record.post_guard_action, "accept")  # type: ignore[union-attr]
        self.assertEqual(
            assist_service.runtime_calls_for_turn(turn_trace.turn_id),
            1,
        )
        request_tags = [call["options"].request_tag for call in gateway.calls]
        self.assertEqual(request_tags, ["primary", "assist_guard_retry_rewrite"])
        self.assertNotIn("你应该立刻", result.reply_text)

    def test_guard_retry_rewrite_falls_back_when_second_guard_fails(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(
            [
                "你应该立刻停下内耗，按下面三步马上执行。",
                '{"revised_reply":"你一直都是这种容易摆烂的性格，所以别矫情。"}',
            ]
        )
        memory_manager = MemoryManager.from_app_config(config)
        assist_service = AssistLLMService.from_app_config(config, gateway)
        engine = DialogueEngine(
            config,
            gateway,
            memory_manager=memory_manager,
            assist_service=assist_service,
        )
        turn_trace = TurnTrace.create(config.runtime.debug_max_preview_chars)

        result = engine.generate_reply(
            user_input="我今天心里堵得慌。",
            conversation_history=[],
            turn_trace=turn_trace,
        )

        self.assertEqual(result.reply_guard_initial_action, "retry_once")
        self.assertEqual(result.reply_guard_action, "safe_fallback")
        self.assertIsNotNone(result.assist_llm_record)
        self.assertEqual(result.assist_llm_record.post_guard_action, "safe_fallback")  # type: ignore[union-attr]
        self.assertEqual(len(gateway.calls), 2)
        self.assertNotIn("摆烂", result.reply_text)
        self.assertTrue(result.reply_guard_fallback_reason)

    def test_runtime_call_already_used_skips_assist_retry(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(
            [
                '{"verdict":"weakly_supported","reason":"borderline"}',
                "你应该立刻停下内耗，按下面三步马上执行。",
                "先别急着逼自己。我们先把最堵的那一点说出来。",
            ]
        )
        memory_manager = MemoryManager.from_app_config(config)
        assist_service = AssistLLMService.from_app_config(config, gateway)
        engine = DialogueEngine(
            config,
            gateway,
            memory_manager=memory_manager,
            assist_service=assist_service,
        )
        turn_trace = TurnTrace.create(config.runtime.debug_max_preview_chars)

        assist_result = assist_service.optional_memory_reference_check(
            user_input="今晚吃什么",
            reply_excerpt="我记得你之前一直在做项目。",
            memory_summaries=["用户最近在做桌面 agent 项目。"],
            linked_turn_id=turn_trace.turn_id,
            turn_trace=turn_trace,
            pre_guard_action="memory_reference_check",
        )
        self.assertTrue(assist_result.success)

        result = engine.generate_reply(
            user_input="我今天真的有点撑不住。",
            conversation_history=[],
            turn_trace=turn_trace,
        )

        self.assertEqual(result.reply_guard_initial_action, "retry_once")
        self.assertEqual(result.reply_guard_action, "accept")
        self.assertEqual(
            assist_service.runtime_calls_for_turn(turn_trace.turn_id),
            1,
        )
        request_tags = [call["options"].request_tag for call in gateway.calls]
        self.assertEqual(
            request_tags,
            [
                "assist_memory_reference_check",
                "primary",
                "reply_guard_retry",
            ],
        )
        self.assertNotIn("assist_guard_retry_rewrite", request_tags)

    def test_assist_timeout_falls_back_to_conservative_path(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(
            [
                "你应该立刻停下内耗，按下面三步马上执行。",
                GatewayError("assist timeout"),
            ]
        )
        memory_manager = MemoryManager.from_app_config(config)
        assist_service = AssistLLMService.from_app_config(config, gateway)
        engine = DialogueEngine(
            config,
            gateway,
            memory_manager=memory_manager,
            assist_service=assist_service,
        )
        turn_trace = TurnTrace.create(config.runtime.debug_max_preview_chars)

        result = engine.generate_reply(
            user_input="我今天心里很堵。",
            conversation_history=[],
            turn_trace=turn_trace,
        )

        self.assertEqual(result.reply_guard_initial_action, "retry_once")
        self.assertEqual(result.reply_guard_action, "safe_fallback")
        self.assertIsNotNone(result.assist_llm_record)
        self.assertEqual(result.assist_llm_record.error_type, "GatewayError")  # type: ignore[union-attr]
        self.assertTrue(result.assist_llm_record.fallback_to_rules)  # type: ignore[union-attr]
        request_tags = [call["options"].request_tag for call in gateway.calls]
        self.assertEqual(request_tags, ["primary", "assist_guard_retry_rewrite"])
        self.assertNotIn("你应该立刻", result.reply_text)


if __name__ == "__main__":
    unittest.main()
