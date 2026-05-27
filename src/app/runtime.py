from __future__ import annotations

from dataclasses import dataclass

from src.app.command_router import CommandRouter
from src.app.coordinator import Coordinator
from src.app.ui_adapter import TerminalUIAdapter
from src.config.loader import AppConfig
from src.memory.admin import MemoryAdminService
from src.observability.trace_admin import TraceAdminService


@dataclass(frozen=True)
class AppRuntime:
    config: AppConfig
    ui: TerminalUIAdapter
    coordinator: Coordinator
    command_router: CommandRouter


def build_app_runtime(config: AppConfig) -> AppRuntime:
    ui = TerminalUIAdapter(
        assistant_label=config.persona.name,
        user_label=config.persona.user_name,
    )
    coordinator = Coordinator(config)
    return AppRuntime(
        config=config,
        ui=ui,
        coordinator=coordinator,
        command_router=build_command_router(config, coordinator),
    )


def build_command_router(config: AppConfig, coordinator: Coordinator) -> CommandRouter:
    trace_admin = TraceAdminService(
        assist_service=coordinator.engine.assist_service,
        runtime=config.runtime,
        project_root=config.config_dir.parent.parent,
    )
    return CommandRouter(
        memory_review_enabled=config.runtime.memory_review_enabled,
        memory_admin=MemoryAdminService(coordinator.memory_service),
        trace_admin=trace_admin,
    )

