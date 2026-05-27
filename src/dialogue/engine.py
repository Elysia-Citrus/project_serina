from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from src.assist_llm import AssistLLMCallRecord, AssistLLMService
from src.config.loader import AppConfig
from src.dialogue.postprocess import PostprocessResult, postprocess_response
from src.dialogue.prompt_builder import (
    PromptMetadata,
    build_prompt_package,
    infer_scene,
)
from src.dialogue.reply_guard import ReplyGuard, ReplyGuardDecision
from src.dialogue.reply_guard.actions import build_fallback_decision
from src.dialogue.reply_guard.models import ReplyGuardContext
from src.llm.gateway import GenerationOptions, GatewayResponse, LLMGateway
from src.memory.manager import MemoryManager
from src.memory.models import MemoryReadResult
from src.observability.trace import TurnTrace
from src.utils.logger import get_logger, log_event
from src.utils.text_utils import safe_preview
from src.utils.time_utils import TimeContext


@dataclass(frozen=True)
class DialogueResult:
    reply_text: str
    scene: str
    raw_response: str
    request_latency_ms: int
    provider_name: str
    model_name: str
    prompt_metadata: PromptMetadata
    postprocess: PostprocessResult
    memory_result: MemoryReadResult
    reply_guard_action: str
    reply_guard_initial_action: str
    reply_guard_final_action: str
    reply_guard_initial_violations: tuple[str, ...]
    reply_guard_retry_attempted: bool
    reply_guard_retry_used: bool
    reply_guard_rewrite_used: bool
    reply_guard_fallback_reason: str | None
    reply_guard_scene: str
    reply_guard_memory_refs_checked: tuple[str, ...]
    reply_guard_case_like_signature: str | None
    reply_guard_violations: tuple[str, ...]
    reply_guard_memory_reference_verdict: str | None
    time_context_summary: str | None = None
    assist_llm_record: AssistLLMCallRecord | None = None
    proactive_followup_candidate: None = None


class DialogueEngine:
    def __init__(
        self,
        config: AppConfig,
        gateway: LLMGateway,
        memory_manager: MemoryManager | None = None,
        reply_guard: ReplyGuard | None = None,
        assist_service: AssistLLMService | None = None,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.assist_service = assist_service or AssistLLMService.from_app_config(
            config,
            gateway,
        )
        self.memory_manager = memory_manager or MemoryManager.from_app_config(config)
        self.reply_guard = reply_guard or ReplyGuard(
            config.runtime,
            config.persona,
            config.policy,
            assist_service=self.assist_service,
        )
        self.logger = get_logger(__name__)

    def generate_reply(
        self,
        user_input: str,
        conversation_history: Sequence[Mapping[str, str]],
        session_id: str | None = None,
        session_turn_index: int | None = None,
        memory_snippets: Sequence[str] | None = None,
        turn_trace: TurnTrace | None = None,
        time_context: TimeContext | None = None,
    ) -> DialogueResult:
        if turn_trace is not None:
            turn_trace.set_model(self.config.runtime.model)

        log_event(
            "dialogue_started",
            level="DEBUG",
            turn_trace=turn_trace,
            history_message_count=len(conversation_history),
        )

        scene = infer_scene(user_input)
        if turn_trace is not None:
            turn_trace.set_scene(scene)
        log_event(
            "scene_inferred",
            level="DEBUG",
            turn_trace=turn_trace,
            scene=scene,
        )

        memory_result = self._resolve_memory_context(
            user_input=user_input,
            scene=scene,
            session_id=session_id,
            session_turn_index=session_turn_index,
            memory_snippets=memory_snippets,
            turn_trace=turn_trace,
        )
        if time_context is not None:
            memory_time_summary = self.memory_manager.summarize_memory_time_context(
                memory_result.session_selected_items + memory_result.selected_items
            )
            time_context = replace(
                time_context,
                memory_time_summary=memory_time_summary,
            )

        prompt_package = build_prompt_package(
            user_input=user_input,
            conversation_history=conversation_history,
            persona=self.config.persona,
            policy=self.config.policy,
            memory_snippets=memory_result.prompt_items,
            continuing_context_snippets=memory_result.startup_prompt_items,
            scene_override=scene,
            preview_chars=self.config.runtime.debug_max_preview_chars,
            time_context=time_context,
        )
        self._log_prompt_package(prompt_package.metadata, turn_trace=turn_trace)

        primary_response = self.gateway.generate(
            prompt_package.messages,
            turn_trace=turn_trace,
            options=GenerationOptions(request_tag="primary"),
        )
        total_latency_ms = primary_response.latency_ms

        (
            final_reply_text,
            raw_response,
            provider_name,
            model_name,
            postprocess_result,
            prompt_metadata,
            reply_guard_decision,
            reply_guard_initial_action,
            reply_guard_initial_violations,
            reply_guard_retry_attempted,
            assist_llm_record,
            total_latency_ms,
        ) = self._apply_guardrail_pipeline(
            user_input=user_input,
            scene=scene,
            conversation_history=conversation_history,
            memory_result=memory_result,
            prompt_metadata=prompt_package.metadata,
            initial_response=primary_response,
            turn_trace=turn_trace,
            total_latency_ms=total_latency_ms,
        )

        if turn_trace is not None:
            turn_trace.set_request_latency(total_latency_ms)
            turn_trace.set_response_preview(raw_response)
            turn_trace.set_postprocessed_response_preview(final_reply_text)

        result = DialogueResult(
            reply_text=final_reply_text,
            scene=scene,
            raw_response=raw_response,
            request_latency_ms=total_latency_ms,
            provider_name=provider_name,
            model_name=model_name,
            prompt_metadata=prompt_metadata,
            postprocess=postprocess_result,
            memory_result=memory_result,
            reply_guard_action=reply_guard_decision.action,
            reply_guard_initial_action=reply_guard_initial_action,
            reply_guard_final_action=reply_guard_decision.final_action,
            reply_guard_initial_violations=reply_guard_initial_violations,
            reply_guard_retry_attempted=reply_guard_retry_attempted,
            reply_guard_retry_used=reply_guard_retry_attempted,
            reply_guard_rewrite_used=reply_guard_decision.rewrite_used,
            reply_guard_fallback_reason=reply_guard_decision.fallback_reason,
            reply_guard_scene=scene,
            reply_guard_memory_refs_checked=reply_guard_decision.memory_refs_checked,
            reply_guard_case_like_signature=(
                reply_guard_decision.assessment.case_like_signature
                if reply_guard_decision.assessment is not None
                else None
            ),
            reply_guard_violations=reply_guard_decision.violation_codes,
            reply_guard_memory_reference_verdict=(
                reply_guard_decision.memory_reference_verdict
            ),
            time_context_summary=prompt_metadata.time_context_summary,
            assist_llm_record=assist_llm_record or reply_guard_decision.assist_record,
        )
        log_event(
            "dialogue_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            reply_guard_action=result.reply_guard_action,
            reply_guard_initial_action=result.reply_guard_initial_action,
            reply_guard_final_action=result.reply_guard_final_action,
            reply_guard_initial_violations=result.reply_guard_initial_violations,
            reply_guard_retry_attempted=result.reply_guard_retry_attempted,
            reply_guard_retry_used=result.reply_guard_retry_used,
            reply_guard_rewrite_used=result.reply_guard_rewrite_used,
            reply_guard_fallback_reason=result.reply_guard_fallback_reason,
            reply_guard_scene=result.reply_guard_scene,
            reply_guard_memory_refs_checked=result.reply_guard_memory_refs_checked,
            reply_guard_case_like_signature=result.reply_guard_case_like_signature,
            reply_guard_violations=result.reply_guard_violations,
            reply_guard_memory_reference_verdict=result.reply_guard_memory_reference_verdict,
            time_context_summary=result.time_context_summary,
            proactive_followup_candidate_present=result.proactive_followup_candidate
            is not None,
            **(
                result.assist_llm_record.as_log_fields()
                if result.assist_llm_record is not None
                else {}
            ),
        )
        return result

    def _resolve_memory_context(
        self,
        *,
        user_input: str,
        scene: str,
        session_id: str | None,
        session_turn_index: int | None,
        memory_snippets: Sequence[str] | None,
        turn_trace: TurnTrace | None,
    ) -> MemoryReadResult:
        if memory_snippets is not None:
            return MemoryReadResult(prompt_items=tuple(memory_snippets))
        return self.memory_manager.retrieve(
            user_input=user_input,
            scene=scene,
            session_id=session_id,
            session_turn_index=session_turn_index,
            turn_trace=turn_trace,
        )

    def _apply_guardrail_pipeline(
        self,
        *,
        user_input: str,
        scene: str,
        conversation_history: Sequence[Mapping[str, str]],
        memory_result: MemoryReadResult,
        prompt_metadata: PromptMetadata,
        initial_response: GatewayResponse,
        turn_trace: TurnTrace | None,
        total_latency_ms: int,
    ) -> tuple[
        str,
        str,
        str,
        str,
        PostprocessResult,
        PromptMetadata,
        ReplyGuardDecision,
        str,
        tuple[str, ...],
        bool,
        AssistLLMCallRecord | None,
        int,
    ]:
        postprocess_result = self._postprocess_response(
            initial_response.text,
            turn_trace=turn_trace,
        )
        linked_turn_id = turn_trace.turn_id if turn_trace is not None else None
        reply_guard_decision = self.reply_guard.evaluate(
            reply_text=postprocess_result.final_text,
            raw_reply_text=initial_response.text,
            user_input=user_input,
            scene=scene,
            memory_result=memory_result,
            allow_retry=True,
            turn_trace=turn_trace,
            linked_turn_id=linked_turn_id,
        )
        self._log_guard_decision(
            event_name="reply_guard_checked",
            decision=reply_guard_decision,
            turn_trace=turn_trace,
        )

        if reply_guard_decision.initial_action == "accept":
            return (
                reply_guard_decision.final_text or postprocess_result.final_text,
                initial_response.text,
                initial_response.provider_name,
                initial_response.model_name,
                postprocess_result,
                prompt_metadata,
                reply_guard_decision,
                reply_guard_decision.initial_action,
                reply_guard_decision.violation_codes,
                False,
                reply_guard_decision.assist_record,
                total_latency_ms,
            )

        if (
            reply_guard_decision.initial_action == "rewrite"
            and reply_guard_decision.final_text is not None
        ):
            return (
                reply_guard_decision.final_text,
                initial_response.text,
                initial_response.provider_name,
                initial_response.model_name,
                postprocess_result,
                prompt_metadata,
                reply_guard_decision,
                reply_guard_decision.initial_action,
                reply_guard_decision.violation_codes,
                False,
                reply_guard_decision.assist_record,
                total_latency_ms,
            )

        if reply_guard_decision.initial_action == "retry_once":
            assist_result = self._maybe_run_assist_retry(
                user_input=user_input,
                scene=scene,
                memory_result=memory_result,
                reply_guard_decision=reply_guard_decision,
                original_reply=postprocess_result.final_text,
                linked_turn_id=linked_turn_id,
                turn_trace=turn_trace,
            )
            if assist_result is not None:
                assist_record = assist_result.record
                if not assist_result.success or not assist_result.text:
                    fallback_decision = self._build_retry_fallback_decision(
                        user_input=user_input,
                        scene=scene,
                        memory_result=memory_result,
                        reply_guard_decision=reply_guard_decision,
                        original_reply=postprocess_result.final_text,
                        raw_reply_text=initial_response.text,
                        reason=assist_record.error_type or "assist_retry_failed",
                    )
                    fallback_decision = self._with_assist_metadata(
                        fallback_decision,
                        assist_record=assist_record,
                    )
                    self._log_guard_decision(
                        event_name="reply_guard_assist_retry_completed",
                        decision=fallback_decision,
                        turn_trace=turn_trace,
                    )
                    return (
                        fallback_decision.final_text or postprocess_result.final_text,
                        initial_response.text,
                        initial_response.provider_name,
                        initial_response.model_name,
                        postprocess_result,
                        prompt_metadata,
                        fallback_decision,
                        reply_guard_decision.initial_action,
                        reply_guard_decision.violation_codes,
                        True,
                        assist_record,
                        total_latency_ms,
                    )

                assist_postprocess = self._postprocess_response(
                    assist_result.text,
                    turn_trace=turn_trace,
                )
                second_decision = self.reply_guard.evaluate(
                    reply_text=assist_postprocess.final_text,
                    raw_reply_text=assist_result.text,
                    user_input=user_input,
                    scene=scene,
                    memory_result=memory_result,
                    allow_retry=False,
                    turn_trace=turn_trace,
                    linked_turn_id=linked_turn_id,
                )
                assist_record = assist_result.record.with_post_guard_action(
                    second_decision.final_action
                )
                if second_decision.final_action != "accept":
                    second_decision = self._with_assist_metadata(
                        second_decision,
                        assist_record=assist_record,
                    )
                self._log_guard_decision(
                    event_name="reply_guard_assist_retry_completed",
                    decision=self._with_assist_metadata(
                        second_decision,
                        assist_record=assist_record,
                    ),
                    turn_trace=turn_trace,
                )
                return (
                    second_decision.final_text or assist_postprocess.final_text,
                    assist_result.text,
                    self.config.runtime.provider,
                    assist_record.model or initial_response.model_name,
                    assist_postprocess,
                    prompt_metadata,
                    self._with_assist_metadata(
                        second_decision,
                        assist_record=assist_record,
                    ),
                    reply_guard_decision.initial_action,
                    reply_guard_decision.violation_codes,
                    True,
                    assist_record,
                    total_latency_ms + assist_record.duration_ms,
                )

            retry_prompt_package = build_prompt_package(
                user_input=user_input,
                conversation_history=conversation_history,
                persona=self.config.persona,
                policy=self.config.policy,
                memory_snippets=memory_result.prompt_items,
                continuing_context_snippets=memory_result.startup_prompt_items,
                scene_override=scene,
                extra_guardrails=reply_guard_decision.retry_instructions,
                preview_chars=self.config.runtime.debug_max_preview_chars,
            )
            self._log_prompt_package(
                retry_prompt_package.metadata,
                turn_trace=turn_trace,
                event_name="reply_guard_retry_prompt_built",
            )
            log_event(
                "reply_guard_retry_started",
                level="DEBUG",
                turn_trace=turn_trace,
                reply_guard_violations=reply_guard_decision.violation_codes,
            )
            retry_response = self.gateway.generate(
                retry_prompt_package.messages,
                turn_trace=turn_trace,
                options=GenerationOptions(
                    temperature=min(self.config.runtime.temperature, 0.35),
                    max_tokens=min(
                        self.config.runtime.max_tokens,
                        max(
                            96,
                            getattr(
                                self.config.runtime,
                                "max_reply_chars_soft_limit",
                                self.config.runtime.max_reply_chars,
                            ),
                        ),
                    ),
                    request_tag="reply_guard_retry",
                ),
            )
            total_latency_ms += retry_response.latency_ms
            retry_postprocess = self._postprocess_response(
                retry_response.text,
                turn_trace=turn_trace,
            )
            second_decision = self.reply_guard.evaluate(
                reply_text=retry_postprocess.final_text,
                raw_reply_text=retry_response.text,
                user_input=user_input,
                scene=scene,
                memory_result=memory_result,
                allow_retry=False,
                turn_trace=turn_trace,
                linked_turn_id=linked_turn_id,
            )
            self._log_guard_decision(
                event_name="reply_guard_retry_completed",
                decision=second_decision,
                turn_trace=turn_trace,
                initial_action=reply_guard_decision.initial_action,
            )
            return (
                second_decision.final_text or retry_postprocess.final_text,
                retry_response.text,
                retry_response.provider_name,
                retry_response.model_name,
                retry_postprocess,
                retry_prompt_package.metadata,
                second_decision,
                reply_guard_decision.initial_action,
                reply_guard_decision.violation_codes,
                True,
                second_decision.assist_record or reply_guard_decision.assist_record,
                total_latency_ms,
            )

        return (
            reply_guard_decision.final_text or postprocess_result.final_text,
            initial_response.text,
            initial_response.provider_name,
            initial_response.model_name,
            postprocess_result,
            prompt_metadata,
            reply_guard_decision,
            reply_guard_decision.initial_action,
            reply_guard_decision.violation_codes,
            False,
            reply_guard_decision.assist_record,
            total_latency_ms,
        )

    def _maybe_run_assist_retry(
        self,
        *,
        user_input: str,
        scene: str,
        memory_result: MemoryReadResult,
        reply_guard_decision: ReplyGuardDecision,
        original_reply: str,
        linked_turn_id: str | None,
        turn_trace: TurnTrace | None,
    ):
        if self.assist_service is None:
            return None
        if not self.config.runtime.reply_guard_retry_once:
            return None
        if not self.config.runtime.assist_llm_enable_guard_retry_rewrite:
            return None
        if linked_turn_id is None:
            return None
        if not self.assist_service.can_use_runtime_task(linked_turn_id):
            return None
        return self.assist_service.guard_retry_rewrite(
            scene=scene,
            user_input=user_input,
            memory_summaries=[
                item.display_text() for item in memory_result.selected_items[:3]
            ],
            violation_categories=reply_guard_decision.violation_codes,
            rewrite_constraints=reply_guard_decision.retry_instructions,
            original_reply_excerpt=safe_preview(original_reply, 160),
            linked_turn_id=linked_turn_id,
            turn_trace=turn_trace,
            pre_guard_action=reply_guard_decision.initial_action,
        )

    def _build_retry_fallback_decision(
        self,
        *,
        user_input: str,
        scene: str,
        memory_result: MemoryReadResult,
        reply_guard_decision: ReplyGuardDecision,
        original_reply: str,
        raw_reply_text: str,
        reason: str,
    ) -> ReplyGuardDecision:
        context = ReplyGuardContext(
            reply_text=original_reply,
            raw_reply_text=raw_reply_text,
            user_input=user_input,
            scene=scene,
            memory_result=memory_result,
            runtime=self.config.runtime,
            persona=self.config.persona,
            policy=self.config.policy,
        )
        return build_fallback_decision(
            reply_guard_decision.assessment,
            context,
            reply_guard_decision.violations,
            reason=f"assist_retry_{reason}",
        )

    def _with_assist_metadata(
        self,
        decision: ReplyGuardDecision,
        *,
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
            memory_reference_verdict=decision.memory_reference_verdict,
            assist_record=assist_record,
        )

    def _postprocess_response(
        self,
        raw_response: str,
        *,
        turn_trace: TurnTrace | None,
    ) -> PostprocessResult:
        result = postprocess_response(
            raw_response,
            fallback_text=f"{self.config.persona.user_name}，我在。",
            preview_chars=self.config.runtime.debug_max_preview_chars,
        )
        log_event(
            "postprocess_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            applied_rules=result.applied_rules,
            used_fallback=result.used_fallback,
        )
        return result

    def _log_prompt_package(
        self,
        metadata: PromptMetadata,
        *,
        turn_trace: TurnTrace | None,
        event_name: str = "prompt_package_built",
    ) -> None:
        log_event(
            event_name,
            level="DEBUG",
            turn_trace=turn_trace,
            prompt_block_count=len(metadata.prompt_blocks),
            message_count=len(metadata.message_summaries),
            system_prompt_char_count=metadata.system_prompt_char_count,
            total_message_char_count=metadata.total_message_char_count,
            continuing_context_summary=metadata.continuing_context_summary,
            memory_context_summary=metadata.memory_context_summary,
            time_context_summary=metadata.time_context_summary,
        )

        if self.config.runtime.debug_show_prompt_blocks:
            log_event(
                "prompt_blocks_summary",
                level="DEBUG",
                turn_trace=turn_trace,
                prompt_blocks=[
                    {
                        "name": block.name,
                        "char_count": block.char_count,
                        "preview": block.preview,
                    }
                    for block in metadata.prompt_blocks
                ],
            )
        if self.config.runtime.debug_show_messages:
            log_event(
                "prompt_messages_summary",
                level="DEBUG",
                turn_trace=turn_trace,
                messages=[
                    {
                        "role": message.role,
                        "char_count": message.char_count,
                        "preview": message.preview,
                    }
                    for message in metadata.message_summaries
                ],
            )

    def _log_guard_decision(
        self,
        *,
        event_name: str,
        decision: ReplyGuardDecision,
        turn_trace: TurnTrace | None,
        initial_action: str | None = None,
    ) -> None:
        log_event(
            event_name,
            level="DEBUG",
            turn_trace=turn_trace,
            reply_guard_action=decision.action,
            reply_guard_initial_action=initial_action or decision.initial_action,
            reply_guard_final_action=decision.final_action,
            reply_guard_triggered=decision.triggered,
            reply_guard_violations=decision.violation_codes,
            reply_guard_rewrite_used=decision.rewrite_used,
            reply_guard_fallback_reason=decision.fallback_reason,
            reply_guard_memory_refs_checked=decision.memory_refs_checked,
            reply_guard_case_like_signature=(
                decision.assessment.case_like_signature
                if decision.assessment is not None
                else None
            ),
            reply_guard_memory_reference_verdict=decision.memory_reference_verdict,
            **(
                decision.assist_record.as_log_fields()
                if decision.assist_record is not None
                else {}
            ),
        )
