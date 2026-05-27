from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable
from uuid import uuid4

from src.config.loader import (
    AppConfig,
    CorrectionStyleConfig,
    PersonaConfig,
    PolicyConfig,
    RelationshipStyleConfig,
    RuntimeConfig,
    VoiceConfig,
)
from src.llm.gateway import GatewayResponse


GatewayScript = str | Exception | GatewayResponse | Callable[..., str | GatewayResponse]


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TemporaryWorkspace:
    def __init__(self) -> None:
        base_dir = PROJECT_ROOT / ".tmp_test_workspaces"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.root = base_dir / f"workspace_{uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "serina_test.db"

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class DummyGateway:
    def __init__(self, responses: list[GatewayScript]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate(self, messages, turn_trace=None, options=None) -> GatewayResponse:  # type: ignore[no-untyped-def]
        if not self.responses:
            raise AssertionError("DummyGateway has no more queued responses.")
        scripted = self.responses.pop(0)
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "options": options,
            }
        )
        if isinstance(scripted, Exception):
            raise scripted
        if callable(scripted):
            scripted = scripted(messages=messages, turn_trace=turn_trace, options=options)
        if isinstance(scripted, GatewayResponse):
            return scripted
        text = str(scripted)
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
    assist_llm_enabled: bool = True,
    assist_llm_enable_guard_retry_rewrite: bool = True,
    assist_llm_enable_memory_reference_check: bool = True,
    assist_llm_enable_trace_summary: bool = True,
    assist_llm_enable_badcase_draft: bool = True,
    assist_llm_enable_pending_review_note: bool = True,
    assist_llm_enable_merge_summary: bool = True,
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
        startup_memory_enabled=True,
        startup_memory_turn_window=2,
        startup_memory_profile_limit=2,
        startup_memory_episodic_limit=2,
        startup_memory_open_loop_limit=2,
        startup_memory_summary_limit=1,
        startup_memory_total_limit=6,
        episodic_memory_ttl_days=episodic_memory_ttl_days,
        memory_review_enabled=memory_review_enabled,
        merge_time_window_hours=merge_time_window_hours,
        followup_scheduler_enabled=followup_scheduler_enabled,
        followup_cooldown_hours=followup_cooldown_hours,
        reply_guard_enabled=reply_guard_enabled,
        reply_guard_retry_once=reply_guard_retry_once,
        max_reply_chars=max_reply_chars,
        max_reply_chars_soft_limit=max_reply_chars,
        assist_llm_enabled=assist_llm_enabled,
        assist_llm_default_model="mock-assist",
        assist_llm_runtime_model="mock-assist-runtime",
        assist_llm_dev_model="mock-assist-dev",
        assist_llm_timeout_ms=2500,
        assist_llm_max_runtime_calls_per_turn=1,
        assist_llm_max_dev_calls_per_command=3,
        assist_llm_enable_guard_retry_rewrite=assist_llm_enable_guard_retry_rewrite,
        assist_llm_enable_memory_reference_check=assist_llm_enable_memory_reference_check,
        assist_llm_enable_trace_summary=assist_llm_enable_trace_summary,
        assist_llm_enable_badcase_draft=assist_llm_enable_badcase_draft,
        assist_llm_enable_pending_review_note=assist_llm_enable_pending_review_note,
        assist_llm_enable_merge_summary=assist_llm_enable_merge_summary,
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
    voice = VoiceConfig(
        enabled=False,
        language="zh-CN",
        input_device=None,
        output_device=None,
        sample_rate=16000,
        channels=1,
        chunk_ms=200,
        record_timeout_s=20.0,
        silence_timeout_s=1.2,
        min_speech_s=0.4,
        silence_rms_threshold=450,
        recording_mode="silence_stop",
        fixed_record_seconds=6.0,
        vad_enabled=False,
        partial_transcript_enabled=False,
        partial_commit_strategy="none",
        asr_provider="dashscope",
        asr_model="paraformer-realtime-v2",
        asr_compute_device="cpu",
        asr_api_key_env="DASHSCOPE_API_KEY",
        asr_api_key="test-voice-key",
        asr_base_url="https://dashscope.aliyuncs.com/api/v1",
        myneuro_asr_url="http://127.0.0.1:1000/v1/upload_audio",
        myneuro_asr_timeout_s=120.0,
        tts_provider="dashscope_tts",
        tts_model="cosyvoice-v3-flash",
        tts_voice_preset="longanyang",
        tts_api_key_env="DASHSCOPE_API_KEY",
        tts_api_key="test-voice-key",
        tts_base_url="https://dashscope.aliyuncs.com/api/v1",
        gpt_sovits_v2_url="http://127.0.0.1:5000/tts",
        gpt_sovits_v2_ref_audio_path="role_voice_api/neuro/01.wav",
        gpt_sovits_v2_prompt_text=(
            "Hold on please, I'm busy. Okay, I think I heard him say he wants me "
            "to stream Hollow Knight on Tuesday and Thursday."
        ),
        gpt_sovits_v2_text_lang="zh",
        gpt_sovits_v2_prompt_lang="en",
        gpt_sovits_v2_text_split_method="cut5",
        gpt_sovits_v2_batch_size=1,
        gpt_sovits_v2_streaming_mode=True,
        gpt_sovits_v2_media_type="wav",
        gpt_sovits_v2_timeout_s=120.0,
        myneuro_memos_base_url="http://127.0.0.1:8000",
        default_voice_profile_id=None,
        voice_profiles_path="voice_profiles.yaml",
        local_tts_enabled=True,
        primary_tts_runtime_url="http://127.0.0.1:51771",
        clone_tts_runtime_url="http://127.0.0.1:51772",
        stream_playback_enabled=True,
        tts_warmup_on_boot=False,
        allow_spoken_commands=False,
        echo_transcript_to_console=True,
        debug_save_input_audio=False,
        debug_save_output_audio=False,
        temp_audio_dir=str(PROJECT_ROOT / "artifacts" / "voice" / "tmp"),
        auto_listen_enabled=False,
        interrupt_enabled=True,
        keyboard_interrupt_enabled=True,
        microphone_interrupt_enabled=False,
        interrupt_rms_threshold=600,
    )
    return AppConfig(
        persona=persona,
        policy=policy,
        runtime=runtime,
        voice=voice,
        config_dir=PROJECT_ROOT / "src" / "config",
    )
