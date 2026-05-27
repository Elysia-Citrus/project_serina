from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re

from src.memory.models import (
    MemoryCandidate,
    MemoryItem,
    MemorySelection,
    format_timestamp,
    parse_timestamp,
)
from src.utils.text_utils import normalize_whitespace, safe_preview


PROFILE_MIN_CONFIDENCE = 0.8
MAX_CANDIDATES_PER_TURN = 3
DEFAULT_FOLLOWUP_DELAY_HOURS = 24

TEMPORAL_MARKERS = (
    "今天",
    "昨天",
    "刚刚",
    "刚才",
    "现在",
    "最近",
    "这次",
    "今晚",
    "这会儿",
)

PERSISTENT_STATE_MARKERS = ("最近", "这几天", "这一阵", "这阵子", "一直", "连续", "状态很差")

FOLLOW_UP_HINTS = (
    "提醒我",
    "记得提醒",
    "问我",
    "继续问我",
    "继续追问",
    "跟进",
    "回头",
    "到时候",
    "后续",
    "下次继续",
    "过两天再问",
)

TASK_VERBS = (
    "在做",
    "在写",
    "在准备",
    "在改",
    "在推进",
    "重构",
    "复盘",
    "计划",
    "打算",
    "准备",
    "忙着",
    "卡在",
    "要做",
    "要准备",
    "要交",
    "要去",
)

TASK_HINTS = (
    "项目",
    "代码",
    "作业",
    "论文",
    "课程",
    "考试",
    "答辩",
    "面试",
    "汇报",
    "demo",
    "文档",
    "发布",
    "展会",
    "产品",
    "方案",
    "任务",
    "计划",
    "模块",
    "训练",
)

EMOTION_HINTS = (
    "焦虑",
    "低落",
    "难受",
    "崩",
    "崩溃",
    "压抑",
    "状态很差",
    "累坏",
    "睡不好",
    "烦",
)

GENERIC_STOPWORDS = {
    "老师",
    "最近",
    "现在",
    "今天",
    "那个",
    "这个",
    "事情",
    "感觉",
    "有点",
    "一下",
    "继续",
    "我们",
    "项目",
    "任务",
    "计划",
    "模块",
}

PROFILE_ADDRESS_PATTERNS = (
    re.compile(
        r"(?:以后|之后|平时|默认)?(?:就)?(?:请)?(?:直接)?(?:叫我|喊我|称呼我)(?P<value>[A-Za-z0-9_\u4e00-\u9fff]{1,12})"
    ),
    re.compile(
        r"我(?:更)?喜欢你(?:叫我|喊我)(?P<value>[A-Za-z0-9_\u4e00-\u9fff]{1,12})"
    ),
)

PROFILE_AVOID_ADDRESS_PATTERNS = (
    re.compile(
        r"别(?:再)?(?:叫我|喊我|称呼我)(?P<value>[A-Za-z0-9_\u4e00-\u9fff]{1,12})"
    ),
)

PROFILE_PREFERENCE_PATTERN = re.compile(
    r"(?:我|其实我|我一直|我向来|我平时|我都)(?P<polarity>特别喜欢|很喜欢|喜欢|讨厌|很讨厌|不喜欢|一直喜欢|一直不喜欢)(?P<object>[^，。！？；]{1,24})"
)

INTERACTION_HINTS = (
    "直接一点",
    "简短一点",
    "详细一点",
    "温柔一点",
    "别太说教",
    "少说教",
    "别像客服",
    "多问一句",
    "少问一点",
    "别太油",
    "别太暧昧",
)

INTERACTION_PREFIXES = (
    "我希望你",
    "我更喜欢你",
    "我不喜欢你",
    "你可以",
    "别总是",
    "请你",
)

TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
TIME_PATTERN = re.compile(r"(今天|最近|这几天|这周|下周|明天|后天|过两天)")


def extract_candidates(
    *,
    user_input: str,
    source_turn: str,
    episodic_ttl_days: int,
    now: datetime,
    scene: str,
) -> list[MemoryCandidate]:
    text = normalize_whitespace(user_input)
    if not text:
        return []

    candidates: list[MemoryCandidate] = []
    seen_keys: set[str] = set()
    for clause in split_clauses(text):
        candidate = (
            _extract_profile_address(clause, source_turn=source_turn)
            or _extract_profile_avoid_address(clause, source_turn=source_turn)
            or _extract_interaction_preference(clause, source_turn=source_turn)
            or _extract_profile_preference(clause, source_turn=source_turn)
            or _extract_follow_up(
                clause,
                source_turn=source_turn,
                ttl_days=episodic_ttl_days,
                now=now,
            )
            or _extract_recent_task(
                clause,
                source_turn=source_turn,
                ttl_days=episodic_ttl_days,
            )
            or _extract_emotion_state(
                clause,
                source_turn=source_turn,
                ttl_days=episodic_ttl_days,
                scene=scene,
            )
        )
        if candidate is None:
            continue
        key = candidate.dedupe_key or candidate.topic_key or candidate.content
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(candidate)
        if len(candidates) >= MAX_CANDIDATES_PER_TURN:
            break
    return candidates


def should_inject_profile(memory: MemoryItem) -> bool:
    return memory.memory_class in {"profile", "semantic"} and (
        memory.pinned or memory.confidence >= PROFILE_MIN_CONFIDENCE
    )


def score_memory_for_query(
    memory: MemoryItem,
    *,
    user_input: str,
    scene: str,
    now: datetime,
) -> MemorySelection | None:
    if memory.review_state in {"rejected", "archived"}:
        return None
    if memory.namespace == "external_knowledge" and memory.owner_kind != "world":
        return None
    if memory.memory_class in {"profile", "semantic"} and not should_inject_profile(memory):
        return None
    if memory.memory_class in {"episodic", "task"} and memory.is_expired(now):
        return None

    query_tokens = extract_retrieval_tokens(user_input)
    if not query_tokens:
        return None
    memory_tokens = extract_retrieval_tokens(
        " ".join(
            filter(
                None,
                (
                    memory.display_text(),
                    memory.source_message_excerpt,
                    memory.topic_key or "",
                    memory.preference_target or "",
                    memory.preference_value or "",
                ),
            )
        )
    )
    overlap = sorted(query_tokens & memory_tokens)
    if not overlap:
        return None

    score = float(len(overlap))
    score += max(0.0, memory.confidence - 0.6)
    score += _memory_priority_bonus(memory)
    if memory.pinned:
        score += 0.5

    if memory.memory_class in {"episodic", "task"}:
        age_days = max(0, int((now - parse_timestamp(memory.updated_at)).days))
        if age_days <= 2:
            score += 0.9
        elif age_days <= 7:
            score += 0.5
        else:
            score += 0.2
        if memory.merge_count > 1:
            score += min(0.6, memory.merge_count * 0.1)
    elif memory.last_confirmed_at is not None:
        confirmed_days = max(0, int((now - parse_timestamp(memory.last_confirmed_at)).days))
        if confirmed_days <= 7:
            score += 0.4
        elif confirmed_days <= 30:
            score += 0.2

    if memory.representation == "preference":
        score += 0.2
    if memory.review_state == "pending_review":
        score -= 0.25
    elif memory.review_state == "stale":
        score -= 0.5
    if memory.memory_class == "impression":
        score -= 0.35
    if memory.namespace == "external_knowledge":
        score -= 0.4

    if scene == "comfort" and memory.memory_class in {"episodic", "task"} and "状态" in memory.display_text():
        score += 0.4
    if scene == "correction" and memory.memory_class in {"episodic", "task"} and (
        "卡" in memory.display_text() or "拖" in memory.display_text()
    ):
        score += 0.2

    return MemorySelection(
        item=memory,
        score=score,
        reason=f"keyword_overlap={','.join(overlap[:4])}",
    )


def sort_memory_selections(selections: list[MemorySelection]) -> list[MemorySelection]:
    return sorted(
        selections,
        key=lambda selection: (
            _memory_order_rank(selection.item),
            -selection.score,
            -parse_timestamp(selection.item.updated_at).timestamp(),
        ),
    )


def format_memory_for_prompt(memory: MemoryItem) -> str:
    if memory.memory_class == "task":
        prefix = "[task]"
    elif memory.memory_class == "episodic":
        prefix = "[episodic]"
    elif memory.representation == "preference":
        prefix = "[preference]"
    elif memory.memory_class == "semantic":
        prefix = "[semantic]"
    elif memory.memory_class == "impression":
        prefix = "[impression-soft]"
    elif memory.namespace == "external_knowledge":
        prefix = "[external-note]"
    else:
        prefix = "[profile]"
    suffix = " (soft signal only)" if memory.memory_class == "impression" else ""
    return f"{prefix} {memory.display_text().strip().rstrip('。')}{suffix}"


def _memory_order_rank(memory: MemoryItem) -> int:
    if memory.namespace == "external_knowledge":
        return 6
    if memory.memory_class == "task":
        return 2
    if memory.memory_class == "episodic":
        return 3
    if memory.memory_class == "semantic":
        return 5
    if memory.memory_class == "impression":
        return 4
    if memory.representation == "preference":
        return 4
    return 4


def _memory_priority_bonus(memory: MemoryItem) -> float:
    if memory.memory_class == "task":
        return 1.0
    if memory.memory_class == "episodic":
        return 0.75
    if memory.representation == "preference":
        return 0.55
    if memory.memory_class == "semantic":
        return 0.35
    if memory.memory_class == "impression":
        return 0.1
    if memory.namespace == "external_knowledge":
        return -0.2
    return 0.45


def build_candidate_expires_at(candidate: MemoryCandidate, now: datetime) -> str | None:
    if candidate.ttl_days is None:
        return None
    return format_timestamp(now + timedelta(days=candidate.ttl_days))


def should_merge_episodic_candidate(
    candidate: MemoryCandidate,
    existing: MemoryItem,
    *,
    now: datetime,
    merge_window_hours: int,
) -> bool:
    if candidate.memory_type != "episodic" or existing.memory_type != "episodic":
        return False
    if candidate.memory_class != existing.memory_class:
        return False
    if existing.status != "active" or existing.is_expired(now):
        return False
    if parse_timestamp(existing.updated_at) < now - timedelta(hours=merge_window_hours):
        return False
    if candidate.topic_key and existing.topic_key and candidate.topic_key == existing.topic_key:
        return True
    if candidate.tags and existing.tags and set(candidate.tags) & set(existing.tags):
        return calculate_text_similarity(candidate.content, existing.display_text()) >= 0.38
    return calculate_text_similarity(candidate.content, existing.display_text()) >= 0.68


def merge_candidate_with_existing(
    candidate: MemoryCandidate,
    existing: MemoryItem,
) -> MemoryCandidate:
    merged_tags = tuple(sorted({*existing.tags, *candidate.tags}))
    merged_count = existing.merge_count + 1
    followup_enabled = existing.followup_enabled or candidate.followup_enabled
    topic_key = candidate.topic_key or existing.topic_key
    summary = build_merged_summary(
        existing=existing,
        candidate=candidate,
        merged_count=merged_count,
        followup_enabled=followup_enabled,
    )
    return MemoryCandidate(
        memory_type=candidate.memory_type,
        content=candidate.content or existing.content,
        source_turn=candidate.source_turn,
        source_message_excerpt=candidate.source_message_excerpt,
        confidence=max(existing.confidence, candidate.confidence),
        ttl_days=candidate.ttl_days or existing.ttl_days,
        decay_policy=candidate.decay_policy,
        dedupe_key=candidate.dedupe_key or existing.dedupe_key,
        candidate_reason=candidate.candidate_reason,
        topic_key=topic_key,
        tags=merged_tags,
        summary=summary,
        pinned=existing.pinned,
        merge_count=merged_count,
        followup_enabled=followup_enabled,
        followup_due_at=candidate.followup_due_at or existing.followup_due_at,
        metadata_json=candidate.metadata_json or existing.metadata_json,
        match_id=existing.id,
        memory_class=candidate.memory_class,
        representation=candidate.representation,
        namespace=candidate.namespace,
        owner_kind=candidate.owner_kind,
        canonical_text=candidate.canonical_text or existing.canonical_text,
        structured_payload_json=candidate.structured_payload_json
        or existing.structured_payload_json,
        evidence_json=candidate.evidence_json or existing.evidence_json,
        source_kind=candidate.source_kind,
        source_ref=candidate.source_ref or existing.source_ref,
        review_state=candidate.review_state,
        stale_reason=candidate.stale_reason,
        last_confirmed_at=candidate.last_confirmed_at or existing.last_confirmed_at,
        supersedes_id=candidate.supersedes_id,
        contradicts_id=candidate.contradicts_id,
        strength=max(existing.strength or existing.confidence, candidate.strength or candidate.confidence),
        useful_score=max(existing.useful_score, candidate.useful_score),
        preference_target=candidate.preference_target or existing.preference_target,
        preference_value=candidate.preference_value or existing.preference_value,
        preference_strength=max(
            existing.preference_strength or 0.0,
            candidate.preference_strength or 0.0,
        )
        or None,
        preference_context=candidate.preference_context or existing.preference_context,
        preference_polarity=candidate.preference_polarity or existing.preference_polarity,
    )


def calculate_text_similarity(left: str, right: str) -> float:
    left_tokens = extract_retrieval_tokens(left)
    right_tokens = extract_retrieval_tokens(right)
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        if union:
            jaccard = overlap / union
            if jaccard >= 0.45:
                return jaccard
    return SequenceMatcher(a=normalize_whitespace(left), b=normalize_whitespace(right)).ratio()


def split_clauses(text: str) -> list[str]:
    parts = re.split(r"[，,\n。！？!?；;]", normalize_whitespace(text))
    return [part.strip(" ，,") for part in parts if part and part.strip(" ，,")]


def extract_retrieval_tokens(text: str) -> set[str]:
    normalized = normalize_whitespace(text).casefold()
    tokens: set[str] = set()
    for match in TOKEN_PATTERN.finditer(normalized):
        token = match.group(0)
        if token in GENERIC_STOPWORDS:
            continue
        if token.isascii():
            tokens.add(token)
            continue
        tokens.add(token)
        if len(token) > 2:
            for index in range(len(token) - 1):
                piece = token[index : index + 2]
                if piece not in GENERIC_STOPWORDS:
                    tokens.add(piece)
    return tokens


def build_merged_summary(
    *,
    existing: MemoryItem,
    candidate: MemoryCandidate,
    merged_count: int,
    followup_enabled: bool,
) -> str | None:
    base = candidate.summary or existing.summary or candidate.content or existing.content
    if not base:
        return None
    base = base.strip().rstrip("。")
    if merged_count <= 1:
        return f"{base}。"
    if followup_enabled:
        if "持续" in base or "多次" in base:
            return f"{base}。"
        return f"{base.replace('最近在做', '最近持续在做').replace('近期事项', '最近持续在做')}，并约定后续跟进。"
    if "状态" in base:
        return f"用户近期多次提到{_strip_user_prefix(base)}。"
    if "最近在做" in base:
        return f"{base.replace('最近在做', '最近持续在做')}。"
    return f"用户最近持续在做{_strip_user_prefix(base)}。"


def build_topic_key(text: str) -> str | None:
    tokens = [
        token
        for token in extract_retrieval_tokens(text)
        if token not in GENERIC_STOPWORDS and not TIME_PATTERN.fullmatch(token)
    ]
    if not tokens:
        return None
    return "|".join(sorted(tokens)[:4])


def build_topic_label(text: str) -> str:
    normalized = normalize_whitespace(text)
    cleaned = TIME_PATTERN.sub("", normalized)
    cleaned = re.sub(
        r"(提醒我|记得提醒|下次继续问我|继续问我|继续追问|过两天再问|之后可以继续追问|之后提醒我)",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(我|最近|这几天|这周|下周|明天|后天|一直|正在|在)\s*", "", cleaned)
    cleaned = cleaned.strip(" ，,。")
    return cleaned or safe_preview(normalized, 24)


def build_followup_due_at(clause: str, now: datetime) -> str:
    if "明天" in clause:
        return format_timestamp(now + timedelta(days=1))
    if "后天" in clause or "过两天" in clause:
        return format_timestamp(now + timedelta(days=2))
    if "下周" in clause:
        return format_timestamp(now + timedelta(days=7))
    if "今晚" in clause:
        return format_timestamp(now + timedelta(hours=8))
    return format_timestamp(now + timedelta(hours=DEFAULT_FOLLOWUP_DELAY_HOURS))


def _extract_profile_address(clause: str, *, source_turn: str) -> MemoryCandidate | None:
    for pattern in PROFILE_ADDRESS_PATTERNS:
        match = pattern.search(clause)
        if match is None:
            continue
        value = match.group("value").strip()
        if not value:
            return None
        return MemoryCandidate(
            memory_type="profile",
            content=f"用户偏好被称呼为{value}。",
            canonical_text=f"用户偏好被称呼为{value}。",
            source_turn=source_turn,
            source_message_excerpt=safe_preview(clause, 60),
            confidence=0.96,
            ttl_days=None,
            decay_policy="manual_override",
            dedupe_key="profile:address",
            candidate_reason="address_preference",
            tags=("address", "preference"),
            summary=f"用户偏好被称呼为{value}。",
            memory_class="profile",
            representation="preference",
            preference_target="address",
            preference_value=value,
            preference_strength=0.96,
            preference_polarity="prefer",
        )
    return None


def _extract_profile_avoid_address(
    clause: str,
    *,
    source_turn: str,
) -> MemoryCandidate | None:
    for pattern in PROFILE_AVOID_ADDRESS_PATTERNS:
        match = pattern.search(clause)
        if match is None:
            continue
        value = match.group("value").strip()
        if not value:
            return None
        return MemoryCandidate(
            memory_type="profile",
            content=f"用户不希望被称呼为{value}。",
            canonical_text=f"用户不希望被称呼为{value}。",
            source_turn=source_turn,
            source_message_excerpt=safe_preview(clause, 60),
            confidence=0.93,
            ttl_days=None,
            decay_policy="manual_override",
            dedupe_key="profile:address",
            candidate_reason="address_avoidance",
            tags=("address", "avoidance"),
            summary=f"用户不希望被称呼为{value}。",
            memory_class="profile",
            representation="preference",
            preference_target="address",
            preference_value=value,
            preference_strength=0.93,
            preference_polarity="avoid",
        )
    return None


def _extract_interaction_preference(
    clause: str,
    *,
    source_turn: str,
) -> MemoryCandidate | None:
    if not any(prefix in clause for prefix in INTERACTION_PREFIXES):
        return None
    if not any(hint in clause for hint in INTERACTION_HINTS):
        return None
    statement = _to_user_statement(clause)
    return MemoryCandidate(
        memory_type="profile",
        content=f"用户偏好互动方式：{statement}",
        canonical_text=f"用户偏好互动方式：{statement}",
        source_turn=source_turn,
        source_message_excerpt=safe_preview(clause, 60),
        confidence=0.9,
        ttl_days=None,
        decay_policy="manual_override",
        dedupe_key="profile:interaction_style",
        candidate_reason="interaction_preference",
        tags=("interaction_style", "preference"),
        summary=f"用户偏好互动方式：{statement}",
        memory_class="profile",
        representation="preference",
        preference_target="interaction_style",
        preference_value=statement,
        preference_strength=0.9,
        preference_polarity="prefer",
    )


def _extract_profile_preference(
    clause: str,
    *,
    source_turn: str,
) -> MemoryCandidate | None:
    match = PROFILE_PREFERENCE_PATTERN.search(clause)
    if match is None:
        return None

    object_text = match.group("object").strip(" ，,")
    if not object_text or not _looks_stable_preference(clause, object_text):
        return None

    polarity = match.group("polarity")
    verb = "喜欢" if "喜欢" in polarity else "明确不喜欢"
    return MemoryCandidate(
        memory_type="profile",
        content=f"用户{verb}{object_text}。",
        canonical_text=f"用户{verb}{object_text}。",
        source_turn=source_turn,
        source_message_excerpt=safe_preview(clause, 60),
        confidence=0.85,
        ttl_days=None,
        decay_policy="manual_override",
        dedupe_key=f"profile:preference:{_normalize_key(object_text)}",
        candidate_reason="stable_preference",
        topic_key=build_topic_key(object_text),
        tags=("preference", verb),
        summary=f"用户{verb}{object_text}。",
        memory_class="profile",
        representation="preference",
        preference_target="topic",
        preference_value=object_text,
        preference_strength=0.85,
        preference_polarity="prefer" if "喜欢" in verb else "avoid",
    )


def _extract_follow_up(
    clause: str,
    *,
    source_turn: str,
    ttl_days: int,
    now: datetime,
) -> MemoryCandidate | None:
    if not any(hint in clause for hint in FOLLOW_UP_HINTS):
        return None
    topic_label = build_topic_label(clause)
    topic_key = build_topic_key(topic_label or clause)
    return MemoryCandidate(
        memory_type="episodic",
        content=f"用户约定后续可跟进：{_to_user_statement(clause)}",
        canonical_text=f"用户约定后续可跟进：{_to_user_statement(clause)}",
        source_turn=source_turn,
        source_message_excerpt=safe_preview(clause, 60),
        confidence=0.92,
        ttl_days=ttl_days,
        decay_policy="ttl_expiry",
        dedupe_key=f"episodic:follow_up:{topic_key or _normalize_key(clause)}",
        candidate_reason="explicit_follow_up",
        topic_key=topic_key,
        tags=("followup", "commitment"),
        summary=f"用户最近提到{topic_label}，并约定后续跟进。",
        followup_enabled=True,
        followup_due_at=build_followup_due_at(clause, now),
        memory_class="task",
        representation="abstract",
    )


def _extract_recent_task(
    clause: str,
    *,
    source_turn: str,
    ttl_days: int,
) -> MemoryCandidate | None:
    has_task_signal = any(verb in clause for verb in TASK_VERBS) and any(
        hint in clause for hint in TASK_HINTS
    )
    has_temporal_task_signal = any(
        marker in clause for marker in ("最近", "这几天", "这周", "下周", "明天", "后天")
    ) and any(hint in clause for hint in TASK_HINTS)
    if not has_task_signal and not has_temporal_task_signal:
        return None
    topic_label = build_topic_label(clause)
    topic_key = build_topic_key(topic_label or clause)
    return MemoryCandidate(
        memory_type="episodic",
        content=f"用户近期事项：{_to_user_statement(clause)}",
        canonical_text=f"用户近期事项：{_to_user_statement(clause)}",
        source_turn=source_turn,
        source_message_excerpt=safe_preview(clause, 60),
        confidence=0.82,
        ttl_days=ttl_days,
        decay_policy="ttl_expiry",
        dedupe_key=f"episodic:task:{topic_key or _normalize_key(clause)}",
        candidate_reason="recent_task",
        topic_key=topic_key,
        tags=("task", "project"),
        summary=f"用户最近在做{topic_label}。",
        memory_class="task",
        representation="abstract",
    )


def _extract_emotion_state(
    clause: str,
    *,
    source_turn: str,
    ttl_days: int,
    scene: str,
) -> MemoryCandidate | None:
    del scene
    has_temporal_marker = any(marker in clause for marker in PERSISTENT_STATE_MARKERS)
    has_emotion = any(hint in clause for hint in EMOTION_HINTS)
    if not has_emotion or not has_temporal_marker:
        return None

    emotion_label = _extract_emotion_label(clause)
    return MemoryCandidate(
        memory_type="episodic",
        content=f"用户近期状态：{_to_user_statement(clause)}",
        canonical_text=f"用户近期状态：{_to_user_statement(clause)}",
        source_turn=source_turn,
        source_message_excerpt=safe_preview(clause, 60),
        confidence=0.78,
        ttl_days=max(3, min(ttl_days, 7)),
        decay_policy="ttl_expiry",
        dedupe_key="episodic:emotion_state",
        candidate_reason="recent_emotion",
        topic_key="emotion_state",
        tags=("emotion", emotion_label),
        summary=f"用户近期状态偏{emotion_label}。",
        memory_class="episodic",
        representation="abstract",
    )


def _looks_stable_preference(clause: str, object_text: str) -> bool:
    if any(marker in clause for marker in TEMPORAL_MARKERS):
        return False
    if len(object_text) > 18:
        return False
    if object_text.endswith(("一下", "一会儿", "这一次", "今天的天气")):
        return False
    return True


def _extract_emotion_label(clause: str) -> str:
    for hint in EMOTION_HINTS:
        if hint in clause:
            return hint
    return "低落"


def _to_user_statement(clause: str) -> str:
    cleaned = clause.strip().rstrip("。")
    if cleaned.startswith("我"):
        return f"用户{cleaned[1:]}"
    if cleaned.startswith("老师"):
        return cleaned
    return f"用户提到{cleaned}"


def _strip_user_prefix(text: str) -> str:
    cleaned = text.strip().rstrip("。")
    for prefix in ("用户最近在做", "用户最近提到", "用户近期事项：", "用户近期状态：", "用户"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :].strip(" ：:")
    return cleaned


def _normalize_key(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text.casefold())[:48] or "item"
