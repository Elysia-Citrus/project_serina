from __future__ import annotations

import json

from src.app.command_router import CommandRouter
from src.assist_llm import AssistLLMService
from src.memory.admin import MemoryAdminService
from src.memory.manager import MemoryManager
from src.observability.trace_admin import TraceAdminService
from tests.regression.helpers import build_memory_item
from tests.regression.models import MemorySeed
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


def test_memory_command_router_lists_and_filters_memories() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path)
        manager = MemoryManager.from_app_config(config)
        manager.store.seed_items(  # type: ignore[union-attr]
            [
                build_memory_item(
                    MemorySeed(
                        id="profile-1",
                        memory_type="profile",
                        content="用户偏好被称呼为阿周。",
                        summary="用户偏好被称呼为阿周。",
                    )
                ),
                build_memory_item(
                    MemorySeed(
                        id="episodic-1",
                        memory_type="episodic",
                        content="用户近期事项：在做桌面 agent 的 memory guard 改造。",
                        summary="用户最近在做桌面 agent 的 memory guard 改造。",
                        ttl_days=7,
                        expires_in_hours=48,
                    )
                ),
            ]
        )
        router = CommandRouter(
            memory_review_enabled=True,
            memory_admin=MemoryAdminService(manager),
        )

        result = router.route("/memory list profile")

        assert result is not None and result.handled
        assert result.success is True
        assert "profile-1" in (result.output_text or "")
        assert "episodic-1" not in (result.output_text or "")
    finally:
        workspace.cleanup()


def test_memory_command_router_supports_update_pin_archive_and_delete() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path)
        manager = MemoryManager.from_app_config(config)
        manager.store.seed_items(  # type: ignore[union-attr]
            [
                build_memory_item(
                    MemorySeed(
                        id="profile-2",
                        memory_type="profile",
                        content="用户偏好被称呼为小周。",
                        summary="用户偏好被称呼为小周。",
                    )
                ),
                build_memory_item(
                    MemorySeed(
                        id="episodic-2",
                        memory_type="episodic",
                        content="用户近期事项：准备答辩。",
                        summary="用户最近在准备答辩。",
                        ttl_days=7,
                        expires_in_hours=48,
                    )
                ),
            ]
        )
        router = CommandRouter(
            memory_review_enabled=True,
            memory_admin=MemoryAdminService(manager),
        )

        pin_result = router.route("/memory pin profile-2")
        update_result = router.route(
            '/memory update profile-2 content="用户偏好被称呼为阿周。" confidence=0.95'
        )
        archive_result = router.route("/memory archive profile-2")
        expire_result = router.route("/memory expire episodic-2")
        delete_result = router.route("/memory delete episodic-2")

        assert pin_result is not None and pin_result.success
        assert update_result is not None and update_result.success
        assert archive_result is not None and archive_result.success
        assert expire_result is not None and expire_result.success
        assert delete_result is not None and delete_result.success

        updated = manager.get_memory("profile-2")
        deleted = manager.get_memory("episodic-2")
        assert updated is not None
        assert updated.pinned is True
        assert updated.content == "用户偏好被称呼为阿周。"
        assert updated.confidence == 0.95
        assert updated.status == "archived"
        assert deleted is None
    finally:
        workspace.cleanup()


def test_memory_command_router_respects_disabled_mode() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path, memory_review_enabled=False)
        manager = MemoryManager.from_app_config(config)
        router = CommandRouter(
            memory_review_enabled=False,
            memory_admin=MemoryAdminService(manager),
        )

        result = router.route("/memory list")

        assert result is not None and result.handled
        assert result.success is False
        assert "disabled" in (result.output_text or "")
    finally:
        workspace.cleanup()


def test_trace_summary_command_generates_assist_summary_from_log_file() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path)
        trace_file = workspace.root / "trace.jsonl"
        trace_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "event_name": "reply_guard_checked",
                            "turn_id": "turn-a",
                            "scene": "comfort",
                            "reply_guard_initial_action": "retry_once",
                            "reply_guard_final_action": "retry_once",
                            "reply_guard_violations": ["scene_conflict", "over_preachy"],
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "event_name": "assist_llm_call_failed",
                            "turn_id": "turn-a",
                            "assist_llm_task": "guard_retry_rewrite",
                            "assist_llm_error_type": "GatewayError",
                        },
                        ensure_ascii=False,
                    ),
                ]
            ),
            encoding="utf-8",
        )
        gateway = DummyGateway(
            [
                (
                    '{"summary":"Recent guard traces cluster around comfort-scene preachy retries.",'
                    '"common_patterns":["scene_conflict + over_preachy","assist retry failure"],'
                    '"recommended_focus":"Harden comfort rewrite prompts before adding more rules."}'
                )
            ]
        )
        trace_admin = TraceAdminService(
            assist_service=AssistLLMService.from_app_config(config, gateway),
            runtime=config.runtime,
            project_root=config.config_dir.parent.parent,
        )
        router = CommandRouter(
            memory_review_enabled=True,
            memory_admin=MemoryAdminService(MemoryManager.from_app_config(config)),
            trace_admin=trace_admin,
        )

        result = router.route(f'/trace summary --file "{trace_file}" --limit 5')

        assert result is not None and result.handled
        assert result.success is True
        assert "trace file:" in (result.output_text or "")
        assert "comfort-scene preachy retries" in (result.output_text or "")
    finally:
        workspace.cleanup()


def test_badcase_draft_command_builds_latest_turn_draft_from_log_file() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path)
        trace_file = workspace.root / "trace.jsonl"
        trace_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "event_name": "turn_received",
                            "turn_id": "turn-b",
                            "scene": "comfort",
                            "cleaned_input_preview": "我今天真的有点撑不住。",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "event_name": "dialogue_completed",
                            "turn_id": "turn-b",
                            "scene": "comfort",
                            "memory_selected_ids": ["memory-1"],
                            "response_preview": "你应该立刻停下内耗，按下面三步马上执行。",
                            "reply_guard_initial_action": "retry_once",
                            "reply_guard_final_action": "safe_fallback",
                            "reply_guard_initial_violations": [
                                "scene_conflict",
                                "over_preachy",
                            ],
                            "reply_guard_violations": ["scene_conflict", "over_preachy"],
                        },
                        ensure_ascii=False,
                    ),
                ]
            ),
            encoding="utf-8",
        )
        gateway = DummyGateway(
            [
                (
                    '{"case_id":"draft_turn-b","scene":"comfort","user_input":"我今天真的有点撑不住。",'
                    '"injected_memories":["memory-1"],'
                    '"assistant_reply":"你应该立刻停下内耗，按下面三步马上执行。",'
                    '"observed_violations":["scene_conflict","over_preachy"],'
                    '"suggested_expected_categories":["scene_conflict","over_preachy"],'
                    '"suggested_expected_action":"safe_fallback",'
                    '"reviewer_notes":"Please confirm whether this should stay severe."}'
                )
            ]
        )
        trace_admin = TraceAdminService(
            assist_service=AssistLLMService.from_app_config(config, gateway),
            runtime=config.runtime,
            project_root=config.config_dir.parent.parent,
        )
        router = CommandRouter(
            memory_review_enabled=True,
            memory_admin=MemoryAdminService(MemoryManager.from_app_config(config)),
            trace_admin=trace_admin,
        )

        result = router.route(f'/badcase draft latest --file "{trace_file}"')

        assert result is not None and result.handled
        assert result.success is True
        assert '"case_id": "draft_turn-b"' in (result.output_text or "")
        assert '"suggested_expected_action": "safe_fallback"' in (result.output_text or "")
    finally:
        workspace.cleanup()
