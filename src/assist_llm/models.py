from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AssistTaskType = Literal[
    "summarize_trace_cluster",
    "draft_badcase_case",
    "review_pending_memory_note",
    "summarize_episodic_merge",
    "guard_retry_rewrite",
    "optional_memory_reference_check",
]
AssistTaskScope = Literal["dev", "runtime"]
MemoryReferenceVerdict = Literal["supported", "weakly_supported", "unsupported"]


@dataclass(frozen=True)
class AssistLLMRequest:
    task: AssistTaskType
    payload: dict[str, Any]
    scope: AssistTaskScope
    linked_turn_id: str | None = None
    command_id: str | None = None
    pre_guard_action: str | None = None
    post_guard_action: str | None = None


@dataclass(frozen=True)
class AssistLLMCallRecord:
    task: AssistTaskType
    enabled: bool
    model: str | None
    timeout_ms: int
    runtime_call_used: bool
    input_excerpt: str | None
    output_excerpt: str | None
    duration_ms: int
    success: bool
    fallback_to_rules: bool
    error_type: str | None
    trace_linked_turn_id: str | None
    pre_guard_action: str | None = None
    post_guard_action: str | None = None

    def with_post_guard_action(self, action: str | None) -> "AssistLLMCallRecord":
        return AssistLLMCallRecord(
            task=self.task,
            enabled=self.enabled,
            model=self.model,
            timeout_ms=self.timeout_ms,
            runtime_call_used=self.runtime_call_used,
            input_excerpt=self.input_excerpt,
            output_excerpt=self.output_excerpt,
            duration_ms=self.duration_ms,
            success=self.success,
            fallback_to_rules=self.fallback_to_rules,
            error_type=self.error_type,
            trace_linked_turn_id=self.trace_linked_turn_id,
            pre_guard_action=self.pre_guard_action,
            post_guard_action=action,
        )

    def as_log_fields(self) -> dict[str, object]:
        return {
            "assist_llm_task": self.task,
            "assist_llm_enabled": self.enabled,
            "assist_llm_model": self.model,
            "assist_llm_timeout_ms": self.timeout_ms,
            "assist_llm_runtime_call_used": self.runtime_call_used,
            "assist_llm_input_excerpt": self.input_excerpt,
            "assist_llm_output_excerpt": self.output_excerpt,
            "assist_llm_duration_ms": self.duration_ms,
            "assist_llm_success": self.success,
            "assist_llm_fallback_to_rules": self.fallback_to_rules,
            "assist_llm_error_type": self.error_type,
            "assist_llm_trace_linked_turn_id": self.trace_linked_turn_id,
            "assist_llm_pre_guard_action": self.pre_guard_action,
            "assist_llm_post_guard_action": self.post_guard_action,
        }


@dataclass(frozen=True)
class AssistLLMResult:
    task: AssistTaskType
    success: bool
    record: AssistLLMCallRecord
    text: str | None = None
    structured: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str | None:
        raw = self.structured.get("verdict")
        return str(raw) if isinstance(raw, str) else None
