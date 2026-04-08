from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.config.loader import (
    AppConfig,
    CorrectionStyleConfig,
    PersonaConfig,
    PolicyConfig,
    RelationshipStyleConfig,
    RuntimeConfig,
)
from src.llm.gateway import GatewayResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TemporaryWorkspace:
    def __init__(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.db_path = self.root / "serina_test.db"

    def cleanup(self) -> None:
        self._temp_dir.cleanup()


class DummyGateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate(self, messages, turn_trace=None, options=None) -> GatewayResponse:  # type: ignore[no-untyped-def]
        if not self.responses:
            raise AssertionError("DummyGateway has no more queued responses.")
        text = self.responses.pop(0)
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "options": options,
            }
        )
        return GatewayResponse(
            text=text,
            provider_name="mock",
            model_name="mock-model",
            latency_ms=12,
        )


def build_test_config(
    db_path: Path,
    *,
    memory_enabled: bool = True,
    memory_write_enabled: bool = True,
    reply_guard_enabled: bool = True,
    reply_guard_retry_once: bool = True,
    max_memory_injection_items: int = 3,
    episodic_memory_ttl_days: int = 7,
    merge_time_window_hours: int = 72,
    memory_review_enabled: bool = True,
    followup_scheduler_enabled: bool = True,
    followup_cooldown_hours: int = 24,
    max_reply_chars: int = 180,
) -> AppConfig:
    persona = PersonaConfig(
        name="Serina",
        user_name="老师",
        language="zh-CN",
        self_concept="你是 Serina。",
        welcome_message="老师，我在。",
        core_traits=["温柔", "稳定"],
        relationship_style=RelationshipStyleConfig(
            positioning="长期私人数字陪伴者",
            default_address="老师",
            intimacy_boundary="自然克制",
        ),
        tone_rules=["自然私聊", "先接住情绪"],
        forbidden_styles=["客服腔", "说教腔", "模板化安慰"],
        correction_style=CorrectionStyleConfig(
            stance="温柔诚实",
            principles=["指出问题但不压人"],
        ),
    )
    policy = PolicyConfig(
        default_reply_style="自然私聊，中等长度优先。",
        short_reply_scenarios=["打招呼", "简单确认"],
        long_reply_scenarios=["深度讨论", "认真安慰"],
        comfort_rules=["先接住情绪，不要一上来讲道理。"],
        correction_rules=["可以指出问题，但要温柔。"],
        memory_usage_rules=[
            "记忆块只是可用上下文。",
            "没有足够依据时不要假装记得。",
        ],
        output_guardrails=["不要客服腔", "不要说教腔"],
    )
    runtime = RuntimeConfig(
        provider="mock",
        model="mock-model",
        reasoner_model=None,
        api_key_env="TEST_API_KEY",
        api_key="test-key",
        base_url="https://example.com",
        temperature=0.8,
        max_tokens=512,
        timeout=60,
        max_history_turns=8,
        memory_enabled=memory_enabled,
        memory_write_enabled=memory_write_enabled,
        memory_store_type="sqlite",
        memory_store_path=str(db_path),
        max_memory_injection_items=max_memory_injection_items,
        episodic_memory_ttl_days=episodic_memory_ttl_days,
        memory_review_enabled=memory_review_enabled,
        merge_time_window_hours=merge_time_window_hours,
        followup_scheduler_enabled=followup_scheduler_enabled,
        followup_cooldown_hours=followup_cooldown_hours,
        reply_guard_enabled=reply_guard_enabled,
        reply_guard_retry_once=reply_guard_retry_once,
        max_reply_chars=max_reply_chars,
        max_reply_chars_soft_limit=max_reply_chars,
        enable_file_logging=False,
        log_dir="data/logs",
        log_level="INFO",
        debug_trace_enabled=False,
        debug_show_scene=True,
        debug_show_prompt_blocks=False,
        debug_show_messages=False,
        debug_cli_diagnostics_enabled=False,
        debug_max_preview_chars=160,
        exit_commands=("exit", "quit"),
    )
    return AppConfig(
        persona=persona,
        policy=policy,
        runtime=runtime,
        config_dir=PROJECT_ROOT / "src" / "config",
    )
