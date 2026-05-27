from __future__ import annotations

from pathlib import Path
import os

from src.config.errors import ConfigError
from src.config.models import (
    AppConfig,
    CorrectionStyleConfig,
    PersonaConfig,
    PolicyConfig,
    RelationshipStyleConfig,
    RuntimeConfig,
    VoiceConfig,
)
from src.config.validators import (
    _optional_bool,
    _optional_device_selector,
    _optional_float,
    _optional_int,
    _optional_string,
    _optional_string_list,
    _require_float,
    _require_int,
    _require_mapping,
    _require_string,
    _require_string_list,
)
from src.config.yaml_utils import _read_yaml_file

__all__ = [
    "AppConfig",
    "ConfigError",
    "CorrectionStyleConfig",
    "PersonaConfig",
    "PolicyConfig",
    "RelationshipStyleConfig",
    "RuntimeConfig",
    "VoiceConfig",
    "load_app_config",
    "load_persona_config",
    "load_policy_config",
    "load_runtime_config",
    "load_voice_config",
    "_read_yaml_file",
]


def load_app_config(config_dir: str | Path | None = None) -> AppConfig:
    resolved_dir = Path(config_dir) if config_dir else Path(__file__).resolve().parent

    persona = load_persona_config(resolved_dir / "persona_config.yaml")
    policy = load_policy_config(resolved_dir / "policy_config.yaml")
    runtime = load_runtime_config(resolved_dir / "runtime_config.yaml")
    voice = load_voice_config(resolved_dir / "voice_config.yaml")

    return AppConfig(
        persona=persona,
        policy=policy,
        runtime=runtime,
        voice=voice,
        config_dir=resolved_dir,
    )


def load_persona_config(path: str | Path) -> PersonaConfig:
    resolved_path = Path(path)
    raw = _read_yaml_file(resolved_path)

    relationship_raw = _require_mapping(raw, "relationship_style", resolved_path)
    correction_raw = _require_mapping(raw, "correction_style", resolved_path)
    user_name = _require_string(raw, "user_name", resolved_path)

    return PersonaConfig(
        name=_require_string(raw, "name", resolved_path),
        user_name=user_name,
        language=str(raw.get("language", "zh-CN")).strip(),
        self_concept=str(raw.get("self_concept", "")).strip()
        or "你是 Serina，是老师长期相处的私人数字伴侣。",
        welcome_message=str(raw.get("welcome_message") or f"{user_name}，我在。").strip(),
        core_traits=_require_string_list(raw, "core_traits", resolved_path),
        relationship_style=RelationshipStyleConfig(
            positioning=_require_string(relationship_raw, "positioning", resolved_path),
            default_address=_require_string(
                relationship_raw,
                "default_address",
                resolved_path,
            ),
            intimacy_boundary=_require_string(
                relationship_raw,
                "intimacy_boundary",
                resolved_path,
            ),
        ),
        tone_rules=_require_string_list(raw, "tone_rules", resolved_path),
        forbidden_styles=_require_string_list(raw, "forbidden_styles", resolved_path),
        correction_style=CorrectionStyleConfig(
            stance=_require_string(correction_raw, "stance", resolved_path),
            principles=_require_string_list(correction_raw, "principles", resolved_path),
        ),
    )


def load_policy_config(path: str | Path) -> PolicyConfig:
    resolved_path = Path(path)
    raw = _read_yaml_file(resolved_path)

    return PolicyConfig(
        default_reply_style=_require_string(raw, "default_reply_style", resolved_path),
        short_reply_scenarios=_require_string_list(
            raw,
            "short_reply_scenarios",
            resolved_path,
        ),
        long_reply_scenarios=_require_string_list(
            raw,
            "long_reply_scenarios",
            resolved_path,
        ),
        comfort_rules=_require_string_list(raw, "comfort_rules", resolved_path),
        correction_rules=_require_string_list(raw, "correction_rules", resolved_path),
        memory_usage_rules=_require_string_list(
            raw,
            "memory_usage_rules",
            resolved_path,
        ),
        output_guardrails=_optional_string_list(raw.get("output_guardrails")),
    )


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    resolved_path = Path(path)
    raw = _read_yaml_file(resolved_path)

    api_key_env = _require_string(raw, "api_key_env", resolved_path)
    inline_api_key = str(raw.get("api_key", "")).strip()
    env_api_key = os.getenv(api_key_env, "").strip()

    exit_commands_raw = raw.get("exit_commands", ["exit", "quit"])
    exit_commands = tuple(
        command.strip().lower()
        for command in _optional_string_list(exit_commands_raw)
        if command.strip()
    )

    return RuntimeConfig(
        provider=_require_string(raw, "provider", resolved_path).lower(),
        model=_require_string(raw, "model", resolved_path),
        reasoner_model=_optional_string(raw.get("reasoner_model")),
        api_key_env=api_key_env,
        api_key=env_api_key or inline_api_key or None,
        base_url=_require_string(raw, "base_url", resolved_path),
        temperature=_require_float(raw, "temperature", resolved_path),
        max_tokens=_require_int(raw, "max_tokens", resolved_path),
        timeout=_require_int(raw, "timeout", resolved_path),
        max_history_turns=max(1, _require_int(raw, "max_history_turns", resolved_path)),
        memory_enabled=_optional_bool(raw.get("memory_enabled"), True),
        memory_write_enabled=_optional_bool(raw.get("memory_write_enabled"), True),
        memory_store_type=_optional_string(raw.get("memory_store_type")) or "sqlite",
        memory_store_path=_optional_string(raw.get("memory_store_path")) or "data/serina.db",
        max_memory_injection_items=max(
            2,
            min(4, _optional_int(raw.get("max_memory_injection_items"), 3)),
        ),
        startup_memory_enabled=_optional_bool(raw.get("startup_memory_enabled"), True),
        startup_memory_turn_window=max(
            1,
            min(3, _optional_int(raw.get("startup_memory_turn_window"), 2)),
        ),
        startup_memory_profile_limit=max(
            0,
            min(2, _optional_int(raw.get("startup_memory_profile_limit"), 2)),
        ),
        startup_memory_episodic_limit=max(
            0,
            min(2, _optional_int(raw.get("startup_memory_episodic_limit"), 2)),
        ),
        startup_memory_open_loop_limit=max(
            0,
            min(2, _optional_int(raw.get("startup_memory_open_loop_limit"), 2)),
        ),
        startup_memory_summary_limit=max(
            0,
            min(1, _optional_int(raw.get("startup_memory_summary_limit"), 1)),
        ),
        startup_memory_total_limit=max(
            1,
            min(7, _optional_int(raw.get("startup_memory_total_limit"), 6)),
        ),
        episodic_memory_ttl_days=max(
            3,
            min(14, _optional_int(raw.get("episodic_memory_ttl_days"), 7)),
        ),
        memory_review_enabled=_optional_bool(raw.get("memory_review_enabled"), True),
        merge_time_window_hours=max(
            6,
            _optional_int(raw.get("merge_time_window_hours"), 72),
        ),
        followup_scheduler_enabled=_optional_bool(
            raw.get("followup_scheduler_enabled"),
            True,
        ),
        followup_cooldown_hours=max(
            6,
            _optional_int(raw.get("followup_cooldown_hours"), 24),
        ),
        reply_guard_enabled=_optional_bool(raw.get("reply_guard_enabled"), True),
        reply_guard_retry_once=_optional_bool(raw.get("reply_guard_retry_once"), True),
        max_reply_chars=max(
            80,
            _optional_int(
                raw.get("max_reply_chars"),
                _optional_int(raw.get("max_reply_chars_soft_limit"), 220),
            ),
        ),
        max_reply_chars_soft_limit=max(
            80,
            _optional_int(
                raw.get("max_reply_chars_soft_limit"),
                _optional_int(raw.get("max_reply_chars"), 220),
            ),
        ),
        assist_llm_enabled=_optional_bool(raw.get("assist_llm_enabled"), True),
        assist_llm_default_model=(
            _optional_string(raw.get("assist_llm_default_model"))
            or _require_string(raw, "model", resolved_path)
        ),
        assist_llm_runtime_model=(
            _optional_string(raw.get("assist_llm_runtime_model"))
            or _optional_string(raw.get("assist_llm_default_model"))
            or _require_string(raw, "model", resolved_path)
        ),
        assist_llm_dev_model=(
            _optional_string(raw.get("assist_llm_dev_model"))
            or _optional_string(raw.get("reasoner_model"))
            or _optional_string(raw.get("assist_llm_default_model"))
            or _require_string(raw, "model", resolved_path)
        ),
        assist_llm_timeout_ms=max(
            500,
            _optional_int(raw.get("assist_llm_timeout_ms"), 4000),
        ),
        assist_llm_max_runtime_calls_per_turn=max(
            0,
            min(1, _optional_int(raw.get("assist_llm_max_runtime_calls_per_turn"), 1)),
        ),
        assist_llm_max_dev_calls_per_command=max(
            0,
            _optional_int(raw.get("assist_llm_max_dev_calls_per_command"), 3),
        ),
        assist_llm_enable_guard_retry_rewrite=_optional_bool(
            raw.get("assist_llm_enable_guard_retry_rewrite"),
            True,
        ),
        assist_llm_enable_memory_reference_check=_optional_bool(
            raw.get("assist_llm_enable_memory_reference_check"),
            True,
        ),
        assist_llm_enable_trace_summary=_optional_bool(
            raw.get("assist_llm_enable_trace_summary"),
            True,
        ),
        assist_llm_enable_badcase_draft=_optional_bool(
            raw.get("assist_llm_enable_badcase_draft"),
            True,
        ),
        assist_llm_enable_pending_review_note=_optional_bool(
            raw.get("assist_llm_enable_pending_review_note"),
            True,
        ),
        assist_llm_enable_merge_summary=_optional_bool(
            raw.get("assist_llm_enable_merge_summary"),
            True,
        ),
        enable_file_logging=_optional_bool(raw.get("enable_file_logging"), False),
        log_dir=_optional_string(raw.get("log_dir")) or "data/logs",
        log_level=str(raw.get("log_level", "INFO")).strip().upper() or "INFO",
        debug_trace_enabled=_optional_bool(raw.get("debug_trace_enabled"), False),
        debug_show_scene=_optional_bool(raw.get("debug_show_scene"), True),
        debug_show_prompt_blocks=_optional_bool(
            raw.get("debug_show_prompt_blocks"),
            False,
        ),
        debug_show_messages=_optional_bool(raw.get("debug_show_messages"), False),
        debug_cli_diagnostics_enabled=_optional_bool(
            raw.get("debug_cli_diagnostics_enabled"),
            False,
        ),
        debug_max_preview_chars=max(
            40,
            _optional_int(raw.get("debug_max_preview_chars"), 160),
        ),
        exit_commands=exit_commands or ("exit", "quit"),
    )


def load_voice_config(path: str | Path) -> VoiceConfig:
    resolved_path = Path(path)
    raw = _read_yaml_file(resolved_path)
    recording_mode = (_optional_string(raw.get("recording_mode")) or "silence_stop").lower()
    if recording_mode not in {"silence_stop", "fixed_duration", "endpoint_once"}:
        raise ConfigError(
            f"Unsupported voice recording_mode: {recording_mode}. "
            "Use silence_stop, fixed_duration, or endpoint_once."
        )
    partial_commit_strategy = (
        _optional_string(raw.get("partial_commit_strategy")) or "none"
    ).lower()
    if partial_commit_strategy not in {"none", "console_latest", "stable_prefix"}:
        raise ConfigError(
            "Unsupported voice partial_commit_strategy: "
            f"{partial_commit_strategy}. Use none, console_latest, or stable_prefix."
        )

    asr_api_key_env = (
        _optional_string(raw.get("asr_api_key_env"))
        or _optional_string(raw.get("api_key_env"))
        or "DASHSCOPE_API_KEY"
    )
    tts_api_key_env = (
        _optional_string(raw.get("tts_api_key_env"))
        or _optional_string(raw.get("api_key_env"))
        or asr_api_key_env
    )
    inline_asr_api_key = (
        _optional_string(raw.get("asr_api_key"))
        or _optional_string(raw.get("api_key"))
    )
    inline_tts_api_key = (
        _optional_string(raw.get("tts_api_key"))
        or _optional_string(raw.get("api_key"))
    )
    env_asr_api_key = os.getenv(asr_api_key_env, "").strip()
    env_tts_api_key = os.getenv(tts_api_key_env, "").strip()

    return VoiceConfig(
        enabled=_optional_bool(raw.get("enabled"), False),
        language=_optional_string(raw.get("language")) or "zh-CN",
        input_device=_optional_device_selector(raw.get("input_device")),
        output_device=_optional_device_selector(raw.get("output_device")),
        sample_rate=max(8000, _optional_int(raw.get("sample_rate"), 16000)),
        channels=max(1, min(2, _optional_int(raw.get("channels"), 1))),
        chunk_ms=max(50, min(1000, _optional_int(raw.get("chunk_ms"), 200))),
        record_timeout_s=max(
            3.0,
            min(120.0, _optional_float(raw.get("record_timeout_s"), 20.0)),
        ),
        silence_timeout_s=max(
            0.3,
            min(5.0, _optional_float(raw.get("silence_timeout_s"), 1.2)),
        ),
        min_speech_s=max(
            0.1,
            min(10.0, _optional_float(raw.get("min_speech_s"), 0.4)),
        ),
        silence_rms_threshold=max(
            50,
            min(5000, _optional_int(raw.get("silence_rms_threshold"), 450)),
        ),
        recording_mode=recording_mode,
        fixed_record_seconds=max(
            1.0,
            min(30.0, _optional_float(raw.get("fixed_record_seconds"), 6.0)),
        ),
        vad_enabled=_optional_bool(raw.get("vad_enabled"), False),
        partial_transcript_enabled=_optional_bool(
            raw.get("partial_transcript_enabled"),
            False,
        ),
        partial_commit_strategy=partial_commit_strategy,
        asr_provider=(_optional_string(raw.get("asr_provider")) or "dashscope").lower(),
        asr_model=_optional_string(raw.get("asr_model")) or "paraformer-realtime-v2",
        asr_compute_device=(
            _optional_string(raw.get("asr_compute_device")) or "cpu"
        ).lower(),
        asr_api_key_env=asr_api_key_env,
        asr_api_key=env_asr_api_key or inline_asr_api_key or None,
        asr_base_url=(
            _optional_string(raw.get("asr_base_url"))
            or _optional_string(raw.get("base_url"))
            or "https://dashscope.aliyuncs.com/api/v1"
        ),
        myneuro_asr_url=(
            _optional_string(raw.get("myneuro_asr_url"))
            or "http://127.0.0.1:1000/v1/upload_audio"
        ),
        myneuro_asr_timeout_s=max(
            1.0,
            min(180.0, _optional_float(raw.get("myneuro_asr_timeout_s"), 120.0)),
        ),
        tts_provider=(
            _optional_string(raw.get("tts_provider")) or "dashscope_tts"
        ).lower(),
        tts_model=_optional_string(raw.get("tts_model")) or "cosyvoice-v3-flash",
        tts_voice_preset=(
            _optional_string(raw.get("tts_voice_preset")) or "longanyang"
        ),
        tts_api_key_env=tts_api_key_env,
        tts_api_key=env_tts_api_key or inline_tts_api_key or None,
        tts_base_url=(
            _optional_string(raw.get("tts_base_url"))
            or _optional_string(raw.get("base_url"))
            or "https://dashscope.aliyuncs.com/api/v1"
        ),
        gpt_sovits_v2_url=(
            _optional_string(raw.get("gpt_sovits_v2_url"))
            or "http://127.0.0.1:5000/tts"
        ),
        gpt_sovits_v2_ref_audio_path=(
            _optional_string(raw.get("gpt_sovits_v2_ref_audio_path"))
            or "role_voice_api/neuro/01.wav"
        ),
        gpt_sovits_v2_prompt_text=(
            _optional_string(raw.get("gpt_sovits_v2_prompt_text"))
            or (
                "Hold on please, I'm busy. Okay, I think I heard him say he wants me "
                "to stream Hollow Knight on Tuesday and Thursday."
            )
        ),
        gpt_sovits_v2_text_lang=(
            _optional_string(raw.get("gpt_sovits_v2_text_lang")) or "zh"
        ),
        gpt_sovits_v2_prompt_lang=(
            _optional_string(raw.get("gpt_sovits_v2_prompt_lang")) or "en"
        ),
        gpt_sovits_v2_text_split_method=(
            _optional_string(raw.get("gpt_sovits_v2_text_split_method")) or "cut5"
        ),
        gpt_sovits_v2_batch_size=max(
            1,
            _optional_int(raw.get("gpt_sovits_v2_batch_size"), 1),
        ),
        gpt_sovits_v2_streaming_mode=raw.get(
            "gpt_sovits_v2_streaming_mode",
            raw.get("stream_playback_enabled", True),
        ),
        gpt_sovits_v2_media_type=(
            _optional_string(raw.get("gpt_sovits_v2_media_type")) or "wav"
        ),
        gpt_sovits_v2_timeout_s=max(
            1.0,
            min(180.0, _optional_float(raw.get("gpt_sovits_v2_timeout_s"), 120.0)),
        ),
        myneuro_memos_base_url=(
            _optional_string(raw.get("myneuro_memos_base_url"))
            or "http://127.0.0.1:8000"
        ),
        default_voice_profile_id=_optional_string(raw.get("default_voice_profile_id")),
        voice_profiles_path=(
            _optional_string(raw.get("voice_profiles_path")) or "voice_profiles.yaml"
        ),
        local_tts_enabled=_optional_bool(raw.get("local_tts_enabled"), True),
        primary_tts_runtime_url=(
            _optional_string(raw.get("primary_tts_runtime_url"))
            or "http://127.0.0.1:51771"
        ),
        clone_tts_runtime_url=(
            _optional_string(raw.get("clone_tts_runtime_url"))
            or "http://127.0.0.1:51772"
        ),
        stream_playback_enabled=_optional_bool(
            raw.get("stream_playback_enabled"),
            True,
        ),
        tts_warmup_on_boot=_optional_bool(raw.get("tts_warmup_on_boot"), False),
        allow_spoken_commands=_optional_bool(raw.get("allow_spoken_commands"), False),
        echo_transcript_to_console=_optional_bool(
            raw.get("echo_transcript_to_console"),
            True,
        ),
        debug_save_input_audio=_optional_bool(
            raw.get("debug_save_input_audio"),
            False,
        ),
        debug_save_output_audio=_optional_bool(
            raw.get("debug_save_output_audio"),
            False,
        ),
        temp_audio_dir=_optional_string(raw.get("temp_audio_dir")) or "artifacts/voice/tmp",
        auto_listen_enabled=_optional_bool(raw.get("auto_listen_enabled"), False),
        interrupt_enabled=_optional_bool(raw.get("interrupt_enabled"), True),
        keyboard_interrupt_enabled=_optional_bool(
            raw.get("keyboard_interrupt_enabled"),
            True,
        ),
        microphone_interrupt_enabled=_optional_bool(
            raw.get("microphone_interrupt_enabled"),
            True,
        ),
        interrupt_rms_threshold=max(
            50,
            min(5000, _optional_int(raw.get("interrupt_rms_threshold"), 600)),
        ),
    )
