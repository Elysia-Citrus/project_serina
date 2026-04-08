from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.config.loader import AppConfig
from src.memory.manager import MemoryManager
from src.observability.trace import TurnTrace
from src.scheduler.followup_adapter import FollowUpScanResult, FollowUpSchedulerAdapter


@dataclass(frozen=True)
class SchedulerManager:
    followup_adapter: FollowUpSchedulerAdapter

    @classmethod
    def from_app_config(
        cls,
        app_config: AppConfig,
        memory_manager: MemoryManager,
    ) -> "SchedulerManager":
        return cls(
            followup_adapter=FollowUpSchedulerAdapter(
                memory_manager,
                enabled=app_config.runtime.followup_scheduler_enabled,
                cooldown_hours=app_config.runtime.followup_cooldown_hours,
            )
        )

    def collect_followup_candidates(
        self,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
        limit: int = 3,
    ) -> FollowUpScanResult:
        return self.followup_adapter.collect_candidates(
            turn_trace=turn_trace,
            now=now,
            limit=limit,
        )
