from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence
import re


MemoryType = Literal["profile", "episodic"]
MemoryStatus = Literal["active", "expired", "archived"]
MemoryClass = Literal[
    "working",
    "session",
    "episodic",
    "semantic",
    "profile",
    "task",
    "impression",
]
MemoryRepresentation = Literal["raw", "abstract", "fact", "preference", "note"]
MemoryReviewState = Literal["active", "stale", "archived", "pending_review", "rejected"]
MemoryNamespace = Literal["user_memory", "agent_self_memory", "external_knowledge"]
MemoryOwnerKind = Literal["user", "agent", "world"]
SessionConsolidationState = Literal[
    "pending",
    "summarized",
    "promoted",
    "skipped",
    "archived",
]
SessionOriginKind = Literal["long_term_bridge", "session_only"]
SessionCandidateKind = Literal["episodic", "task", "preference"]

DEFAULT_NAMESPACE: MemoryNamespace = "user_memory"
DEFAULT_OWNER_KIND: MemoryOwnerKind = "user"
DEFAULT_REVIEW_STATE: MemoryReviewState = "active"
DEFAULT_SESSION_TTL_DAYS = 3
DEFAULT_SESSION_GRACE_HOURS_PROMOTED = 24
DEFAULT_SESSION_GRACE_HOURS_SKIPPED = 12
DEFAULT_SESSION_FINAL_ATTEMPT_HOURS = 6

ALLOWED_NAMESPACE_OWNER_KINDS: dict[MemoryNamespace, tuple[MemoryOwnerKind, ...]] = {
    "user_memory": ("user",),
    "agent_self_memory": ("agent",),
    "external_knowledge": ("world",),
}

_POSITIVE_PREFERENCE_PATTERN = re.compile(
    r"用户(?:偏好|喜欢|通常喜欢|更喜欢|倾向于)(?P<value>[^。；，]{1,32})"
)
_NEGATIVE_PREFERENCE_PATTERN = re.compile(
    r"用户(?:不喜欢|不希望|避免)(?P<value>[^。；，]{1,32})"
)
_ADDRESS_POSITIVE_PATTERN = re.compile(r"被称呼为(?P<value>[A-Za-z0-9_\u4e00-\u9fff]{1,16})")
_ADDRESS_NEGATIVE_PATTERN = re.compile(
    r"不希望被称呼为(?P<value>[A-Za-z0-9_\u4e00-\u9fff]{1,16})"
)
_INTERACTION_PATTERN = re.compile(r"互动方式[：:](?P<value>.+)$")


def now_timestamp() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def format_timestamp(value: datetime) -> str:
    return value.astimezone().replace(microsecond=0).isoformat()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def validate_namespace_owner(
    namespace: str | None,
    owner_kind: str | None,
) -> tuple[MemoryNamespace, MemoryOwnerKind]:
    resolved_namespace = str(namespace or DEFAULT_NAMESPACE)
    resolved_owner_kind = str(owner_kind or DEFAULT_OWNER_KIND)
    allowed = ALLOWED_NAMESPACE_OWNER_KINDS.get(resolved_namespace)  # type: ignore[arg-type]
    if allowed is None or resolved_owner_kind not in allowed:
        raise ValueError(
            f"Unsupported namespace/owner_kind combination: "
            f"{resolved_namespace}/{resolved_owner_kind}"
        )
    return (
        resolved_namespace,  # type: ignore[return-value]
        resolved_owner_kind,  # type: ignore[return-value]
    )


def derive_legacy_memory_type(memory_class: str | None) -> MemoryType:
    if memory_class in {"profile", "semantic", "impression"}:
        return "profile"
    return "episodic"


def derive_memory_class(
    *,
    memory_type: str,
    tags: Sequence[str] = (),
    dedupe_key: str | None = None,
    followup_enabled: bool = False,
    topic_key: str | None = None,
) -> MemoryClass:
    if memory_type == "profile":
        return "profile"

    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
    if followup_enabled or {"followup", "commitment"} & tag_set:
        return "task"
    if dedupe_key and dedupe_key.startswith("episodic:task:"):
        return "task"
    if "task" in tag_set and ("project" in tag_set or topic_key):
        return "task"
    return "episodic"


def derive_representation(
    *,
    memory_type: str,
    memory_class: str,
    tags: Sequence[str] = (),
    dedupe_key: str | None = None,
    summary: str | None = None,
    merge_count: int = 1,
    preference_target: str | None = None,
    preference_value: str | None = None,
) -> MemoryRepresentation:
    if preference_target or preference_value or is_preference_like(
        memory_type=memory_type,
        tags=tags,
        dedupe_key=dedupe_key,
    ):
        return "preference"
    if memory_class in {"profile", "semantic"}:
        return "fact"
    if summary or merge_count > 1:
        return "abstract"
    return "raw"


def is_preference_like(
    *,
    memory_type: str,
    tags: Sequence[str] = (),
    dedupe_key: str | None = None,
) -> bool:
    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
    if memory_type != "profile":
        return False
    if "preference" in tag_set or "interaction_style" in tag_set or "address" in tag_set:
        return True
    if "avoidance" in tag_set:
        return True
    if dedupe_key is None:
        return False
    return dedupe_key.startswith("profile:preference:") or dedupe_key == "profile:address"


def derive_preference_fields(
    *,
    canonical_text: str,
    tags: Sequence[str] = (),
    preference_target: str | None = None,
    preference_value: str | None = None,
    preference_context: str | None = None,
    preference_polarity: str | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if preference_target or preference_value:
        return (
            preference_target,
            preference_value,
            preference_context,
            preference_polarity,
        )

    text = canonical_text.strip()
    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}

    negative_address = _ADDRESS_NEGATIVE_PATTERN.search(text)
    if negative_address is not None:
        return ("address", negative_address.group("value"), None, "avoid")
    positive_address = _ADDRESS_POSITIVE_PATTERN.search(text)
    if positive_address is not None:
        return ("address", positive_address.group("value"), None, "prefer")

    if "interaction_style" in tag_set:
        interaction = _INTERACTION_PATTERN.search(text)
        if interaction is not None:
            return ("interaction_style", interaction.group("value").strip(), None, "prefer")
        return ("interaction_style", text, None, "prefer")

    negative = _NEGATIVE_PREFERENCE_PATTERN.search(text)
    if negative is not None:
        return ("topic", negative.group("value").strip(), None, "avoid")

    positive = _POSITIVE_PREFERENCE_PATTERN.search(text)
    if positive is not None:
        return ("topic", positive.group("value").strip(), None, "prefer")

    return (None, None, None, None)


def derive_cross_session_visible(
    *,
    memory_class: str | None,
    representation: str | None,
    tags: Sequence[str] = (),
    followup_enabled: bool = False,
    source_kind: str | None = None,
) -> bool:
    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
    if representation == "preference":
        return True
    if memory_class == "profile":
        return True
    if memory_class == "task" or followup_enabled:
        return True
    if source_kind == "session_consolidation":
        return True
    if "session_consolidated" in tag_set:
        return True
    return False


@dataclass(frozen=True)
class MemoryItem:
    id: str
    memory_type: MemoryType
    content: str
    source_turn: str
    source_message_excerpt: str
    created_at: str
    updated_at: str
    confidence: float
    ttl_days: int | None
    expires_at: str | None
    decay_policy: str
    status: MemoryStatus = "active"
    dedupe_key: str | None = None
    topic_key: str | None = None
    tags: tuple[str, ...] = ()
    summary: str | None = None
    pinned: bool = False
    merge_count: int = 1
    followup_enabled: bool = False
    followup_due_at: str | None = None
    last_followup_at: str | None = None
    metadata_json: str | None = None
    memory_class: MemoryClass | None = None
    representation: MemoryRepresentation | None = None
    namespace: MemoryNamespace = DEFAULT_NAMESPACE
    owner_kind: MemoryOwnerKind = DEFAULT_OWNER_KIND
    canonical_text: str | None = None
    structured_payload_json: str | None = None
    evidence_json: str | None = None
    source_kind: str = "conversation_turn"
    source_ref: str | None = None
    review_state: MemoryReviewState = DEFAULT_REVIEW_STATE
    stale_reason: str | None = None
    last_confirmed_at: str | None = None
    last_used_at: str | None = None
    supersedes_id: str | None = None
    contradicts_id: str | None = None
    strength: float | None = None
    useful_score: float = 0.0
    cross_session_visible: bool = False
    preference_target: str | None = None
    preference_value: str | None = None
    preference_strength: float | None = None
    preference_context: str | None = None
    preference_polarity: str | None = None

    def __post_init__(self) -> None:
        namespace, owner_kind = validate_namespace_owner(self.namespace, self.owner_kind)
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "owner_kind", owner_kind)

        resolved_class = self.memory_class or derive_memory_class(
            memory_type=self.memory_type,
            tags=self.tags,
            dedupe_key=self.dedupe_key,
            followup_enabled=self.followup_enabled,
            topic_key=self.topic_key,
        )
        object.__setattr__(self, "memory_class", resolved_class)

        canonical_text = self.canonical_text or self.content
        object.__setattr__(self, "canonical_text", canonical_text)

        resolved_representation = self.representation or derive_representation(
            memory_type=self.memory_type,
            memory_class=resolved_class,
            tags=self.tags,
            dedupe_key=self.dedupe_key,
            summary=self.summary,
            merge_count=max(1, self.merge_count),
            preference_target=self.preference_target,
            preference_value=self.preference_value,
        )
        object.__setattr__(self, "representation", resolved_representation)

        source_ref = self.source_ref or self.source_turn
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(
            self,
            "last_confirmed_at",
            self.last_confirmed_at or self.updated_at,
        )
        object.__setattr__(self, "strength", self.confidence if self.strength is None else self.strength)

        (
            preference_target,
            preference_value,
            preference_context,
            preference_polarity,
        ) = derive_preference_fields(
            canonical_text=canonical_text,
            tags=self.tags,
            preference_target=self.preference_target,
            preference_value=self.preference_value,
            preference_context=self.preference_context,
            preference_polarity=self.preference_polarity,
        )
        object.__setattr__(self, "preference_target", preference_target)
        object.__setattr__(self, "preference_value", preference_value)
        object.__setattr__(self, "preference_context", preference_context)
        object.__setattr__(self, "preference_polarity", preference_polarity)
        if self.preference_strength is None and resolved_representation == "preference":
            object.__setattr__(self, "preference_strength", self.confidence)
        object.__setattr__(
            self,
            "cross_session_visible",
            bool(
                self.cross_session_visible
                or derive_cross_session_visible(
                    memory_class=resolved_class,
                    representation=resolved_representation,
                    tags=self.tags,
                    followup_enabled=self.followup_enabled,
                    source_kind=self.source_kind,
                )
            ),
        )

    def is_expired(self, now: datetime) -> bool:
        if self.status == "expired":
            return True
        if self.status != "active" or not self.expires_at:
            return False
        return parse_timestamp(self.expires_at) <= now

    def is_soft_signal(self) -> bool:
        return self.memory_class == "impression"

    def display_text(self) -> str:
        return (self.summary or self.canonical_text or self.content).strip()


@dataclass(frozen=True)
class MemoryCandidate:
    memory_type: MemoryType
    content: str
    source_turn: str
    source_message_excerpt: str
    confidence: float
    ttl_days: int | None
    decay_policy: str
    dedupe_key: str | None = None
    candidate_reason: str = ""
    topic_key: str | None = None
    tags: tuple[str, ...] = ()
    summary: str | None = None
    pinned: bool = False
    merge_count: int = 1
    followup_enabled: bool = False
    followup_due_at: str | None = None
    metadata_json: str | None = None
    match_id: str | None = None
    memory_class: MemoryClass | None = None
    representation: MemoryRepresentation | None = None
    namespace: MemoryNamespace = DEFAULT_NAMESPACE
    owner_kind: MemoryOwnerKind = DEFAULT_OWNER_KIND
    canonical_text: str | None = None
    structured_payload_json: str | None = None
    evidence_json: str | None = None
    source_kind: str = "conversation_turn"
    source_ref: str | None = None
    review_state: MemoryReviewState = DEFAULT_REVIEW_STATE
    stale_reason: str | None = None
    last_confirmed_at: str | None = None
    last_used_at: str | None = None
    supersedes_id: str | None = None
    contradicts_id: str | None = None
    strength: float | None = None
    useful_score: float = 0.0
    cross_session_visible: bool = False
    preference_target: str | None = None
    preference_value: str | None = None
    preference_strength: float | None = None
    preference_context: str | None = None
    preference_polarity: str | None = None

    def __post_init__(self) -> None:
        namespace, owner_kind = validate_namespace_owner(self.namespace, self.owner_kind)
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "owner_kind", owner_kind)

        resolved_class = self.memory_class or derive_memory_class(
            memory_type=self.memory_type,
            tags=self.tags,
            dedupe_key=self.dedupe_key,
            followup_enabled=self.followup_enabled,
            topic_key=self.topic_key,
        )
        object.__setattr__(self, "memory_class", resolved_class)

        canonical_text = self.canonical_text or self.content
        object.__setattr__(self, "canonical_text", canonical_text)

        resolved_representation = self.representation or derive_representation(
            memory_type=self.memory_type,
            memory_class=resolved_class,
            tags=self.tags,
            dedupe_key=self.dedupe_key,
            summary=self.summary,
            merge_count=max(1, self.merge_count),
            preference_target=self.preference_target,
            preference_value=self.preference_value,
        )
        object.__setattr__(self, "representation", resolved_representation)

        object.__setattr__(self, "source_ref", self.source_ref or self.source_turn)
        object.__setattr__(self, "strength", self.confidence if self.strength is None else self.strength)

        (
            preference_target,
            preference_value,
            preference_context,
            preference_polarity,
        ) = derive_preference_fields(
            canonical_text=canonical_text,
            tags=self.tags,
            preference_target=self.preference_target,
            preference_value=self.preference_value,
            preference_context=self.preference_context,
            preference_polarity=self.preference_polarity,
        )
        object.__setattr__(self, "preference_target", preference_target)
        object.__setattr__(self, "preference_value", preference_value)
        object.__setattr__(self, "preference_context", preference_context)
        object.__setattr__(self, "preference_polarity", preference_polarity)
        if self.preference_strength is None and resolved_representation == "preference":
            object.__setattr__(self, "preference_strength", self.confidence)
        object.__setattr__(
            self,
            "cross_session_visible",
            bool(
                self.cross_session_visible
                or derive_cross_session_visible(
                    memory_class=resolved_class,
                    representation=resolved_representation,
                    tags=self.tags,
                    followup_enabled=self.followup_enabled,
                    source_kind=self.source_kind,
                )
            ),
        )


@dataclass(frozen=True)
class SessionMemoryItem:
    id: str
    session_id: str
    representation: MemoryRepresentation
    namespace: MemoryNamespace
    owner_kind: MemoryOwnerKind
    canonical_text: str
    source_turn: str
    created_at: str
    updated_at: str
    expires_at: str | None
    status: MemoryStatus = "active"
    consolidation_state: SessionConsolidationState = "pending"
    origin_kind: SessionOriginKind = "session_only"
    topic_key: str | None = None
    carryover_kind: str | None = None
    summary_text: str | None = None
    structured_payload_json: str | None = None
    metadata_json: str | None = None
    last_confirmed_at: str | None = None
    last_touched_at: str | None = None
    last_consolidated_at: str | None = None
    archived_at: str | None = None
    promotion_fingerprint: str | None = None
    produced_memory_refs: tuple[str, ...] = ()
    turn_id: str = ""
    source_role: str = "derived"
    category: str = "recent_event"
    content: str = ""
    content_summary: str | None = None
    importance: float = 0.0
    confidence: float = 0.0
    source_turn_range: str | None = None

    def __post_init__(self) -> None:
        namespace, owner_kind = validate_namespace_owner(self.namespace, self.owner_kind)
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "owner_kind", owner_kind)
        object.__setattr__(self, "turn_id", self.turn_id or self.source_turn)
        object.__setattr__(self, "content", self.content or self.canonical_text)
        object.__setattr__(self, "content_summary", self.content_summary or self.summary_text)
        object.__setattr__(
            self,
            "last_confirmed_at",
            self.last_confirmed_at or self.updated_at,
        )
        object.__setattr__(
            self,
            "last_touched_at",
            self.last_touched_at or self.updated_at,
        )

    def is_expired(self, now: datetime) -> bool:
        if self.status == "expired":
            return True
        if self.status != "active" or not self.expires_at:
            return False
        return parse_timestamp(self.expires_at) <= now

    def display_text(self) -> str:
        return (self.summary_text or self.canonical_text).strip()


@dataclass(frozen=True)
class SessionMemoryCandidate:
    session_id: str
    canonical_text: str
    source_turn: str
    representation: MemoryRepresentation = "abstract"
    namespace: MemoryNamespace = DEFAULT_NAMESPACE
    owner_kind: MemoryOwnerKind = DEFAULT_OWNER_KIND
    status: MemoryStatus = "active"
    consolidation_state: SessionConsolidationState = "pending"
    origin_kind: SessionOriginKind = "session_only"
    topic_key: str | None = None
    carryover_kind: str | None = None
    summary_text: str | None = None
    structured_payload_json: str | None = None
    metadata_json: str | None = None
    ttl_days: int = DEFAULT_SESSION_TTL_DAYS
    last_confirmed_at: str | None = None
    promotion_fingerprint: str | None = None
    produced_memory_refs: tuple[str, ...] = ()
    turn_id: str = ""
    source_role: str = "derived"
    category: str = "recent_event"
    content: str = ""
    content_summary: str | None = None
    importance: float = 0.0
    confidence: float = 0.0
    source_turn_range: str | None = None


@dataclass(frozen=True)
class SessionContinuityRecord:
    session_id: str
    started_at: str
    last_active_at: str
    turn_count: int = 0
    first_user_message: str | None = None
    last_user_message: str | None = None
    last_assistant_message: str | None = None
    last_scene: str | None = None
    summary_text: str | None = None
    metadata_json: str | None = None

    @property
    def display_text(self) -> str:
        return (
            self.summary_text
            or self.last_user_message
            or self.first_user_message
            or ""
        ).strip()


@dataclass(frozen=True)
class SessionPromotionCandidate:
    candidate_kind: SessionCandidateKind
    memory_candidate: MemoryCandidate
    fingerprint: str


@dataclass(frozen=True)
class SessionConsolidationResult:
    session_item_id: str
    session_id: str
    target_state: SessionConsolidationState
    summary_text: str | None = None
    promotion_candidates: tuple[SessionPromotionCandidate, ...] = ()
    skipped_reason: str | None = None
    final_attempt: bool = False
    produced_memory_refs: tuple[str, ...] = ()

    @property
    def promoted(self) -> bool:
        return bool(self.promotion_candidates)


@dataclass(frozen=True)
class SessionMaintenanceResult:
    processed: tuple[SessionConsolidationResult, ...] = ()
    archived_session_ids: tuple[str, ...] = ()
    expired_count: int = 0

    @property
    def processed_count(self) -> int:
        return len(self.processed)


@dataclass(frozen=True)
class SessionFinalizeResult:
    session_id: str
    summary_text: str | None = None
    promoted_memory_ids: tuple[str, ...] = ()
    open_loop_memory_ids: tuple[str, ...] = ()
    consolidation_triggered: bool = False
    continuity_updated: bool = False
    skipped_reason: str | None = None

    @property
    def promoted_memory_count(self) -> int:
        return len(self.promoted_memory_ids)


@dataclass(frozen=True)
class WorkingMemoryState:
    session_id: str
    active_topic_keys: tuple[str, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    recent_memory_refs: tuple[str, ...] = ()
    current_task_hint: str | None = None


@dataclass(frozen=True)
class CandidateWriteResult:
    candidate_preview: str
    accepted: bool
    action: str
    reason: str
    memory_id: str | None = None
    candidate_reason: str | None = None


@dataclass(frozen=True)
class MemorySelection:
    item: MemoryItem
    score: float
    reason: str


@dataclass(frozen=True)
class MemoryReadResult:
    selected_items: tuple[MemoryItem, ...] = ()
    session_selected_items: tuple[SessionMemoryItem, ...] = ()
    continuity_selected_items: tuple[SessionContinuityRecord, ...] = ()
    startup_selected_items: tuple[MemoryItem, ...] = ()
    working_prompt_items: tuple[str, ...] = ()
    session_prompt_items: tuple[str, ...] = ()
    continuity_prompt_items: tuple[str, ...] = ()
    startup_prompt_items: tuple[str, ...] = ()
    prompt_items: tuple[str, ...] = ()
    debug_selections: tuple[MemorySelection, ...] = ()
    continuation_cue_detected: bool = False
    retrieval_mode: str = "query"
    startup_categories: tuple[str, ...] = ()
    last_session_summary_used: bool = False
    skipped_reason: str | None = None

    @property
    def selected_ids(self) -> tuple[str, ...]:
        ids = [f"session:{item.id}" for item in self.session_selected_items]
        ids.extend(f"continuity:{item.session_id}" for item in self.continuity_selected_items)
        ids.extend(item.id for item in self.selected_items)
        return tuple(ids)

    @property
    def startup_selected_ids(self) -> tuple[str, ...]:
        ids = [item.id for item in self.startup_selected_items]
        ids.extend(f"continuity:{item.session_id}" for item in self.continuity_selected_items)
        return tuple(ids)

    @property
    def hit(self) -> bool:
        return bool(self.prompt_items)


@dataclass(frozen=True)
class MemoryWriteResult:
    stored_items: tuple[MemoryItem, ...] = ()
    decisions: tuple[CandidateWriteResult, ...] = ()
    skipped_reason: str | None = None

    @property
    def stored_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.stored_items)

    @property
    def wrote_any(self) -> bool:
        return bool(self.stored_items)


@dataclass(frozen=True)
class MemoryTurnInput:
    user_input: str
    assistant_reply: str
    scene: str
    turn_id: str
    session_id: str | None = None
    turn_index: int | None = None
    source_channel: str = "text"
    raw_asr_text: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    asr_provider: str | None = None
    tts_provider: str | None = None
    latency_json: str | None = None
    metadata_json: str | None = None


@dataclass(frozen=True)
class ConversationTurn:
    id: str
    session_id: str
    turn_index: int
    source_channel: str
    user_text: str
    assistant_text: str
    raw_asr_text: str | None
    scene: str | None
    started_at: str
    completed_at: str
    llm_provider: str | None = None
    llm_model: str | None = None
    asr_provider: str | None = None
    tts_provider: str | None = None
    latency_json: str | None = None
    metadata_json: str | None = None


@dataclass(frozen=True)
class MemoryStoreStats:
    active_profile_count: int = 0
    active_episodic_count: int = 0
    active_task_count: int = 0
    active_semantic_count: int = 0
    active_preference_count: int = 0
    expired_count: int = 0
    archived_count: int = 0
    stale_count: int = 0
    session_active_count: int = 0
