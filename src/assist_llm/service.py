from __future__ import annotations

from collections import defaultdict
from time import monotonic
from typing import Any, Mapping, Sequence

from src.assist_llm.config import AssistLLMConfig
from src.assist_llm.models import (
    AssistLLMCallRecord,
    AssistLLMRequest,
    AssistLLMResult,
    AssistTaskType,
)
from src.assist_llm.prompts import build_input_excerpt, build_messages, parse_response
from src.assist_llm.tasks import TASK_SPECS, AssistTaskSpec
from src.config.loader import AppConfig
from src.llm.gateway import GenerationOptions, GatewayError, LLMGateway
from src.observability.trace import TurnTrace
from src.utils.logger import log_event
from src.utils.text_utils import normalize_whitespace, safe_preview


class AssistLLMService:
    def __init__(
        self,
        config: AssistLLMConfig,
        gateway: LLMGateway,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self._runtime_calls_by_turn: dict[str, int] = defaultdict(int)
        self._dev_calls_by_command: dict[str, int] = defaultdict(int)
        self._active_call_depth = 0

    @classmethod
    def from_app_config(
        cls,
        app_config: AppConfig,
        gateway: LLMGateway,
    ) -> "AssistLLMService":
        return cls(AssistLLMConfig.from_runtime(app_config.runtime), gateway)

    def can_use_runtime_task(self, turn_id: str | None) -> bool:
        if not self.config.enabled or turn_id is None:
            return False
        return self._runtime_calls_by_turn[turn_id] < self.config.max_runtime_calls_per_turn

    def runtime_calls_for_turn(self, turn_id: str | None) -> int:
        if turn_id is None:
            return 0
        return self._runtime_calls_by_turn[turn_id]

    def dev_calls_for_command(self, command_id: str | None) -> int:
        if command_id is None:
            return 0
        return self._dev_calls_by_command[command_id]

    def guard_retry_rewrite(
        self,
        *,
        scene: str,
        user_input: str,
        memory_summaries: Sequence[str],
        violation_categories: Sequence[str],
        rewrite_constraints: Sequence[str],
        original_reply_excerpt: str,
        linked_turn_id: str | None,
        turn_trace: TurnTrace | None,
        pre_guard_action: str,
    ) -> AssistLLMResult:
        return self._run(
            AssistLLMRequest(
                task="guard_retry_rewrite",
                scope="runtime",
                linked_turn_id=linked_turn_id,
                pre_guard_action=pre_guard_action,
                payload={
                    "scene": scene,
                    "user_input": user_input,
                    "memory_summaries": list(memory_summaries),
                    "violation_categories": list(violation_categories),
                    "rewrite_constraints": list(rewrite_constraints),
                    "original_reply_excerpt": original_reply_excerpt,
                },
            ),
            turn_trace=turn_trace,
        )

    def optional_memory_reference_check(
        self,
        *,
        user_input: str,
        reply_excerpt: str,
        memory_summaries: Sequence[str],
        linked_turn_id: str | None,
        turn_trace: TurnTrace | None,
        pre_guard_action: str | None = None,
    ) -> AssistLLMResult:
        return self._run(
            AssistLLMRequest(
                task="optional_memory_reference_check",
                scope="runtime",
                linked_turn_id=linked_turn_id,
                pre_guard_action=pre_guard_action,
                payload={
                    "user_input": user_input,
                    "reply_excerpt": reply_excerpt,
                    "memory_summaries": list(memory_summaries),
                },
            ),
            turn_trace=turn_trace,
        )

    def summarize_trace_cluster(
        self,
        *,
        trace_records: Sequence[str],
        command_id: str,
        turn_trace: TurnTrace | None = None,
    ) -> AssistLLMResult:
        return self._run(
            AssistLLMRequest(
                task="summarize_trace_cluster",
                scope="dev",
                command_id=command_id,
                payload={"trace_records": list(trace_records)},
            ),
            turn_trace=turn_trace,
        )

    def draft_badcase_case(
        self,
        *,
        trace_record: Mapping[str, Any],
        command_id: str,
        turn_trace: TurnTrace | None = None,
    ) -> AssistLLMResult:
        return self._run(
            AssistLLMRequest(
                task="draft_badcase_case",
                scope="dev",
                command_id=command_id,
                payload=dict(trace_record),
            ),
            turn_trace=turn_trace,
        )

    def review_pending_memory_note(
        self,
        *,
        candidate_preview: Mapping[str, Any],
        command_id: str,
        turn_trace: TurnTrace | None = None,
    ) -> AssistLLMResult:
        return self._run(
            AssistLLMRequest(
                task="review_pending_memory_note",
                scope="dev",
                command_id=command_id,
                payload=dict(candidate_preview),
            ),
            turn_trace=turn_trace,
        )

    def summarize_episodic_merge(
        self,
        *,
        source_items: Sequence[str],
        fallback_summary: str,
        command_id: str,
        turn_trace: TurnTrace | None = None,
    ) -> AssistLLMResult:
        result = self._run(
            AssistLLMRequest(
                task="summarize_episodic_merge",
                scope="dev",
                command_id=command_id,
                payload={
                    "source_items": list(source_items),
                    "fallback_summary": fallback_summary,
                },
            ),
            turn_trace=turn_trace,
        )
        if not result.success:
            return result

        summary = normalize_whitespace(result.structured.get("summary", "") or "")
        if not self._is_summary_safe(summary, source_items):
            return self._fallback_result(
                task="summarize_episodic_merge",
                linked_turn_id=None,
                timeout_ms=self.config.timeout_ms,
                input_excerpt=build_input_excerpt(
                    {
                        "source_items": list(source_items),
                        "fallback_summary": fallback_summary,
                    }
                ),
                output_excerpt=safe_preview(summary, 120),
                model=self.config.dev_model,
                runtime_call_used=False,
                error_type="UnsafeSummary",
                fallback_text=fallback_summary,
            )
        return result

    def _run(
        self,
        request: AssistLLMRequest,
        *,
        turn_trace: TurnTrace | None,
    ) -> AssistLLMResult:
        spec = TASK_SPECS[request.task]
        input_excerpt = build_input_excerpt(request.payload)

        if not self.config.enabled or not getattr(self.config, spec.enabled_flag):
            return self._fallback_result(
                task=request.task,
                linked_turn_id=request.linked_turn_id,
                timeout_ms=self.config.timeout_ms,
                input_excerpt=input_excerpt,
                output_excerpt=None,
                model=self._select_model(spec),
                runtime_call_used=self._runtime_used_flag(request),
                error_type="AssistDisabled",
                pre_guard_action=request.pre_guard_action,
                post_guard_action=request.post_guard_action,
            )

        if self._active_call_depth > 0:
            return self._fallback_result(
                task=request.task,
                linked_turn_id=request.linked_turn_id,
                timeout_ms=self.config.timeout_ms,
                input_excerpt=input_excerpt,
                output_excerpt=None,
                model=self._select_model(spec),
                runtime_call_used=self._runtime_used_flag(request),
                error_type="RecursiveAssistCall",
                pre_guard_action=request.pre_guard_action,
                post_guard_action=request.post_guard_action,
            )

        budget_error = self._consume_budget(request, spec)
        if budget_error is not None:
            return self._fallback_result(
                task=request.task,
                linked_turn_id=request.linked_turn_id,
                timeout_ms=self.config.timeout_ms,
                input_excerpt=input_excerpt,
                output_excerpt=None,
                model=self._select_model(spec),
                runtime_call_used=self._runtime_used_flag(request),
                error_type=budget_error,
                pre_guard_action=request.pre_guard_action,
                post_guard_action=request.post_guard_action,
            )

        model_name = self._select_model(spec)
        started_at = monotonic()
        log_event(
            "assist_llm_call_started",
            level="DEBUG",
            turn_trace=turn_trace,
            assist_llm_task=request.task,
            assist_llm_enabled=True,
            assist_llm_model=model_name,
            assist_llm_timeout_ms=self.config.timeout_ms,
            assist_llm_runtime_call_used=self._runtime_used_flag(request),
            assist_llm_input_excerpt=input_excerpt,
            assist_llm_trace_linked_turn_id=request.linked_turn_id,
            assist_llm_pre_guard_action=request.pre_guard_action,
            assist_llm_post_guard_action=request.post_guard_action,
        )

        self._active_call_depth += 1
        try:
            gateway_response = self.gateway.generate(
                build_messages(request),
                turn_trace=turn_trace,
                options=GenerationOptions(
                    temperature=spec.temperature,
                    max_tokens=spec.max_tokens,
                    model_override=model_name,
                    timeout_seconds=self.config.timeout_ms / 1000.0,
                    request_tag=spec.request_tag,
                ),
            )
            text, structured = parse_response(request.task, gateway_response.text)
        except (GatewayError, ValueError) as exc:
            duration_ms = int((monotonic() - started_at) * 1000)
            result = self._fallback_result(
                task=request.task,
                linked_turn_id=request.linked_turn_id,
                timeout_ms=self.config.timeout_ms,
                input_excerpt=input_excerpt,
                output_excerpt=None,
                model=model_name,
                runtime_call_used=self._runtime_used_flag(request),
                error_type=type(exc).__name__,
                duration_ms=duration_ms,
                pre_guard_action=request.pre_guard_action,
                post_guard_action=request.post_guard_action,
            )
            log_event(
                "assist_llm_call_failed",
                level="WARNING",
                turn_trace=turn_trace,
                **result.record.as_log_fields(),
            )
            return result
        finally:
            self._active_call_depth -= 1

        duration_ms = int((monotonic() - started_at) * 1000)
        record = AssistLLMCallRecord(
            task=request.task,
            enabled=True,
            model=model_name,
            timeout_ms=self.config.timeout_ms,
            runtime_call_used=self._runtime_used_flag(request),
            input_excerpt=input_excerpt,
            output_excerpt=safe_preview(text or gateway_response.text, 160),
            duration_ms=duration_ms,
            success=True,
            fallback_to_rules=False,
            error_type=None,
            trace_linked_turn_id=request.linked_turn_id,
            pre_guard_action=request.pre_guard_action,
            post_guard_action=request.post_guard_action,
        )
        result = AssistLLMResult(
            task=request.task,
            success=True,
            record=record,
            text=text,
            structured=structured,
        )
        log_event(
            "assist_llm_call_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            **record.as_log_fields(),
        )
        return result

    def _consume_budget(
        self,
        request: AssistLLMRequest,
        spec: AssistTaskSpec,
    ) -> str | None:
        if spec.scope == "runtime":
            if request.linked_turn_id is None:
                return "MissingTurnId"
            if (
                self._runtime_calls_by_turn[request.linked_turn_id]
                >= self.config.max_runtime_calls_per_turn
            ):
                return "RuntimeBudgetExceeded"
            self._runtime_calls_by_turn[request.linked_turn_id] += 1
            return None

        command_id = request.command_id or request.linked_turn_id or request.task
        if self._dev_calls_by_command[command_id] >= self.config.max_dev_calls_per_command:
            return "DevBudgetExceeded"
        self._dev_calls_by_command[command_id] += 1
        return None

    def _select_model(self, spec: AssistTaskSpec) -> str:
        return self.config.runtime_model if spec.scope == "runtime" else self.config.dev_model

    def _runtime_used_flag(self, request: AssistLLMRequest) -> bool:
        if request.linked_turn_id is None:
            return False
        return self._runtime_calls_by_turn[request.linked_turn_id] > 0

    def _fallback_result(
        self,
        *,
        task: AssistTaskType,
        linked_turn_id: str | None,
        timeout_ms: int,
        input_excerpt: str | None,
        output_excerpt: str | None,
        model: str | None,
        runtime_call_used: bool,
        error_type: str,
        duration_ms: int = 0,
        fallback_text: str | None = None,
        pre_guard_action: str | None = None,
        post_guard_action: str | None = None,
    ) -> AssistLLMResult:
        record = AssistLLMCallRecord(
            task=task,
            enabled=self.config.enabled,
            model=model,
            timeout_ms=timeout_ms,
            runtime_call_used=runtime_call_used,
            input_excerpt=input_excerpt,
            output_excerpt=output_excerpt,
            duration_ms=duration_ms,
            success=False,
            fallback_to_rules=True,
            error_type=error_type,
            trace_linked_turn_id=linked_turn_id,
            pre_guard_action=pre_guard_action,
            post_guard_action=post_guard_action,
        )
        structured: dict[str, Any] = {}
        if task == "summarize_episodic_merge" and fallback_text is not None:
            structured["summary"] = fallback_text
        if task == "review_pending_memory_note" and fallback_text is not None:
            structured["note"] = fallback_text
        return AssistLLMResult(
            task=task,
            success=False,
            record=record,
            text=fallback_text,
            structured=structured,
        )

    def _is_summary_safe(self, summary: str, source_items: Sequence[str]) -> bool:
        normalized = normalize_whitespace(summary)
        if not normalized or len(normalized) > 80:
            return False
        if any(
            marker in normalized
            for marker in (
                "我觉得",
                "应该",
                "说明",
                "因此",
                "because",
                "suggests",
                "probably",
            )
        ):
            return False
        source_blob = " ".join(source_items)
        source_tokens = {
            token for token in _extract_brief_tokens(source_blob) if len(token) >= 2
        }
        summary_tokens = [
            token for token in _extract_brief_tokens(normalized) if len(token) >= 2
        ]
        unsupported = [
            token for token in summary_tokens if token not in source_tokens and not token.isdigit()
        ]
        return len(unsupported) <= 1


def _extract_brief_tokens(text: str) -> set[str]:
    import re

    tokens = set(re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,6}", normalize_whitespace(text)))
    return {token for token in tokens if token.strip()}
