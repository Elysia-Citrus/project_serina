from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RelationshipStyleConfig:
    positioning: str
    default_address: str
    intimacy_boundary: str


@dataclass(frozen=True)
class CorrectionStyleConfig:
    stance: str
    principles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaConfig:
    name: str
    user_name: str
    language: str
    self_concept: str
    welcome_message: str
    core_traits: list[str] = field(default_factory=list)
    relationship_style: RelationshipStyleConfig | None = None
    tone_rules: list[str] = field(default_factory=list)
    forbidden_styles: list[str] = field(default_factory=list)
    correction_style: CorrectionStyleConfig | None = None


@dataclass(frozen=True)
class PolicyConfig:
    default_reply_style: str
    short_reply_scenarios: list[str] = field(default_factory=list)
    long_reply_scenarios: list[str] = field(default_factory=list)
    comfort_rules: list[str] = field(default_factory=list)
    correction_rules: list[str] = field(default_factory=list)
    memory_usage_rules: list[str] = field(default_factory=list)
    output_guardrails: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str
    model: str
    reasoner_model: str | None
    api_key_env: str
    api_key: str | None
    base_url: str
    temperature: float
    max_tokens: int
    timeout: int
    max_history_turns: int
    memory_enabled: bool
    memory_write_enabled: bool
    memory_store_type: str
    memory_store_path: str
    max_memory_injection_items: int
    startup_memory_enabled: bool
    startup_memory_turn_window: int
    startup_memory_profile_limit: int
    startup_memory_episodic_limit: int
    startup_memory_open_loop_limit: int
    startup_memory_summary_limit: int
    startup_memory_total_limit: int
    episodic_memory_ttl_days: int
    memory_review_enabled: bool
    merge_time_window_hours: int
    followup_scheduler_enabled: bool
    followup_cooldown_hours: int
    reply_guard_enabled: bool
    reply_guard_retry_once: bool
    max_reply_chars: int
    max_reply_chars_soft_limit: int
    assist_llm_enabled: bool
    assist_llm_default_model: str
    assist_llm_runtime_model: str
    assist_llm_dev_model: str
    assist_llm_timeout_ms: int
    assist_llm_max_runtime_calls_per_turn: int
    assist_llm_max_dev_calls_per_command: int
    assist_llm_enable_guard_retry_rewrite: bool
    assist_llm_enable_memory_reference_check: bool
    assist_llm_enable_trace_summary: bool
    assist_llm_enable_badcase_draft: bool
    assist_llm_enable_pending_review_note: bool
    assist_llm_enable_merge_summary: bool
    enable_file_logging: bool
    log_dir: str
    log_level: str
    debug_trace_enabled: bool
    debug_show_scene: bool
    debug_show_prompt_blocks: bool
    debug_show_messages: bool
    debug_cli_diagnostics_enabled: bool
    debug_max_preview_chars: int
    exit_commands: tuple[str, ...]


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool
    language: str
    input_device: str | int | None
    output_device: str | int | None
    sample_rate: int
    channels: int
    chunk_ms: int
    record_timeout_s: float
    silence_timeout_s: float
    min_speech_s: float
    silence_rms_threshold: int
    recording_mode: str
    fixed_record_seconds: float
    vad_enabled: bool
    partial_transcript_enabled: bool
    partial_commit_strategy: str
    asr_provider: str
    asr_model: str
    asr_compute_device: str
    asr_api_key_env: str
    asr_api_key: str | None
    asr_base_url: str
    myneuro_asr_url: str
    myneuro_asr_timeout_s: float
    tts_provider: str
    tts_model: str
    tts_voice_preset: str
    tts_api_key_env: str
    tts_api_key: str | None
    tts_base_url: str
    gpt_sovits_v2_url: str
    gpt_sovits_v2_ref_audio_path: str
    gpt_sovits_v2_prompt_text: str
    gpt_sovits_v2_text_lang: str
    gpt_sovits_v2_prompt_lang: str
    gpt_sovits_v2_text_split_method: str
    gpt_sovits_v2_batch_size: int
    gpt_sovits_v2_streaming_mode: bool | int
    gpt_sovits_v2_media_type: str
    gpt_sovits_v2_timeout_s: float
    myneuro_memos_base_url: str
    default_voice_profile_id: str | None
    voice_profiles_path: str
    local_tts_enabled: bool
    primary_tts_runtime_url: str
    clone_tts_runtime_url: str
    stream_playback_enabled: bool
    tts_warmup_on_boot: bool
    allow_spoken_commands: bool
    echo_transcript_to_console: bool
    debug_save_input_audio: bool
    debug_save_output_audio: bool
    temp_audio_dir: str
    auto_listen_enabled: bool
    interrupt_enabled: bool
    keyboard_interrupt_enabled: bool
    microphone_interrupt_enabled: bool
    interrupt_rms_threshold: int


@dataclass(frozen=True)
class AppConfig:
    persona: PersonaConfig
    policy: PolicyConfig
    runtime: RuntimeConfig
    voice: VoiceConfig
    config_dir: Path
