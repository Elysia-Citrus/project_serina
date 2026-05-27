from __future__ import annotations

from dataclasses import dataclass

from src.assist_llm.models import AssistTaskScope, AssistTaskType


@dataclass(frozen=True)
class AssistTaskSpec:
    task: AssistTaskType
    scope: AssistTaskScope
    enabled_flag: str
    request_tag: str
    temperature: float
    max_tokens: int


TASK_SPECS: dict[AssistTaskType, AssistTaskSpec] = {
    "summarize_trace_cluster": AssistTaskSpec(
        task="summarize_trace_cluster",
        scope="dev",
        enabled_flag="enable_trace_summary",
        request_tag="assist_trace_summary",
        temperature=0.2,
        max_tokens=220,
    ),
    "draft_badcase_case": AssistTaskSpec(
        task="draft_badcase_case",
        scope="dev",
        enabled_flag="enable_badcase_draft",
        request_tag="assist_badcase_draft",
        temperature=0.1,
        max_tokens=260,
    ),
    "review_pending_memory_note": AssistTaskSpec(
        task="review_pending_memory_note",
        scope="dev",
        enabled_flag="enable_pending_review_note",
        request_tag="assist_pending_review_note",
        temperature=0.1,
        max_tokens=120,
    ),
    "summarize_episodic_merge": AssistTaskSpec(
        task="summarize_episodic_merge",
        scope="dev",
        enabled_flag="enable_merge_summary",
        request_tag="assist_merge_summary",
        temperature=0.1,
        max_tokens=120,
    ),
    "guard_retry_rewrite": AssistTaskSpec(
        task="guard_retry_rewrite",
        scope="runtime",
        enabled_flag="enable_guard_retry_rewrite",
        request_tag="assist_guard_retry_rewrite",
        temperature=0.2,
        max_tokens=180,
    ),
    "optional_memory_reference_check": AssistTaskSpec(
        task="optional_memory_reference_check",
        scope="runtime",
        enabled_flag="enable_memory_reference_check",
        request_tag="assist_memory_reference_check",
        temperature=0.0,
        max_tokens=80,
    ),
}
