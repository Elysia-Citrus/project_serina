from __future__ import annotations

from src.config.loader import PersonaConfig, PolicyConfig, RuntimeConfig
from src.dialogue.reply_guard.actions import (
    build_accept_decision,
    build_fallback_decision,
    build_rewrite_decision,
    build_retry_decision,
)
from src.dialogue.reply_guard.checks import run_checks
from src.dialogue.reply_guard.classify import classify_violations
from src.dialogue.reply_guard.models import ReplyGuardContext, ReplyGuardDecision


class ReplyGuard:
    def __init__(
        self,
        runtime: RuntimeConfig,
        persona: PersonaConfig,
        policy: PolicyConfig,
    ) -> None:
        self.runtime = runtime
        self.persona = persona
        self.policy = policy

    def evaluate(
        self,
        *,
        reply_text: str,
        user_input: str,
        scene: str,
        memory_result,
        allow_retry: bool,
        raw_reply_text: str | None = None,
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
        assessment = classify_violations(
            violations,
            scene=scene,
            retry_enabled=allow_retry and self.runtime.reply_guard_retry_once,
        )

        if assessment.suggested_action == "accept":
            return build_accept_decision(assessment, context, violations)
        if assessment.suggested_action == "rewrite":
            return build_rewrite_decision(assessment, context, violations)
        if assessment.suggested_action == "retry_once":
            return build_retry_decision(assessment, context, violations)
        return build_fallback_decision(assessment, context, violations)
