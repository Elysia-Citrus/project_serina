from __future__ import annotations

from datetime import timedelta

from src.app.coordinator import Coordinator
from src.dialogue.engine import DialogueEngine
from src.dialogue.reply_guard import ReplyGuard
from src.memory.manager import MemoryManager
from src.memory.models import (
    MemoryItem,
    MemoryReadResult,
    MemoryTurnInput,
    format_timestamp,
    now_timestamp,
)
from src.memory.rules import format_memory_for_prompt
from tests.regression.models import MemorySeed, RegressionCase
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


def build_memory_item(seed: MemorySeed):
    now = now_timestamp()
    created_at = now - timedelta(hours=seed.created_hours_ago)
    updated_at = now - timedelta(hours=seed.updated_hours_ago)
    expires_at = None
    if seed.expires_in_hours is not None:
        expires_at = format_timestamp(now + timedelta(hours=seed.expires_in_hours))
    elif seed.ttl_days is not None and seed.status == "active":
        expires_at = format_timestamp(now + timedelta(days=seed.ttl_days))
    elif seed.status == "expired":
        expires_at = format_timestamp(now - timedelta(hours=1))

    followup_due_at = None
    if seed.followup_due_in_hours is not None:
        followup_due_at = format_timestamp(now + timedelta(hours=seed.followup_due_in_hours))

    last_followup_at = None
    if seed.last_followup_hours_ago is not None:
        last_followup_at = format_timestamp(now - timedelta(hours=seed.last_followup_hours_ago))

    return MemoryItem(
        id=seed.id,
        memory_type=seed.memory_type,  # type: ignore[arg-type]
        content=seed.content,
        source_turn=seed.source_turn,
        source_message_excerpt=seed.source_message_excerpt or seed.content[:40],
        created_at=format_timestamp(created_at),
        updated_at=format_timestamp(updated_at),
        confidence=seed.confidence,
        ttl_days=seed.ttl_days,
        expires_at=expires_at,
        decay_policy="ttl_expiry" if seed.memory_type == "episodic" else "manual_override",
        status=seed.status,  # type: ignore[arg-type]
        dedupe_key=seed.dedupe_key,
        topic_key=seed.topic_key,
        tags=seed.tags,
        summary=seed.summary,
        pinned=seed.pinned,
        merge_count=seed.merge_count,
        followup_enabled=seed.followup_enabled,
        followup_due_at=followup_due_at,
        last_followup_at=last_followup_at,
    )


def build_memory_read_result(case: RegressionCase) -> MemoryReadResult:
    selected_ids = set(case.expected_injected_memory_ids)
    if not selected_ids:
        return MemoryReadResult()

    selected_items = tuple(
        build_memory_item(seed)
        for seed in case.existing_memories
        if seed.id in selected_ids
    )
    return MemoryReadResult(
        selected_items=selected_items,
        prompt_items=tuple(format_memory_for_prompt(item) for item in selected_items),
    )


def seed_memories(memory_manager: MemoryManager, memories: tuple[MemorySeed, ...]) -> None:
    if not memories or memory_manager.store is None:
        return
    memory_manager.store.seed_items(build_memory_item(seed) for seed in memories)


def build_memory_manager(
    workspace: TemporaryWorkspace,
    **config_kwargs: object,
) -> tuple[MemoryManager, object]:
    config = build_test_config(workspace.db_path, **config_kwargs)
    return MemoryManager.from_app_config(config), config


def build_reply_guard(
    workspace: TemporaryWorkspace,
    **config_kwargs: object,
) -> ReplyGuard:
    config = build_test_config(workspace.db_path, **config_kwargs)
    return ReplyGuard(
        config.runtime,
        config.persona,
        config.policy,
    )


def run_flow_case(
    workspace: TemporaryWorkspace,
    case: RegressionCase,
    **config_kwargs: object,
):
    config = build_test_config(workspace.db_path, **config_kwargs)
    memory_manager = MemoryManager.from_app_config(config)
    seed_memories(memory_manager, case.existing_memories)
    gateway = DummyGateway(list(case.gateway_responses))
    engine = DialogueEngine(config, gateway, memory_manager=memory_manager)
    coordinator = Coordinator(config, engine=engine)
    coordinator.session.history.extend([dict(message) for message in case.input_history])
    result = coordinator.process_user_message(case.user_input)
    return result, coordinator, gateway, memory_manager


def build_turn_input(case: RegressionCase) -> MemoryTurnInput:
    return MemoryTurnInput(
        user_input=case.user_input,
        assistant_reply="",
        scene=case.scene or "casual_chat",
        turn_id=case.case_id,
    )
