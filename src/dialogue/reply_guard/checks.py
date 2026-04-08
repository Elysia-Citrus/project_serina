from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re
from typing import Iterable

from src.dialogue.reply_guard.models import ReplyGuardContext, ReplyViolation
from src.memory.models import MemoryItem, now_timestamp
from src.utils.text_utils import safe_preview


AI_SELF_DISCLOSURE_PATTERNS = (
    re.compile(r"作为\s*(?:一个)?\s*(?:ai|人工智能|语言模型|程序|模型)", re.IGNORECASE),
    re.compile(r"我是\s*(?:一个)?\s*(?:ai|人工智能|语言模型|程序|模型)", re.IGNORECASE),
    re.compile(r"我只是\s*(?:一个)?\s*(?:程序|模型|语言模型)", re.IGNORECASE),
    re.compile(r"只能从(?:数据|语料)角度", re.IGNORECASE),
)

MEMORY_STRONG_CLAIM_PATTERNS = (
    re.compile(r"我记得你之前"),
    re.compile(r"我记得你以前"),
    re.compile(r"我记得你前两天"),
    re.compile(r"我记得你上次"),
    re.compile(r"你之前(?:不是|一直|总是)"),
    re.compile(r"你一直(?:都)?"),
    re.compile(r"你总是"),
    re.compile(r"你每次都"),
    re.compile(r"你一向"),
)

PREACHY_PATTERNS = (
    "你应该立刻",
    "你必须",
    "严格执行",
    "立刻停止这种想法",
    "按下面",
    "先复盘",
    "系统性地",
)

CUSTOMER_SERVICE_PATTERNS = (
    "您好",
    "很高兴为你服务",
    "感谢你的分享",
    "亲爱的用户",
    "如有需要",
    "以下是我的回答",
)

TEMPLATE_PATTERNS = (
    "下面我将",
    "以下是我的回答",
    "分三点",
    "第一，",
    "第二，",
    "第三，",
    "总结一下",
)

FLIPPANT_PATTERNS = ("哈哈这", "别想太多啦", "开心最重要", "~")
EMPTY_ENCOURAGEMENT_PATTERNS = ("你一定可以", "你真的很棒", "请加油", "相信未来")


@dataclass(frozen=True)
class MemorySupportSnapshot:
    checked_ids: tuple[str, ...]
    relevant_ids: tuple[str, ...]
    relevant_items: tuple[MemoryItem, ...]
    has_support: bool
    has_low_confidence_support: bool
    has_profile_support: bool
    has_expired_support: bool


def run_checks(context: ReplyGuardContext) -> tuple[ReplyViolation, ...]:
    support = inspect_memory_support(context)
    violations: list[ReplyViolation] = []
    violations.extend(check_ai_self_disclosure(context))
    violations.extend(check_fake_memory_claim(context, support))
    violations.extend(check_scene_conflict(context))
    violations.extend(check_templated_tone(context))
    violations.extend(check_overlong(context))
    violations.extend(check_forbidden_style(context))
    violations.extend(check_over_preachy(context))
    violations.extend(check_weak_boundary_in_correction(context))
    return tuple(_dedupe_violations(violations))


def inspect_memory_support(context: ReplyGuardContext) -> MemorySupportSnapshot:
    checked_ids = tuple(item.id for item in context.memory_result.selected_items)
    now = now_timestamp()
    relevant_items: list[MemoryItem] = []
    low_confidence = False
    has_profile = False
    has_expired = False
    for item in context.memory_result.selected_items:
        if item.is_expired(now):
            has_expired = True
            continue
        if item.memory_type == "profile":
            has_profile = True
        if item.confidence < 0.65:
            low_confidence = True
        if _memory_item_is_relevant(item, context):
            relevant_items.append(item)
    return MemorySupportSnapshot(
        checked_ids=checked_ids,
        relevant_ids=tuple(item.id for item in relevant_items),
        relevant_items=tuple(relevant_items),
        has_support=bool(relevant_items),
        has_low_confidence_support=low_confidence,
        has_profile_support=has_profile,
        has_expired_support=has_expired,
    )


def check_ai_self_disclosure(context: ReplyGuardContext) -> list[ReplyViolation]:
    for text in (context.raw_reply_text, context.reply_text):
        for pattern in AI_SELF_DISCLOSURE_PATTERNS:
            match = pattern.search(text)
            if match:
                return [
                    ReplyViolation(
                        rule_id="ai_self_disclosure.identity",
                        category="ai_self_disclosure",
                        severity="severe",
                        message="回复直接暴露了模型或程序身份。",
                        evidence_excerpt=safe_preview(match.group(0), 48),
                        should_block=True,
                        can_rewrite=False,
                    )
                ]
    return []


def check_fake_memory_claim(
    context: ReplyGuardContext,
    support: MemorySupportSnapshot,
) -> list[ReplyViolation]:
    text = context.reply_text
    matched = next(
        (pattern for pattern in MEMORY_STRONG_CLAIM_PATTERNS if pattern.search(text)),
        None,
    )
    if matched is None:
        return []

    violations: list[ReplyViolation] = []
    strong_generalization = bool(re.search(r"你(?:一直|总是|每次都|一向|本来就)", text))
    if not support.checked_ids:
        violations.append(
            ReplyViolation(
                rule_id="fake_memory_claim.no_support",
                category="fake_memory_claim",
                severity="severe",
                message="没有足够记忆依据却使用了强记忆口吻。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
                metadata={"memory_refs_checked": support.checked_ids},
            )
        )
        return violations

    if support.has_expired_support:
        violations.append(
            ReplyViolation(
                rule_id="fake_memory_claim.expired_support",
                category="fake_memory_claim",
                severity="severe",
                message="过期记忆不能支撑强记忆口吻。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
                metadata={"memory_refs_checked": support.checked_ids},
            )
        )
        return violations

    if not support.has_support:
        violations.append(
            ReplyViolation(
                rule_id="fake_memory_claim.irrelevant_support",
                category="fake_memory_claim",
                severity="medium",
                message="当前轮没有相关记忆依据，却硬提了旧事。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
                metadata={"memory_refs_checked": support.checked_ids},
            )
        )
        violations.append(
            ReplyViolation(
                rule_id="unnatural_memory_reference.irrelevant",
                category="unnatural_memory_reference",
                severity="medium",
                message="记忆引用与当前轮不自然相关。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=False,
                can_rewrite=True,
                metadata={"memory_refs_checked": support.checked_ids},
            )
        )
        return violations

    if strong_generalization and not support.has_profile_support:
        violations.append(
            ReplyViolation(
                rule_id="fake_memory_claim.overgeneralized",
                category="fake_memory_claim",
                severity="severe",
                message="把短期记忆或过期记忆说成了稳定事实。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
                metadata={"memory_refs_checked": support.relevant_ids},
            )
        )
        return violations

    if support.has_low_confidence_support:
        violations.append(
            ReplyViolation(
                rule_id="fake_memory_claim.low_confidence_overclaim",
                category="fake_memory_claim",
                severity="medium",
                message="低置信度记忆被说得过于确定。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
                metadata={"memory_refs_checked": support.relevant_ids},
            )
        )

    violations.append(
        ReplyViolation(
            rule_id="unnatural_memory_reference.strong_tone",
            category="unnatural_memory_reference",
            severity="light" if not support.has_low_confidence_support else "medium",
            message="记忆引用语气偏硬，应该弱化为自然相关的上下文引用。",
            evidence_excerpt=safe_preview(text, 72),
            should_block=False,
            can_rewrite=True,
            metadata={"memory_refs_checked": support.relevant_ids},
        )
    )
    return violations


def check_scene_conflict(context: ReplyGuardContext) -> list[ReplyViolation]:
    text = context.reply_text
    scene = context.scene
    bullet_count = _count_list_markers(text)
    violations: list[ReplyViolation] = []

    if scene == "comfort":
        if _contains_any(text, PREACHY_PATTERNS) or bullet_count >= 2:
            violations.append(
                ReplyViolation(
                    rule_id="scene_conflict.comfort_preachy",
                    category="scene_conflict",
                    severity="medium",
                    message="comfort 场景被写成了命令式建议或清单。",
                    evidence_excerpt=safe_preview(text, 72),
                    should_block=True,
                    can_rewrite=False,
                )
            )
        elif re.search(r"(从心理学角度|可以视为|认知反应|结构性问题)", text):
            violations.append(
                ReplyViolation(
                    rule_id="scene_conflict.comfort_cold_analysis",
                    category="scene_conflict",
                    severity="medium",
                    message="comfort 场景语气过冷、过分析。",
                    evidence_excerpt=safe_preview(text, 72),
                    should_block=True,
                    can_rewrite=False,
                )
            )

    if scene == "casual_chat" and (
        bullet_count >= 2 or re.search(r"(系统性地|重新规划|执行步骤|以下是)", text)
    ):
        violations.append(
            ReplyViolation(
                rule_id="scene_conflict.casual_too_heavy",
                category="scene_conflict",
                severity="medium",
                message="casual_chat 场景展开得过重。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
            )
        )

    if scene == "correction" and re.search(
        r"(都可以|没关系|不做也没关系|完全支持你先放掉|你开心就好)",
        text,
    ):
        violations.append(
            ReplyViolation(
                rule_id="scene_conflict.correction_too_soft",
                category="scene_conflict",
                severity="medium",
                message="correction 场景失去了应有边界。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
            )
        )

    if scene == "deep_discussion" and _contains_any(text, FLIPPANT_PATTERNS):
        violations.append(
            ReplyViolation(
                rule_id="scene_conflict.deep_discussion_flippant",
                category="scene_conflict",
                severity="medium",
                message="deep_discussion 场景语气过轻浮。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
            )
        )

    if scene == "greeting" and (
        bullet_count >= 1 or len(text) > 80 or _contains_any(text, TEMPLATE_PATTERNS)
    ):
        violations.append(
            ReplyViolation(
                rule_id="scene_conflict.greeting_too_long",
                category="scene_conflict",
                severity="light",
                message="简单问候被展开成模板话术。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=False,
                can_rewrite=True,
            )
        )

    return violations


def check_templated_tone(context: ReplyGuardContext) -> list[ReplyViolation]:
    text = context.reply_text
    matches = [pattern for pattern in TEMPLATE_PATTERNS if pattern in text]
    repeated_openers = _count_repeated_sentence_openers(text)
    encouragement_hits = sum(text.count(pattern) for pattern in EMPTY_ENCOURAGEMENT_PATTERNS)
    if (
        not matches
        and repeated_openers < 2
        and not _contains_any(text, CUSTOMER_SERVICE_PATTERNS)
        and encouragement_hits < 2
    ):
        return []

    severity = (
        "medium"
        if _contains_any(text, CUSTOMER_SERVICE_PATTERNS) or encouragement_hits >= 3
        else "light"
    )
    return [
        ReplyViolation(
            rule_id="templated_tone.detected",
            category="templated_tone",
            severity=severity,
            message="回复带有明显模板化或客服化腔调。",
            evidence_excerpt=safe_preview(text, 72),
            should_block=severity == "medium",
            can_rewrite=True,
        )
    ]


def check_overlong(context: ReplyGuardContext) -> list[ReplyViolation]:
    reply_length = len(context.reply_text)
    user_length = max(1, len(context.user_input.strip()))
    list_density = _count_list_markers(context.reply_text)
    ratio = reply_length / user_length

    if context.scene == "greeting":
        if reply_length <= max(40, context.runtime.max_reply_chars_soft_limit):
            return []
        return [
            ReplyViolation(
                rule_id="overlong.greeting_detected",
                category="overlong",
                severity="light",
                message="问候回复不该展开得太长。",
                evidence_excerpt=safe_preview(context.reply_text, 72),
                should_block=False,
                can_rewrite=True,
                metadata={"reply_length": reply_length, "input_length": user_length},
            )
        ]

    if (
        reply_length <= context.runtime.max_reply_chars_soft_limit
        and ratio <= 7
        and list_density < 2
    ):
        return []

    severity = (
        "medium"
        if reply_length > context.runtime.max_reply_chars_soft_limit * 1.4 or ratio > 12
        else "light"
    )
    return [
        ReplyViolation(
            rule_id="overlong.detected",
            category="overlong",
            severity=severity,
            message="回复对当前输入来说明显过长或结构过重。",
            evidence_excerpt=safe_preview(context.reply_text, 72),
            should_block=severity == "medium",
            can_rewrite=True,
            metadata={
                "reply_length": reply_length,
                "input_length": user_length,
                "ratio": round(ratio, 2),
            },
        )
    ]


def check_forbidden_style(context: ReplyGuardContext) -> list[ReplyViolation]:
    text = context.reply_text
    violations: list[ReplyViolation] = []

    if _contains_any(text, CUSTOMER_SERVICE_PATTERNS):
        violations.append(
            ReplyViolation(
                rule_id="forbidden_style.customer_service",
                category="forbidden_style",
                severity="medium",
                message="回复滑向客服式口吻。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=True,
            )
        )

    if re.search(r"(你一直都是这样|你就是这种性格|摆烂的性格)", text):
        violations.append(
            ReplyViolation(
                rule_id="forbidden_style.personality_attack",
                category="forbidden_style",
                severity="severe",
                message="回复对用户做了过强的人格化定性。",
                evidence_excerpt=safe_preview(text, 72),
                should_block=True,
                can_rewrite=False,
            )
        )
    return violations


def check_over_preachy(context: ReplyGuardContext) -> list[ReplyViolation]:
    preachy_hits = [pattern for pattern in PREACHY_PATTERNS if pattern in context.reply_text]
    if not preachy_hits:
        return []
    severity = "medium" if len(preachy_hits) >= 2 else "light"
    return [
        ReplyViolation(
            rule_id="over_preachy.detected",
            category="over_preachy",
            severity=severity,
            message="回复说教感过强。",
            evidence_excerpt=safe_preview(context.reply_text, 72),
            should_block=severity == "medium",
            can_rewrite=True,
        )
    ]


def check_weak_boundary_in_correction(context: ReplyGuardContext) -> list[ReplyViolation]:
    if context.scene != "correction":
        return []
    match = re.search(
        r"(都可以|不做也没关系|完全支持你(?:先)?放掉|你开心就好)",
        context.reply_text,
    )
    if not match:
        return []
    return [
        ReplyViolation(
            rule_id="weak_boundary_in_correction.detected",
            category="weak_boundary_in_correction",
            severity="medium",
            message="correction 场景边界过弱，容易纵容回避。",
            evidence_excerpt=safe_preview(match.group(0), 48),
            should_block=True,
            can_rewrite=False,
        )
    ]


def _memory_item_is_relevant(item: MemoryItem, context: ReplyGuardContext) -> bool:
    metadata = _parse_memory_metadata(item)
    if isinstance(metadata.get("relevant"), bool):
        return bool(metadata["relevant"])

    memory_text = item.display_text()
    needles = _extract_terms(memory_text)
    if not needles:
        return False
    haystack = f"{context.user_input} {context.reply_text}"
    return sum(1 for term in needles if term in haystack) >= 1


def _parse_memory_metadata(item: MemoryItem) -> dict[str, object]:
    if not item.metadata_json:
        return {}
    try:
        raw = json.loads(item.metadata_json)
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _extract_terms(text: str) -> tuple[str, ...]:
    ascii_terms = re.findall(r"[A-Za-z]{3,}", text)
    chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    stopwords = {"用户", "最近", "之前", "这个", "那个", "事情", "项目", "继续"}
    ordered: list[str] = []
    seen: set[str] = set()
    for term in ascii_terms + chinese_terms:
        if term in stopwords or len(term.strip()) < 2:
            continue
        if term in seen:
            continue
        seen.add(term)
        ordered.append(term)
        if not term.isascii() and len(term) > 2:
            for index in range(len(term) - 1):
                piece = term[index : index + 2]
                if piece in stopwords or piece in seen:
                    continue
                seen.add(piece)
                ordered.append(piece)
    return tuple(ordered[:16])


def _count_list_markers(text: str) -> int:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    count = 0
    for line in lines:
        if re.match(r"^(\d+\.\s|[-*]\s|第[一二三四五六七八九十])", line):
            count += 1
    return count


def _count_repeated_sentence_openers(text: str) -> int:
    sentences = re.split(r"[。！？!?]\s*", text)
    openers = [sentence[:6] for sentence in sentences if len(sentence.strip()) >= 6]
    if not openers:
        return 0
    return max(Counter(openers).values())


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _dedupe_violations(violations: list[ReplyViolation]) -> list[ReplyViolation]:
    by_category: dict[str, ReplyViolation] = {}
    rank = {"info": 0, "light": 1, "medium": 2, "severe": 3}
    for violation in violations:
        existing = by_category.get(violation.category)
        if existing is None or rank[violation.severity] > rank[existing.severity]:
            by_category[violation.category] = violation
    return list(by_category.values())
