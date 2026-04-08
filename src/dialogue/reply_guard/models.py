from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.config.loader import PersonaConfig, PolicyConfig, RuntimeConfig
from src.memory.models import MemoryReadResult


ViolationSeverity = Literal["info", "light", "medium", "severe"]
GuardAction = Literal["accept", "rewrite", "retry_once", "safe_fallback"]


@dataclass(frozen=True)
class ReplyViolation:
    rule_id: str
    category: str
    severity: ViolationSeverity
    message: str
    evidence_excerpt: str
    should_block: bool
    can_rewrite: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplyGuardAssessment:
    severity: Literal["none", "light", "medium", "severe"]
    suggested_action: GuardAction
    categories: tuple[str, ...]
    blocking_categories: tuple[str, ...]
    scene: str
    case_like_signature: str


@dataclass(frozen=True)
class ReplyGuardDecision:
    initial_action: GuardAction
    final_action: GuardAction
    final_text: str | None
    violations: tuple[ReplyViolation, ...] = ()
    assessment: ReplyGuardAssessment | None = None
    retry_instructions: tuple[str, ...] = ()
    rewrite_used: bool = False
    retry_used: bool = False
    fallback_reason: str | None = None
    memory_refs_checked: tuple[str, ...] = ()

    @property
    def action(self) -> GuardAction:
        return self.final_action

    @property
    def triggered(self) -> bool:
        return bool(self.violations)

    @property
    def violation_codes(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for violation in self.violations:
            if violation.category in seen:
                continue
            seen.add(violation.category)
            ordered.append(violation.category)
        return tuple(ordered)


@dataclass(frozen=True)
class ReplyGuardContext:
    reply_text: str
    raw_reply_text: str
    user_input: str
    scene: str
    memory_result: MemoryReadResult
    runtime: RuntimeConfig
    persona: PersonaConfig
    policy: PolicyConfig
