from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from typing import Sequence
import json

from src.memory.models import (
    DEFAULT_SESSION_FINAL_ATTEMPT_HOURS,
    MemoryCandidate,
    SessionConsolidationResult,
    SessionMemoryItem,
    SessionPromotionCandidate,
)
from src.memory.rules import build_followup_due_at, build_topic_key
from src.utils.text_utils import normalize_whitespace, safe_preview


_TASK_HINTS = (
    "提醒",
    "记得",
    "继续问我",
    "继续跟进",
    "follow-up",
    "deadline",
    "reminder",
    "check back",
    "next time",
)
_EVENT_HINTS = (
    "今天",
    "刚刚",
    "已经",
    "完成",
    "提交",
    "定下",
    "决定",
    "结果",
    "本次",
)
_WEAK_CHAT_HINTS = ("哈哈", "晚安", "吃饭", "天气", "随便聊聊")


@dataclass(frozen=True)
class SessionSummarizer:
    episodic_ttl_days: int

    def summarize(
        self,
        item: SessionMemoryItem,
        *,
        now: datetime,
        sibling_items: Sequence[SessionMemoryItem] = (),
        strong_only: bool = False,
    ) -> SessionConsolidationResult:
        text = normalize_whitespace(item.canonical_text).strip()
        summary_text = self._build_summary_text(item)
        if not text:
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="skipped",
                summary_text=summary_text,
                skipped_reason="empty_session_item",
                final_attempt=strong_only,
            )

        if item.namespace != "user_memory" or item.owner_kind != "user":
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="skipped",
                summary_text=summary_text,
                skipped_reason="non_user_namespace",
                final_attempt=strong_only,
            )

        if item.carryover_kind == "impression":
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="skipped",
                summary_text=summary_text,
                skipped_reason="impression_soft_signal_only",
                final_attempt=strong_only,
            )

        if any(hint in text for hint in _WEAK_CHAT_HINTS):
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="skipped",
                summary_text=summary_text,
                skipped_reason="weak_small_talk_signal",
                final_attempt=strong_only,
            )

        promotion_candidate = self._build_promotion_candidate(
            item,
            now=now,
            sibling_items=sibling_items,
            strong_only=strong_only,
            summary_text=summary_text,
        )
        if promotion_candidate is not None:
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="promoted",
                summary_text=summary_text,
                promotion_candidates=(promotion_candidate,),
                final_attempt=strong_only,
            )

        if item.carryover_kind == "session":
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="summarized",
                summary_text=summary_text,
                skipped_reason="summary_only_recheckable",
                final_attempt=strong_only,
            )

        return SessionConsolidationResult(
            session_item_id=item.id,
            session_id=item.session_id,
            target_state="skipped",
            summary_text=summary_text,
            skipped_reason="no_promotable_session_signal",
            final_attempt=strong_only,
        )

    def _build_promotion_candidate(
        self,
        item: SessionMemoryItem,
        *,
        now: datetime,
        sibling_items: Sequence[SessionMemoryItem],
        strong_only: bool,
        summary_text: str,
    ) -> SessionPromotionCandidate | None:
        preference_signal = self._extract_preference_signal(item, sibling_items=sibling_items)
        if preference_signal is not None and not strong_only:
            target, value, polarity = preference_signal
            canonical_text = f"用户偏好{target}：{value}"
            candidate = MemoryCandidate(
                memory_type="profile",
                content=canonical_text,
                canonical_text=canonical_text,
                source_turn=item.source_turn,
                source_message_excerpt=safe_preview(item.canonical_text, 60),
                confidence=0.86,
                ttl_days=None,
                decay_policy="manual_override",
                dedupe_key=f"profile:preference:{_normalize_key(target)}:{_normalize_key(value)}",
                candidate_reason="session_consolidation_preference",
                topic_key=item.topic_key or build_topic_key(value),
                tags=("preference", "session_consolidated"),
                summary=summary_text,
                memory_class="profile",
                representation="preference",
                namespace=item.namespace,
                owner_kind=item.owner_kind,
                source_kind="session_consolidation",
                source_ref=f"session_item:{item.id}",
                review_state="active",
                preference_target=target,
                preference_value=value,
                preference_strength=0.86,
                preference_polarity=polarity,
                metadata_json=_build_session_source_metadata(
                    session_item_id=item.id,
                    session_id=item.session_id,
                    candidate_kind="preference",
                ),
            )
            fingerprint = _build_promotion_fingerprint(item.id, "preference", canonical_text)
            return SessionPromotionCandidate(
                candidate_kind="preference",
                memory_candidate=candidate,
                fingerprint=fingerprint,
            )

        if self._looks_like_task(item):
            canonical_text = summary_text
            followup_enabled = self._has_followup_signal(item.canonical_text)
            candidate = MemoryCandidate(
                memory_type="episodic",
                content=canonical_text,
                canonical_text=canonical_text,
                source_turn=item.source_turn,
                source_message_excerpt=safe_preview(item.canonical_text, 60),
                confidence=0.84 if followup_enabled else 0.8,
                ttl_days=self.episodic_ttl_days,
                decay_policy="ttl_expiry",
                dedupe_key=f"episodic:task:{item.topic_key or _normalize_key(canonical_text)}",
                candidate_reason="session_consolidation_task",
                topic_key=item.topic_key or build_topic_key(canonical_text),
                tags=("session_consolidated", "task"),
                summary=summary_text,
                memory_class="task",
                representation="abstract",
                namespace=item.namespace,
                owner_kind=item.owner_kind,
                source_kind="session_consolidation",
                source_ref=f"session_item:{item.id}",
                review_state="active",
                followup_enabled=followup_enabled,
                followup_due_at=build_followup_due_at(item.canonical_text, now)
                if followup_enabled
                else None,
                metadata_json=_build_session_source_metadata(
                    session_item_id=item.id,
                    session_id=item.session_id,
                    candidate_kind="task",
                ),
            )
            fingerprint = _build_promotion_fingerprint(item.id, "task", canonical_text)
            return SessionPromotionCandidate(
                candidate_kind="task",
                memory_candidate=candidate,
                fingerprint=fingerprint,
            )

        if self._looks_like_strong_episodic(item, strong_only=strong_only):
            canonical_text = summary_text
            candidate = MemoryCandidate(
                memory_type="episodic",
                content=canonical_text,
                canonical_text=canonical_text,
                source_turn=item.source_turn,
                source_message_excerpt=safe_preview(item.canonical_text, 60),
                confidence=0.78,
                ttl_days=self.episodic_ttl_days,
                decay_policy="ttl_expiry",
                dedupe_key=f"episodic:session:{item.topic_key or _normalize_key(canonical_text)}",
                candidate_reason="session_consolidation_episodic",
                topic_key=item.topic_key or build_topic_key(canonical_text),
                tags=("session_consolidated", "episodic"),
                summary=summary_text,
                memory_class="episodic",
                representation="abstract",
                namespace=item.namespace,
                owner_kind=item.owner_kind,
                source_kind="session_consolidation",
                source_ref=f"session_item:{item.id}",
                review_state="active",
                metadata_json=_build_session_source_metadata(
                    session_item_id=item.id,
                    session_id=item.session_id,
                    candidate_kind="episodic",
                ),
            )
            fingerprint = _build_promotion_fingerprint(item.id, "episodic", canonical_text)
            return SessionPromotionCandidate(
                candidate_kind="episodic",
                memory_candidate=candidate,
                fingerprint=fingerprint,
            )

        return None

    def _build_summary_text(self, item: SessionMemoryItem) -> str:
        if item.summary_text:
            return normalize_whitespace(item.summary_text).strip()
        text = normalize_whitespace(item.canonical_text).strip()
        if item.carryover_kind == "task":
            return f"本次会话待延续事项：{text}"
        if item.carryover_kind == "episodic":
            return f"本次会话近期事件：{text}"
        if item.representation == "preference":
            return f"本次会话显式偏好：{text}"
        if item.carryover_kind == "session":
            return f"本次会话中间结论：{text}"
        return text

    def _looks_like_task(self, item: SessionMemoryItem) -> bool:
        if item.carryover_kind == "task":
            return True
        text = normalize_whitespace(item.canonical_text)
        return self._has_followup_signal(text)

    def _has_followup_signal(self, text: str) -> bool:
        return any(hint in text.casefold() for hint in _TASK_HINTS)

    def _looks_like_strong_episodic(
        self,
        item: SessionMemoryItem,
        *,
        strong_only: bool,
    ) -> bool:
        if item.carryover_kind not in {"episodic", "session"} and strong_only:
            return False
        text = normalize_whitespace(item.canonical_text)
        hint_hits = sum(1 for hint in _EVENT_HINTS if hint in text)
        if item.carryover_kind == "episodic":
            return hint_hits >= (2 if strong_only else 1)
        return hint_hits >= (3 if strong_only else 2)

    def _extract_preference_signal(
        self,
        item: SessionMemoryItem,
        *,
        sibling_items: Sequence[SessionMemoryItem],
    ) -> tuple[str, str, str] | None:
        if item.representation != "preference":
            return None
        payload = _load_json_payload(item.structured_payload_json)
        target = str(payload.get("preference_target") or "").strip()
        value = str(payload.get("preference_value") or "").strip()
        polarity = str(payload.get("preference_polarity") or "prefer").strip() or "prefer"
        if not target or not value:
            target = item.topic_key or "interaction_style"
            value = normalize_whitespace(item.canonical_text)
        if not target or not value:
            return None
        if sibling_items:
            repeated_hits = [
                sibling
                for sibling in sibling_items
                if sibling.id != item.id
                and sibling.representation == "preference"
                and normalize_whitespace(sibling.canonical_text) == normalize_whitespace(item.canonical_text)
            ]
            if repeated_hits:
                return (target, value, polarity)
        return (target, value, polarity)


def should_run_final_consolidation_attempt(
    item: SessionMemoryItem,
    *,
    now: datetime,
    threshold_hours: int = DEFAULT_SESSION_FINAL_ATTEMPT_HOURS,
) -> bool:
    if item.status != "active" or item.consolidation_state != "pending" or not item.expires_at:
        return False
    remaining_seconds = (datetime.fromisoformat(item.expires_at) - now).total_seconds()
    return 0 <= remaining_seconds <= max(1, threshold_hours) * 3600


def _build_session_source_metadata(
    *,
    session_item_id: str,
    session_id: str,
    candidate_kind: str,
) -> str:
    return json.dumps(
        {
            "source_session_item_id": session_item_id,
            "source_session_id": session_id,
            "candidate_kind": candidate_kind,
        },
        ensure_ascii=False,
    )


def _build_promotion_fingerprint(
    session_item_id: str,
    candidate_kind: str,
    canonical_text: str,
) -> str:
    payload = f"{session_item_id}|{candidate_kind}|{normalize_whitespace(canonical_text).casefold()}"
    return sha1(payload.encode("utf-8")).hexdigest()[:16]


def _load_json_payload(raw_value: str | None) -> dict[str, object]:
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_key(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())[:48] or "item"
