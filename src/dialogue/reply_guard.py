from __future__ import annotations

from dataclasses import dataclass
import re

from src.config.loader import PersonaConfig, PolicyConfig, RuntimeConfig
from src.memory.models import MemoryReadResult
from src.utils.text_utils import (
    ensure_non_empty_text,
    normalize_whitespace,
    safe_preview,
    strip_ai_disclaimer,
    strip_known_role_prefixes,
)


AI_DECLARATION_PATTERNS = (
    r"作为(?:一个)?(?:ai|人工智能|语言模型)",
    r"我是(?:一个)?(?:ai|人工智能|语言模型)",
    r"作为(?:数字|智能)?助手",
)

PREACHY_PATTERNS = (
    r"你应该",
    r"建议你",
    r"最好",
    r"必须",
    r"立刻",
    r"马上",
)

UNSUPPORTED_MEMORY_PATTERNS = (
    r"我记得你(?:之前|上次|前面)",
    r"你之前说过",
    r"上次你提到",
    r"我还记得你",
)

TEMPLATE_PATTERNS = (
    r"首先.{0,40}其次",
    r"第一.{0,40}第二",
    r"1\.\s.*2\.\s",
)

CUSTOMER_SERVICE_PATTERNS = (
    r"您好",
    r"很高兴为你服务",
    r"请问还有什么可以帮",
    r"感谢你的理解",
    r"祝你(?:生活|今天).*(?:愉快|顺利)",
)

CASUAL_HEAVY_PATTERNS = (
    r"人生的本质",
    r"命运",
    r"终极",
    r"深刻地说明",
)

CORRECTION_AVOIDANCE_PATTERNS = (
    r"都行",
    r"你开心就好",
    r"我不评价",
    r"算了吧",
)

SOFTEN_REWRITES = (
    ("你应该", "你可以先"),
    ("建议你", "你可以考虑"),
    ("最好", "也许更合适"),
    ("必须", "得先"),
    ("立刻", "先"),
    ("马上", "先"),
)


@dataclass(frozen=True)
class ReplyViolation:
    code: str
    severity: int
    reason: str


@dataclass(frozen=True)
class ReplyGuardDecision:
    action: str
    final_text: str | None
    violations: tuple[ReplyViolation, ...]
    retry_instructions: tuple[str, ...] = ()

    @property
    def triggered(self) -> bool:
        return bool(self.violations)

    @property
    def violation_codes(self) -> tuple[str, ...]:
        return tuple(violation.code for violation in self.violations)


class ReplyGuard:
    def __init__(
        self,
        runtime: RuntimeConfig,
        persona: PersonaConfig,
        policy: PolicyConfig,
    ) -> None:
        self.runtime = runtime
        self.persona = persona
        self.policy = policy

    def evaluate(
        self,
        *,
        reply_text: str,
        user_input: str,
        scene: str,
        memory_result: MemoryReadResult,
        allow_retry: bool,
    ) -> ReplyGuardDecision:
        if not self.runtime.reply_guard_enabled:
            return ReplyGuardDecision(action="accept", final_text=reply_text, violations=())

        violations = tuple(
            self._collect_violations(
                reply_text=reply_text,
                user_input=user_input,
                scene=scene,
                memory_result=memory_result,
            )
        )
        if not violations:
            return ReplyGuardDecision(action="accept", final_text=reply_text, violations=())

        max_severity = max(violation.severity for violation in violations)
        severity_sum = sum(violation.severity for violation in violations)

        if max_severity >= 3 or severity_sum >= 5:
            return ReplyGuardDecision(
                action="safe_fallback",
                final_text=self._safe_fallback(scene),
                violations=violations,
            )

        if max_severity >= 2:
            if allow_retry and self.runtime.reply_guard_retry_once:
                return ReplyGuardDecision(
                    action="retry",
                    final_text=None,
                    violations=violations,
                    retry_instructions=self._build_retry_instructions(violations, scene),
                )
            return ReplyGuardDecision(
                action="safe_fallback",
                final_text=self._safe_fallback(scene),
                violations=violations,
            )

        rewritten = self._rewrite_reply(reply_text, scene=scene)
        return ReplyGuardDecision(
            action="rewrite",
            final_text=rewritten,
            violations=violations,
        )

    def _collect_violations(
        self,
        *,
        reply_text: str,
        user_input: str,
        scene: str,
        memory_result: MemoryReadResult,
    ) -> list[ReplyViolation]:
        normalized = normalize_whitespace(reply_text)
        compact = normalized.replace(" ", "")
        violations: list[ReplyViolation] = []

        if _has_pattern_hit(compact, AI_DECLARATION_PATTERNS):
            violations.append(
                ReplyViolation(
                    code="ai_self_disclosure",
                    severity=1,
                    reason="detected_ai_self_disclosure",
                )
            )

        if _has_pattern_hit(compact, UNSUPPORTED_MEMORY_PATTERNS):
            if not memory_result.hit:
                violations.append(
                    ReplyViolation(
                        code="unsupported_memory_claim",
                        severity=2,
                        reason="reply_claims_memory_without_selected_memory",
                    )
                )
            else:
                violations.append(
                    ReplyViolation(
                        code="memory_overclaim_tone",
                        severity=1,
                        reason="reply_uses_overstrong_memory_tone",
                    )
                )

        if _has_pattern_hit(compact, CUSTOMER_SERVICE_PATTERNS):
            violations.append(
                ReplyViolation(
                    code="forbidden_style_customer_service",
                    severity=2,
                    reason="reply_slipped_into_customer_service_tone",
                )
            )

        if self._looks_preachy(normalized, scene=scene):
            violations.append(
                ReplyViolation(
                    code="preachy_tone",
                    severity=2 if scene == "comfort" else 1,
                    reason="reply_is_too_advice_heavy_for_scene",
                )
            )

        if _has_pattern_hit(normalized, TEMPLATE_PATTERNS):
            violations.append(
                ReplyViolation(
                    code="template_style",
                    severity=1,
                    reason="reply_looks_templated",
                )
            )

        if self._has_scene_conflict(normalized, scene=scene):
            violations.append(
                ReplyViolation(
                    code="scene_conflict",
                    severity=2,
                    reason="reply_style_conflicts_with_scene",
                )
            )

        if self._is_too_long(normalized, user_input=user_input, scene=scene):
            severity = 2 if len(normalized) > int(self._reply_soft_limit * 1.5) else 1
            violations.append(
                ReplyViolation(
                    code="too_long",
                    severity=severity,
                    reason="reply_is_too_long_for_current_turn",
                )
            )

        if self._hits_persona_forbidden_style(normalized):
            violations.append(
                ReplyViolation(
                    code="persona_forbidden_style",
                    severity=2,
                    reason="reply_matches_persona_forbidden_style",
                )
            )
        return violations

    def _looks_preachy(self, text: str, *, scene: str) -> bool:
        if not _has_pattern_hit(text, PREACHY_PATTERNS):
            return False
        return scene in {"comfort", "casual_chat", "greeting"}

    def _has_scene_conflict(self, text: str, *, scene: str) -> bool:
        if scene == "comfort":
            return _has_pattern_hit(text, TEMPLATE_PATTERNS) or _has_pattern_hit(
                text, PREACHY_PATTERNS
            )
        if scene == "casual_chat":
            return _has_pattern_hit(text, CASUAL_HEAVY_PATTERNS)
        if scene == "correction":
            return _has_pattern_hit(text, CORRECTION_AVOIDANCE_PATTERNS)
        return False

    def _is_too_long(self, text: str, *, user_input: str, scene: str) -> bool:
        scene_limit = self._reply_soft_limit
        if scene == "greeting":
            scene_limit = min(scene_limit, 80)
        elif scene == "casual_chat":
            scene_limit = min(scene_limit, 140)
        elif scene == "comfort":
            scene_limit = max(140, min(scene_limit, 220))

        dynamic_limit = max(scene_limit, len(normalize_whitespace(user_input)) * 4)
        return len(text) > dynamic_limit

    def _hits_persona_forbidden_style(self, text: str) -> bool:
        forbidden_styles = " ".join(self.persona.forbidden_styles + self.policy.output_guardrails)
        if "客服" in forbidden_styles and _has_pattern_hit(text, CUSTOMER_SERVICE_PATTERNS):
            return True
        if "说教" in forbidden_styles and _has_pattern_hit(text, PREACHY_PATTERNS):
            return True
        if "模板化安慰" in forbidden_styles and _has_pattern_hit(text, TEMPLATE_PATTERNS):
            return True
        return False

    def _rewrite_reply(self, reply_text: str, *, scene: str) -> str:
        rewritten = normalize_whitespace(reply_text)
        rewritten = strip_known_role_prefixes(rewritten)
        rewritten = strip_ai_disclaimer(rewritten)

        for pattern in CUSTOMER_SERVICE_PATTERNS:
            rewritten = re.sub(pattern, "", rewritten, flags=re.IGNORECASE)
        for pattern in TEMPLATE_PATTERNS:
            rewritten = re.sub(pattern, "", rewritten, flags=re.IGNORECASE | re.DOTALL)
        for source, target in SOFTEN_REWRITES:
            rewritten = rewritten.replace(source, target)

        rewritten = re.sub(
            r"(我记得你(?:之前|上次|前面)|你之前说过|上次你提到|我还记得你)",
            "听起来",
            rewritten,
            flags=re.IGNORECASE,
        )
        rewritten = _flatten_list_markers(rewritten)
        rewritten = _trim_to_limit(rewritten, self._reply_soft_limit)
        rewritten = normalize_whitespace(rewritten)
        return ensure_non_empty_text(rewritten, self._safe_fallback(scene))

    @property
    def _reply_soft_limit(self) -> int:
        return getattr(self.runtime, "max_reply_chars_soft_limit", self.runtime.max_reply_chars)

    def _build_retry_instructions(
        self,
        violations: tuple[ReplyViolation, ...],
        scene: str,
    ) -> tuple[str, ...]:
        codes = {violation.code for violation in violations}
        instructions = [
            "这是一次保守重试，只输出更自然、更短的最终回复。",
            "不要自称 AI、助手、模型，不要解释系统过程。",
            "没有足够依据时，不要说“我记得你之前……”或假装记得。",
            f"保持与当前场景 `{scene}` 一致，不要跑偏。",
        ]
        if "preachy_tone" in codes:
            instructions.append("避免居高临下或训诫口吻，少用“你应该/建议你”。")
        if "too_long" in codes or "template_style" in codes:
            instructions.append("用自然短段落，不要列模板化清单。")
        return tuple(instructions)

    def _safe_fallback(self, scene: str) -> str:
        if scene == "comfort":
            return "我在，先别把自己逼太紧。你要是愿意，可以慢慢跟我说。"
        if scene == "correction":
            return "这件事我不想糊弄你。问题确实在那儿，但我们可以一点点拆开。"
        if scene == "deep_discussion":
            return "我先说结论：这件事值得认真想，但别急着把话说满。你想先从哪个点展开？"
        if scene == "greeting":
            return "老师，我在。你想先从哪句开始都行。"
        return "老师，我在。你继续说，我跟着你。"


def summarize_guard_decision(decision: ReplyGuardDecision) -> dict[str, object]:
    return {
        "action": decision.action,
        "triggered": decision.triggered,
        "violations": [violation.code for violation in decision.violations],
        "preview": safe_preview(decision.final_text or "", 80),
    }


def _has_pattern_hit(text: str, patterns: tuple[str, ...]) -> bool:
    return any(
        re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        for pattern in patterns
    )


def _flatten_list_markers(text: str) -> str:
    flattened = re.sub(r"(?m)^\s*[-*]\s*", "", text)
    flattened = re.sub(r"(?m)^\s*\d+\.\s*", "", flattened)
    return flattened


def _trim_to_limit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut_points = [window.rfind(symbol) for symbol in "。！？!?"]
    cut_at = max(cut_points)
    if cut_at >= int(limit * 0.6):
        return window[: cut_at + 1]
    return f"{window.rstrip()}……"
