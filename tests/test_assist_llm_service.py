from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.assist_llm import AssistLLMService
from src.dialogue.reply_guard import ReplyGuard
from src.memory.manager import MemoryManager
from src.memory.models import MemoryTurnInput, now_timestamp
from tests.regression.helpers import build_guard_case_memory_result
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


class AssistLLMServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_optional_memory_reference_check_reports_weak_support(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(
            ['{"verdict":"weakly_supported","reason":"same recent fatigue topic"}']
        )
        assist_service = AssistLLMService.from_app_config(config, gateway)
        guard = ReplyGuard(
            config.runtime,
            config.persona,
            config.policy,
            assist_service=assist_service,
        )
        memory_result = build_guard_case_memory_result(
            {
                "injected_memories": [
                    {
                        "id": "m-1",
                        "type": "episodic",
                        "content": "用户这两天确实比较累。",
                        "relevant": True,
                    }
                ]
            }
        )

        decision = guard.evaluate(
            reply_text="我记得你前两天挺累的，今晚稍微歇一下也正常。",
            raw_reply_text="我记得你前两天挺累的，今晚稍微歇一下也正常。",
            user_input="今晚想偷懒一下。",
            scene="casual_chat",
            memory_result=memory_result,
            allow_retry=True,
            linked_turn_id="turn-weak-support",
        )

        self.assertEqual(decision.memory_reference_verdict, "weakly_supported")
        self.assertIn("unnatural_memory_reference", decision.violation_codes)
        self.assertEqual(decision.initial_action, "rewrite")
        self.assertIsNotNone(decision.assist_record)
        self.assertEqual(decision.assist_record.task, "optional_memory_reference_check")  # type: ignore[union-attr]

    def test_unsupported_memory_reference_never_relaxes_fake_memory_claim(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(['{"verdict":"unsupported","reason":"memory is off-topic"}'])
        assist_service = AssistLLMService.from_app_config(config, gateway)
        guard = ReplyGuard(
            config.runtime,
            config.persona,
            config.policy,
            assist_service=assist_service,
        )
        memory_result = build_guard_case_memory_result(
            {
                "injected_memories": [
                    {
                        "id": "m-2",
                        "type": "episodic",
                        "content": "用户最近在做桌面 agent 项目。",
                        "relevant": True,
                    }
                ]
            }
        )

        decision = guard.evaluate(
            reply_text="我记得你前两天挺累的，今晚稍微歇一下也正常。",
            raw_reply_text="我记得你前两天挺累的，今晚稍微歇一下也正常。",
            user_input="今晚想偷懒一下。",
            scene="casual_chat",
            memory_result=memory_result,
            allow_retry=True,
            linked_turn_id="turn-unsupported",
        )

        self.assertEqual(decision.memory_reference_verdict, "unsupported")
        self.assertIn("fake_memory_claim", decision.violation_codes)
        self.assertEqual(decision.initial_action, "retry_once")

    def test_optional_memory_reference_check_disabled_keeps_rule_result(self) -> None:
        config = build_test_config(
            self.workspace.db_path,
            assist_llm_enable_memory_reference_check=False,
        )
        gateway = DummyGateway(['{"verdict":"supported","reason":"unused"}'])
        assist_service = AssistLLMService.from_app_config(config, gateway)
        guard = ReplyGuard(
            config.runtime,
            config.persona,
            config.policy,
            assist_service=assist_service,
        )
        memory_result = build_guard_case_memory_result(
            {
                "injected_memories": [
                    {
                        "id": "m-3",
                        "type": "episodic",
                        "content": "用户这两天确实比较累。",
                        "relevant": True,
                    }
                ]
            }
        )

        decision = guard.evaluate(
            reply_text="我记得你前两天挺累的，今晚稍微歇一下也正常。",
            raw_reply_text="我记得你前两天挺累的，今晚稍微歇一下也正常。",
            user_input="今晚想偷懒一下。",
            scene="casual_chat",
            memory_result=memory_result,
            allow_retry=True,
            linked_turn_id="turn-disabled",
        )

        self.assertIsNone(decision.memory_reference_verdict)
        self.assertEqual(decision.initial_action, "rewrite")
        self.assertEqual(len(gateway.calls), 0)

    def test_badcase_draft_returns_structured_payload(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(
            [
                (
                    '{"case_id":"draft_guard_001","scene":"comfort","user_input":"我今天有点撑不住。",'
                    '"injected_memories":[],"assistant_reply":"你应该立刻冷静下来。",'
                    '"observed_violations":["scene_conflict","over_preachy"],'
                    '"suggested_expected_categories":["scene_conflict","over_preachy"],'
                    '"suggested_expected_action":"retry_once","reviewer_notes":"需要人工确认 final action"}'
                )
            ]
        )
        assist_service = AssistLLMService.from_app_config(config, gateway)

        result = assist_service.draft_badcase_case(
            trace_record={
                "scene": "comfort",
                "user_input": "我今天有点撑不住。",
                "assistant_reply": "你应该立刻冷静下来。",
            },
            command_id="badcase-draft-1",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.structured["case_id"], "draft_guard_001")
        self.assertEqual(result.structured["suggested_expected_action"], "retry_once")
        self.assertIn("observed_violations", result.structured)

    def test_pending_review_note_does_not_change_write_decision(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(['{"note":"Looks like a stable address preference."}'])
        assist_service = AssistLLMService.from_app_config(config, gateway)
        memory_manager = MemoryManager.from_app_config(config)
        turn = MemoryTurnInput(
            user_input="以后还是叫我阿周吧。",
            assistant_reply="好。",
            scene="casual_chat",
            turn_id="pending-review-turn",
        )
        fixed_now = now_timestamp()
        before = memory_manager.preview_write_candidates(turn, now=fixed_now)
        self.assertTrue(before)

        note_result = assist_service.review_pending_memory_note(
            candidate_preview={
                "memory_type": before[0].memory_type,
                "content": before[0].content,
                "candidate_reason": before[0].candidate_reason,
                "summary": before[0].summary,
            },
            command_id="pending-review-1",
        )
        after = memory_manager.preview_write_candidates(turn, now=fixed_now)

        self.assertTrue(note_result.success)
        self.assertEqual(note_result.structured["note"], "Looks like a stable address preference.")
        self.assertEqual(before, after)

    def test_merge_summary_candidate_is_dropped_when_unsafe(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(['{"summary":"我觉得用户应该继续做桌面 agent memory guard 改造。"}'])
        assist_service = AssistLLMService.from_app_config(config, gateway)

        result = assist_service.summarize_episodic_merge(
            source_items=[
                "用户最近持续在做桌面 agent 的 memory guard 改造。",
                "用户说这周会继续推进 memory guard 改造。",
            ],
            fallback_summary="用户最近持续在做桌面 agent 的 memory guard 改造。",
            command_id="merge-summary-1",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.record.error_type, "UnsafeSummary")
        self.assertEqual(
            result.structured["summary"],
            "用户最近持续在做桌面 agent 的 memory guard 改造。",
        )

    def test_runtime_budget_never_exceeds_one_call_per_turn(self) -> None:
        config = build_test_config(self.workspace.db_path)
        gateway = DummyGateway(
            [
                '{"verdict":"weakly_supported","reason":"borderline"}',
                '{"revised_reply":"先别急。"}',
            ]
        )
        assist_service = AssistLLMService.from_app_config(config, gateway)

        first = assist_service.optional_memory_reference_check(
            user_input="今晚想偷懒一下。",
            reply_excerpt="我记得你前两天挺累的。",
            memory_summaries=["用户这两天确实比较累。"],
            linked_turn_id="runtime-budget-turn",
            turn_trace=None,
            pre_guard_action="memory_reference_check",
        )
        second = assist_service.guard_retry_rewrite(
            scene="casual_chat",
            user_input="今晚想偷懒一下。",
            memory_summaries=["用户这两天确实比较累。"],
            violation_categories=["unnatural_memory_reference"],
            rewrite_constraints=["Keep it natural."],
            original_reply_excerpt="我记得你前两天挺累的。",
            linked_turn_id="runtime-budget-turn",
            turn_trace=None,
            pre_guard_action="retry_once",
        )

        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertEqual(second.record.error_type, "RuntimeBudgetExceeded")
        self.assertEqual(assist_service.runtime_calls_for_turn("runtime-budget-turn"), 1)

    def test_assist_service_blocks_recursive_calls(self) -> None:
        config = build_test_config(self.workspace.db_path)
        nested_results: list[object] = []
        gateway = DummyGateway([])
        assist_service = AssistLLMService.from_app_config(config, gateway)

        def nested_call(**_kwargs):
            nested_results.append(
                assist_service.review_pending_memory_note(
                    candidate_preview={"content": "用户偏好被称呼为阿周。"},
                    command_id="nested-review",
                )
            )
            return '{"revised_reply":"先别急着硬撑。"}'

        gateway.responses.append(nested_call)
        outer = assist_service.guard_retry_rewrite(
            scene="comfort",
            user_input="我今天有点撑不住。",
            memory_summaries=[],
            violation_categories=["scene_conflict"],
            rewrite_constraints=["Keep it warm and short."],
            original_reply_excerpt="你应该立刻冷静下来。",
            linked_turn_id="recursive-turn",
            turn_trace=None,
            pre_guard_action="retry_once",
        )

        self.assertTrue(outer.success)
        self.assertEqual(len(nested_results), 1)
        nested = nested_results[0]
        self.assertFalse(nested.success)
        self.assertEqual(nested.record.error_type, "RecursiveAssistCall")


if __name__ == "__main__":
    unittest.main()
