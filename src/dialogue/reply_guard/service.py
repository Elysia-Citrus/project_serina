from __future__ import annotations

from src.assist_llm import AssistLLMCallRecord, AssistLLMService
from src.dialogue.reply_guard.actions import (
    build_accept_decision,
    build_fallback_decision,
    build_rewrite_decision,
    build_retry_decision,
)
from src.dialogue.reply_guard.checks import run_checks
from src.dialogue.reply_guard.classify import classify_violations
from src.dialogue.reply_guard.models import (
    ReplyGuardContext,
    ReplyGuardDecision,
    ReplyViolation,
)
from src.memory.models import MemoryReadResult
from src.observability.trace import TurnTrace
from src.utils.text_utils import safe_preview


class ReplyGuard:
    def __init__(
        self,
        runtime,
        persona,
        policy,
        assist_service: AssistLLMService | None = None,
    ) -> None:
        self.runtime = runtime
        self.persona = persona
        self.policy = policy
        self.assist_service = assist_service

    def evaluate(
        self,
        *,
        reply_text: str,
        user_input: str,
        scene: str,
        memory_result: MemoryReadResult,
        allow_retry: bool,
        raw_reply_text: str | None = None,
        turn_trace: TurnTrace | None = None,
        linked_turn_id: str | None = None,
    ) -> ReplyGuardDecision:
        context = ReplyGuardContext(
            reply_text=reply_text,
            raw_reply_text=raw_reply_text or reply_text,
            user_input=user_input,
            scene=scene,
            memory_result=memory_result,
            runtime=self.runtime,
            persona=self.persona,
            policy=self.policy,
        )

        if not self.runtime.reply_guard_enabled:
            assessment = classify_violations((), scene=scene, retry_enabled=False)
            return build_accept_decision(assessment, context)

        violations = run_checks(context)
        violations, memory_reference_verdict, assist_record = (
            self._maybe_apply_memory_reference_assist(
                context=context,
                violations=violations,
                turn_trace=turn_trace,
                linked_turn_id=linked_turn_id,
            )
        )

        assessment = classify_violations(
            violations,
            scene=scene,
            retry_enabled=allow_retry and self.runtime.reply_guard_retry_once,
        )

        if assessment.suggested_action == "accept":
            decision = build_accept_decision(assessment, context, violations)
        elif assessment.suggested_action == "rewrite":
            decision = build_rewrite_decision(assessment, context, violations)
        elif assessment.suggested_action == "retry_once":
            decision = build_retry_decision(assessment, context, violations)
        else:
            decision = build_fallback_decision(assessment, context, violations)

        return self._attach_assist_metadata(
            decision,
            memory_reference_verdict=memory_reference_verdict,
            assist_record=assist_record,
        )

    def _maybe_apply_memory_reference_assist(
        self,
        *,
        context: ReplyGuardContext,
        violations: tuple[ReplyViolation, ...],
        turn_trace: TurnTrace | None,
        linked_turn_id: str | None,
    ) -> tuple[
        tuple[ReplyViolation, ...],
        str | None,
        AssistLLMCallRecord | None,
    ]:
        if self.assist_service is None:
            return violations, None, None
        if not self.runtime.assist_llm_enable_memory_reference_check:
            return violations, None, None
        if linked_turn_id is None:
            return violations, None, None
        if not self.assist_service.can_use_runtime_task(linked_turn_id):
            return violations, None, None
        if not context.memory_result.selected_items:
            return violations, None, None

        categories = {violation.category for violation in violations}
        if "unnatural_memory_reference" not in categories:
            return violations, None, None
        if any(
            violation.category == "fake_memory_claim" and violation.severity == "severe"
            for violation in violations
        ):
            return violations, None, None

        assist_result = self.assist_service.optional_memory_reference_check(
            user_input=context.user_input,
            reply_excerpt=safe_preview(context.reply_text, 120),
            memory_summaries=[
                item.display_text() for item in context.memory_result.selected_items[:3]
            ],
            linked_turn_id=linked_turn_id,
            turn_trace=turn_trace,
            pre_guard_action="memory_reference_check",
        )
        verdict = assist_result.verdict if assist_result.success else None
        if verdict != "unsupported":
            return violations, verdict, assist_result.record

        if "fake_memory_claim" in categories:
            return violations, verdict, assist_result.record

        escalated = list(violations)
        escalated.append(
            ReplyViolation(
                rule_id="fake_memory_claim.assist_unsupported",
                category="fake_memory_claim",
                severity="medium",
                message="Assist lane judged the memory reference unsupported.",
                evidence_excerpt=safe_preview(context.reply_text, 72),
                should_block=True,
                can_rewrite=False,
                metadata={"assist_memory_verdict": verdict},
            )
        )
        return tuple(escalated), verdict, assist_result.record

    def _attach_assist_metadata(
        self,
        decision: ReplyGuardDecision,
        *,
        memory_reference_verdict: str | None,
        assist_record: AssistLLMCallRecord | None,
    ) -> ReplyGuardDecision:
        return ReplyGuardDecision(
            initial_action=decision.initial_action,
            final_action=decision.final_action,
            final_text=decision.final_text,
            violations=decision.violations,
            assessment=decision.assessment,
            retry_instructions=decision.retry_instructions,
            rewrite_used=decision.rewrite_used,
            retry_used=decision.retry_used,
            fallback_reason=decision.fallback_reason,
            memory_refs_checked=decision.memory_refs_checked,
            memory_reference_verdict=memory_reference_verdict,
            assist_record=assist_record,
        )
