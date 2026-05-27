from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from src.assist_llm.models import AssistLLMRequest, AssistTaskType
from src.utils.text_utils import normalize_whitespace, safe_preview


def build_messages(request: AssistLLMRequest) -> list[dict[str, str]]:
    prompt = _build_user_prompt(request.task, request.payload)
    return [
        {
            "role": "system",
            "content": (
                "You are a tightly controlled assist lane for Project Serina. "
                "Return concise JSON only. Never add extra commentary."
            ),
        },
        {"role": "user", "content": prompt},
    ]


def parse_response(task: AssistTaskType, raw_text: str) -> tuple[str | None, dict[str, Any]]:
    cleaned = normalize_whitespace(raw_text)
    if not cleaned:
        raise ValueError("empty assist-llm response")

    payload = _try_parse_json(cleaned)
    if payload is None:
        if task == "guard_retry_rewrite":
            return cleaned, {"revised_reply": cleaned}
        if task == "review_pending_memory_note":
            return cleaned, {"note": cleaned}
        if task == "summarize_episodic_merge":
            return cleaned, {"summary": cleaned}
        raise ValueError("assist-llm response is not valid JSON")

    if task == "guard_retry_rewrite":
        revised_reply = _read_string(payload, "revised_reply")
        return revised_reply, {"revised_reply": revised_reply}
    if task == "optional_memory_reference_check":
        verdict = _read_string(payload, "verdict")
        if verdict not in {"supported", "weakly_supported", "unsupported"}:
            raise ValueError("invalid verdict")
        reason = _read_string(payload, "reason", allow_empty=True)
        return reason, {"verdict": verdict, "reason": reason}
    if task == "review_pending_memory_note":
        note = _read_string(payload, "note")
        return note, {"note": note}
    if task == "summarize_episodic_merge":
        summary = _read_string(payload, "summary")
        return summary, {"summary": summary}
    if task == "summarize_trace_cluster":
        summary = _read_string(payload, "summary")
        return summary, {
            "summary": summary,
            "common_patterns": _read_string_list(payload.get("common_patterns")),
            "recommended_focus": _read_string(payload, "recommended_focus", allow_empty=True),
        }
    if task == "draft_badcase_case":
        return None, payload
    raise ValueError(f"unsupported assist task: {task}")


def build_input_excerpt(payload: Mapping[str, Any], limit: int = 160) -> str:
    return safe_preview(json.dumps(payload, ensure_ascii=False, sort_keys=True), limit)


def _build_user_prompt(task: AssistTaskType, payload: Mapping[str, Any]) -> str:
    lines = [f"task={task}"]
    if task == "guard_retry_rewrite":
        lines.extend(
            [
                "Return JSON: {\"revised_reply\": \"...\"}",
                "Goal: revise the reply once. Keep it natural, short, in-scene, and persona-safe.",
                "Do not mention AI, model identity, or hidden tools.",
                f"scene={payload.get('scene', '')}",
                f"user_input={payload.get('user_input', '')}",
                f"memory_summaries={_join_items(payload.get('memory_summaries'))}",
                f"violations={_join_items(payload.get('violation_categories'))}",
                f"constraints={_join_items(payload.get('rewrite_constraints'))}",
                f"original_reply={payload.get('original_reply_excerpt', '')}",
            ]
        )
    elif task == "optional_memory_reference_check":
        lines.extend(
            [
                "Return JSON: {\"verdict\": \"supported|weakly_supported|unsupported\", \"reason\": \"...\"}",
                "Judge only whether the memory reference is supported by the provided injected memories.",
                "Do not invent missing evidence.",
                f"user_input={payload.get('user_input', '')}",
                f"reply_excerpt={payload.get('reply_excerpt', '')}",
                f"memory_summaries={_join_items(payload.get('memory_summaries'))}",
            ]
        )
    elif task == "summarize_trace_cluster":
        lines.extend(
            [
                "Return JSON with summary, common_patterns, recommended_focus.",
                f"trace_cluster={_join_items(payload.get('trace_records'))}",
            ]
        )
    elif task == "draft_badcase_case":
        lines.extend(
            [
                "Return JSON with case_id, scene, user_input, injected_memories, assistant_reply, observed_violations, suggested_expected_categories, suggested_expected_action, reviewer_notes.",
                f"trace_record={json.dumps(dict(payload), ensure_ascii=False)}",
            ]
        )
    elif task == "review_pending_memory_note":
        lines.extend(
            [
                "Return JSON: {\"note\": \"...\"}",
                "Explain briefly why this pending memory candidate looks stable, episodic, or under-supported.",
                f"candidate={json.dumps(dict(payload), ensure_ascii=False)}",
            ]
        )
    elif task == "summarize_episodic_merge":
        lines.extend(
            [
                "Return JSON: {\"summary\": \"...\"}",
                "Compress only. Do not add new facts, causes, or duration claims.",
                f"merged_items={_join_items(payload.get('source_items'))}",
                f"fallback_summary={payload.get('fallback_summary', '')}",
            ]
        )
    else:
        raise ValueError(f"unsupported assist task: {task}")
    return "\n".join(lines)


def _join_items(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return str(value or "")
    return " | ".join(str(item) for item in value if str(item).strip())


def _try_parse_json(raw_text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _read_string(
    payload: Mapping[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"missing string field: {key}")
    text = normalize_whitespace(value)
    if not allow_empty and not text:
        raise ValueError(f"empty string field: {key}")
    return text


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [normalize_whitespace(str(item)) for item in value if normalize_whitespace(str(item))]
