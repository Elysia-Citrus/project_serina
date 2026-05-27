from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.memory.manager import MemoryManager
from src.memory.models import MemoryItem, now_timestamp, parse_timestamp
from src.observability.trace import TurnTrace
from src.utils.logger import log_event


@dataclass(frozen=True)
class FollowUpCandidate:
    memory_id: str
    due_at: str | None
    summary: str
    reason: str


@dataclass(frozen=True)
class FollowUpScanResult:
    accepted: tuple[FollowUpCandidate, ...] = ()
    rejected: tuple[dict[str, str], ...] = ()
    skipped_reason: str | None = None


class FollowUpSchedulerAdapter:
    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        enabled: bool,
        cooldown_hours: int,
    ) -> None:
        self.memory_manager = memory_manager
        self.enabled = enabled
        self.cooldown_hours = max(6, cooldown_hours)

    def collect_candidates(
        self,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
        limit: int = 3,
    ) -> FollowUpScanResult:
        if not self.enabled:
            result = FollowUpScanResult(skipped_reason="followup_scheduler_disabled")
            log_event(
                "followup_candidate_scan_skipped",
                level="DEBUG",
                turn_trace=turn_trace,
                skipped_reason=result.skipped_reason,
            )
            return result

        current_time = now or now_timestamp()
        accepted: list[FollowUpCandidate] = []
        rejected: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        candidate_memories = list(
            self.memory_manager.list_memories(
                memory_class="task",
                status="active",
                review_states=("active",),
            )
        ) + list(
            self.memory_manager.list_memories(
                memory_type="episodic",
                memory_class="episodic",
                status="active",
                review_states=("active",),
            )
        )
        for memory in candidate_memories:
            if memory.id in seen_ids:
                continue
            seen_ids.add(memory.id)
            accepted_candidate, rejection_reason = self._evaluate_memory(
                memory,
                now=current_time,
            )
            if accepted_candidate is not None:
                accepted.append(accepted_candidate)
            else:
                rejected.append(
                    {
                        "id": memory.id,
                        "reason": rejection_reason or "unknown",
                    }
                )

        accepted.sort(
            key=lambda candidate: candidate.due_at or "",
        )
        result = FollowUpScanResult(
            accepted=tuple(accepted[:limit]),
            rejected=tuple(rejected),
        )
        log_event(
            "followup_candidate_scan_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            accepted_candidates=[
                {
                    "id": candidate.memory_id,
                    "due_at": candidate.due_at,
                    "reason": candidate.reason,
                }
                for candidate in result.accepted
            ],
            rejected_candidates=list(result.rejected[:10]),
            skipped_reason=result.skipped_reason,
        )
        return result

    def _evaluate_memory(
        self,
        memory: MemoryItem,
        *,
        now: datetime,
    ) -> tuple[FollowUpCandidate | None, str | None]:
        if not memory.followup_enabled:
            return None, "followup_not_enabled"
        if memory.is_expired(now):
            return None, "memory_expired"
        if memory.followup_due_at is not None and parse_timestamp(memory.followup_due_at) > now:
            return None, "followup_not_due"
        if memory.last_followup_at is not None:
            if parse_timestamp(memory.last_followup_at) > now - timedelta(hours=self.cooldown_hours):
                return None, "followup_cooldown"
        return (
            FollowUpCandidate(
                memory_id=memory.id,
                due_at=memory.followup_due_at,
                summary=memory.display_text(),
                reason="explicit_followup_memory",
            ),
            None,
        )
