from __future__ import annotations

import re

from src.dialogue.reply_guard.checks import (
    CUSTOMER_SERVICE_PATTERNS,
    TEMPLATE_PATTERNS,
    inspect_memory_support,
    run_checks,
)
from src.dialogue.reply_guard.models import (
    ReplyGuardAssessment,
    ReplyGuardContext,
    ReplyGuardDecision,
    ReplyViolation,
)
from src.utils.text_utils import normalize_whitespace


def build_accept_decision(
    assessment: ReplyGuardAssessment,
    context: ReplyGuardContext,
    violations: tuple[ReplyViolation, ...] = (),
) -> ReplyGuardDecision:
    support = inspect_memory_support(context)
    return ReplyGuardDecision(
        initial_action="accept",
        final_action="accept",
        final_text=context.reply_text,
        violations=violations,
        assessment=assessment,
        memory_refs_checked=support.checked_ids,
    )


def build_rewrite_decision(
    assessment: ReplyGuardAssessment,
    context: ReplyGuardContext,
    violations: tuple[ReplyViolation, ...],
) -> ReplyGuardDecision:
    rewritten = rewrite_reply(context)
    rewritten_context = ReplyGuardContext(
        reply_text=rewritten,
        raw_reply_text=rewritten,
        user_input=context.user_input,
        scene=context.scene,
        memory_result=context.memory_result,
        runtime=context.runtime,
        persona=context.persona,
        policy=context.policy,
    )
    rewritten_violations = run_checks(rewritten_context)
    if any(violation.severity in {"medium", "severe"} for violation in rewritten_violations):
        return ReplyGuardDecision(
            initial_action="rewrite",
            final_action="safe_fallback",
            final_text=build_safe_fallback(context),
            violations=violations,
            assessment=assessment,
            rewrite_used=True,
            fallback_reason="rewrite_still_violating",
            memory_refs_checked=inspect_memory_support(context).checked_ids,
        )

    return ReplyGuardDecision(
        initial_action="rewrite",
        final_action="accept",
        final_text=rewritten,
        violations=violations,
        assessment=assessment,
        rewrite_used=True,
        memory_refs_checked=inspect_memory_support(context).checked_ids,
    )


def build_retry_decision(
    assessment: ReplyGuardAssessment,
    context: ReplyGuardContext,
    violations: tuple[ReplyViolation, ...],
) -> ReplyGuardDecision:
    return ReplyGuardDecision(
        initial_action="retry_once",
        final_action="retry_once",
        final_text=None,
        violations=violations,
        assessment=assessment,
        retry_instructions=build_retry_instructions(context, assessment),
        memory_refs_checked=inspect_memory_support(context).checked_ids,
    )


def build_fallback_decision(
    assessment: ReplyGuardAssessment,
    context: ReplyGuardContext,
    violations: tuple[ReplyViolation, ...],
    *,
    reason: str | None = None,
) -> ReplyGuardDecision:
    return ReplyGuardDecision(
        initial_action="safe_fallback",
        final_action="safe_fallback",
        final_text=build_safe_fallback(context),
        violations=violations,
        assessment=assessment,
        fallback_reason=reason or _default_fallback_reason(assessment),
        memory_refs_checked=inspect_memory_support(context).checked_ids,
    )


def rewrite_reply(context: ReplyGuardContext) -> str:
    reply = context.reply_text
    reply = _remove_ai_identity(reply)
    reply = _remove_customer_service_openers(reply)
    reply = _remove_template_structure(reply)
    reply = _soften_memory_reference(reply, context)
    reply = _trim_list_payload(reply, context)
    reply = _trim_to_soft_limit(reply, context)
    reply = normalize_whitespace(reply)
    if not reply:
        return build_safe_fallback(context)

    if context.scene == "greeting":
        first = _first_sentence(reply)
        return first or build_safe_fallback(context)
    if context.scene == "comfort" and len(reply) < 8:
        return "先别急着逼自己，缓一缓也可以。"
    if context.scene == "casual_chat" and len(reply) < 6:
        return "慢一点也行，先别把自己绷太紧。"
    return reply


def build_retry_instructions(
    context: ReplyGuardContext,
    assessment: ReplyGuardAssessment,
) -> tuple[str, ...]:
    instructions = [
        "只保留自然私聊口吻，不要暴露模型或程序身份。",
        "记忆块只是可用上下文；没有足够依据时，不要说“我记得你之前……”。",
    ]
    if context.scene == "comfort":
        instructions.append("先接住情绪，不要上来分点说教或冷分析。")
    elif context.scene == "casual_chat":
        instructions.append("保持轻松短句，不要展开成长篇规划或客服式建议。")
    elif context.scene == "correction":
        instructions.append("要有边界，但不要训人；指出逃避点后给出最小下一步。")
    elif context.scene == "deep_discussion":
        instructions.append("认真回应问题，不要轻浮敷衍，也不要机械大纲化。")
    elif context.scene == "greeting":
        instructions.append("只做简短自然的问候，不要延展成长篇模板。")

    if (
        "fake_memory_claim" in assessment.categories
        or "unnatural_memory_reference" in assessment.categories
    ):
        instructions.append("只有当前轮自然相关且证据充分时才可轻描淡写地引用记忆，否则直接不提。")
    return tuple(instructions)


def build_safe_fallback(context: ReplyGuardContext) -> str:
    scene = context.scene
    if scene == "comfort":
        return "我在。先别硬撑，我们就从眼前这一点慢慢理。"
    if scene == "correction":
        return "这事别再顺手往后拖了。先把最小那一步做掉，我们再往下接。"
    if scene == "deep_discussion":
        return "我更想认真接住这个问题。你要是愿意，我们就从最刺你的那一点说起。"
    if scene == "greeting":
        return "我在。"
    return "我在，接着说。"


def _remove_ai_identity(text: str) -> str:
    patterns = (
        r"作为\s*(?:一个)?\s*(?:AI|人工智能|语言模型|程序|模型)[，,、 ]*",
        r"我是\s*(?:一个)?\s*(?:AI|人工智能|语言模型|程序|模型)[，,、 ]*",
        r"我只是\s*(?:一个)?\s*(?:程序|模型|语言模型)[，,、 ]*",
        r"所以这类问题我只能从(?:数据|语料)角度回答[，,、 ]*",
    )
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned


def _remove_customer_service_openers(text: str) -> str:
    cleaned = text
    for opener in CUSTOMER_SERVICE_PATTERNS:
        cleaned = cleaned.replace(opener, "")
    cleaned = re.sub(r"请问还有什么可以帮你[吗嘛？?]?", "", cleaned)
    cleaned = re.sub(r"感谢你的理解。?", "", cleaned)
    return cleaned.strip("，,。 ")


def _remove_template_structure(text: str) -> str:
    cleaned = text
    for marker in TEMPLATE_PATTERNS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"^1\.\s*", "", cleaned)
    cleaned = re.sub(r"^2\.\s*", "", cleaned)
    cleaned = re.sub(r"^3\.\s*", "", cleaned)
    cleaned = re.sub(r"第[一二三四五六七八九十][，、:\s]*", "", cleaned)
    return cleaned.strip()


def _soften_memory_reference(text: str, context: ReplyGuardContext) -> str:
    if re.search(r"还是叫我(.+?)吧", context.user_input):
        match = re.search(r"还是叫我(.+?)吧", context.user_input)
        if match:
            return f"好，那我就叫你{match.group(1)}。"

    if re.search(r"(我记得你之前|我记得你以前|我记得你前两天|我记得你上次)", text):
        if context.memory_result.selected_items:
            first_memory = context.memory_result.selected_items[0].display_text()
            if any(keyword in first_memory for keyword in ("累", "疲", "休息")):
                return "你这两天本来就挺累，今晚稍微松一点也正常。"
        text = re.sub(r"我记得你(?:之前|以前|前两天|上次)", "", text)

    text = re.sub(r"你(?:一直|总是|每次都|一向|本来就)", "这阵子你", text)
    text = re.sub(r"很确定", "大概", text)
    return text.strip("，,。 ")


def _trim_list_payload(text: str, context: ReplyGuardContext) -> str:
    if context.scene == "greeting":
        return _first_sentence(text)
    if re.search(r"(第一|第二|第三|\d+\.)", text):
        sentences = _sentences(text)
        if sentences:
            return "。".join(sentences[:2]).strip("。") + "。"
    return text


def _trim_to_soft_limit(text: str, context: ReplyGuardContext) -> str:
    limit = context.runtime.max_reply_chars_soft_limit
    if len(text) <= limit:
        return text
    sentences = _sentences(text)
    trimmed: list[str] = []
    total = 0
    for sentence in sentences:
        if not sentence:
            continue
        next_total = total + len(sentence)
        if trimmed and next_total > limit:
            break
        trimmed.append(sentence)
        total = next_total
        if total >= limit:
            break
    if trimmed:
        return "。".join(trimmed).strip("。") + "。"
    return text[: limit - 1].rstrip("，,。 ") + "。"


def _first_sentence(text: str) -> str:
    sentences = _sentences(text)
    if not sentences:
        return ""
    return sentences[0].strip("。") + "。"


def _sentences(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"[。！？!?]\s*", text) if segment.strip()]


def _default_fallback_reason(assessment: ReplyGuardAssessment) -> str:
    if "ai_self_disclosure" in assessment.categories:
        return "ai_self_disclosure"
    if "fake_memory_claim" in assessment.categories:
        return "fake_memory_claim"
    return "guard_severe"
