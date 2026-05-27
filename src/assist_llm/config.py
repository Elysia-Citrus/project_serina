from __future__ import annotations

from dataclasses import dataclass

from src.config.loader import RuntimeConfig


@dataclass(frozen=True)
class AssistLLMConfig:
    enabled: bool
    default_model: str
    runtime_model: str
    dev_model: str
    timeout_ms: int
    max_runtime_calls_per_turn: int
    max_dev_calls_per_command: int
    enable_guard_retry_rewrite: bool
    enable_memory_reference_check: bool
    enable_trace_summary: bool
    enable_badcase_draft: bool
    enable_pending_review_note: bool
    enable_merge_summary: bool

    @classmethod
    def from_runtime(cls, runtime: RuntimeConfig) -> "AssistLLMConfig":
        return cls(
            enabled=runtime.assist_llm_enabled,
            default_model=runtime.assist_llm_default_model,
            runtime_model=runtime.assist_llm_runtime_model,
            dev_model=runtime.assist_llm_dev_model,
            timeout_ms=runtime.assist_llm_timeout_ms,
            max_runtime_calls_per_turn=runtime.assist_llm_max_runtime_calls_per_turn,
            max_dev_calls_per_command=runtime.assist_llm_max_dev_calls_per_command,
            enable_guard_retry_rewrite=runtime.assist_llm_enable_guard_retry_rewrite,
            enable_memory_reference_check=runtime.assist_llm_enable_memory_reference_check,
            enable_trace_summary=runtime.assist_llm_enable_trace_summary,
            enable_badcase_draft=runtime.assist_llm_enable_badcase_draft,
            enable_pending_review_note=runtime.assist_llm_enable_pending_review_note,
            enable_merge_summary=runtime.assist_llm_enable_merge_summary,
        )
