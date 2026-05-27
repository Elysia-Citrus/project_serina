from dataclasses import replace
from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.app.runtime import build_app_runtime
from src.app.ui_adapter import TerminalUIAdapter
from src.avatar.event_bus import AvatarEventBus
from src.config.loader import ConfigError, VoiceConfig, load_app_config
from src.utils.logger import configure_logging, get_logger
from src.voice.asr import build_asr_provider
from src.voice.controller import VoiceSessionController
from src.voice.errors import VoicePipelineError
from src.voice.models import VoiceTurnResult
from src.voice.playback import build_audio_playback
from src.voice.recorder import build_audio_recorder, describe_audio_devices
from src.voice.synthesis import build_speech_synthesis_service


def main() -> int:
    bootstrap_ui = TerminalUIAdapter()
    configure_logging("INFO")
    logger = get_logger(__name__)
    cli_args = set(sys.argv[1:])

    if "--list-devices" in cli_args:
        try:
            bootstrap_ui.display_system_message(describe_audio_devices())
            return 0
        except VoicePipelineError as exc:
            bootstrap_ui.display_system_message(str(exc))
            return 1

    try:
        config = load_app_config()
    except ConfigError as exc:
        logger.error("Config load failed: %s", exc)
        bootstrap_ui.display_system_message("Config load failed: " + str(exc))
        return 1

    if not config.voice.enabled:
        bootstrap_ui.display_system_message(
            "Voice mode is disabled. Set src/config/voice_config.yaml -> enabled: true before starting main_voice.py."
        )
        return 1

    configure_logging(config.runtime)
    logger = get_logger(__name__)
    auto_listen_enabled = config.voice.auto_listen_enabled
    if "--auto-listen" in cli_args:
        auto_listen_enabled = True
    if "--manual" in cli_args:
        auto_listen_enabled = False
    config = _apply_cli_overrides(config, cli_args)

    app_runtime = build_app_runtime(config)
    ui = app_runtime.ui
    coordinator = app_runtime.coordinator
    command_router = app_runtime.command_router
    speech_service = build_speech_synthesis_service(config)
    event_bus = AvatarEventBus()
    voice_controller = VoiceSessionController(
        config=config.voice,
        coordinator=coordinator,
        recorder=build_audio_recorder(config.voice),
        asr_provider=build_asr_provider(config.voice),
        speech_service=speech_service,
        playback=build_audio_playback(config.voice),
        command_router=command_router,
        status_callback=ui.display_system_message,
        event_bus=event_bus,
    )
    exit_commands = {command.lower() for command in config.runtime.exit_commands}

    ui.display_system_message("Project_Serina Voice CLI Demo")
    ui.display_system_message(_build_voice_runtime_banner(config.voice, auto_listen_enabled))
    if config.voice.tts_warmup_on_boot and speech_service.is_enabled:
        warmup_status = speech_service.warmup_local_runtimes()
        if warmup_status:
            ui.display_system_message(
                "[voice] local runtime warmup: "
                + ", ".join(f"{name}={status}" for name, status in warmup_status.items())
            )
    ui.display_assistant_message(coordinator.get_welcome_message())

    try:
        if auto_listen_enabled:
            _run_auto_listen_loop(ui, voice_controller, config.voice, logger)
        else:
            _run_manual_loop(
                ui=ui,
                voice_controller=voice_controller,
                voice_config=config.voice,
                user_name=config.persona.user_name,
                exit_commands=exit_commands,
                logger=logger,
            )
    finally:
        try:
            coordinator.finalize_session()
        except Exception:
            logger.exception("Failed to finalize session")

    return 0


def _apply_cli_overrides(config, cli_args: set[str]):
    if "--no-tts" not in cli_args:
        return config
    return replace(
        config,
        voice=replace(
            config.voice,
            tts_provider="none",
            stream_playback_enabled=False,
            tts_warmup_on_boot=False,
        ),
    )


def _run_manual_loop(
    *,
    ui: TerminalUIAdapter,
    voice_controller: VoiceSessionController,
    voice_config: VoiceConfig,
    user_name: str,
    exit_commands: set[str],
    logger,
) -> None:
    while True:
        try:
            raw_input = input(f"{user_name} (voice) > ")
        except (EOFError, KeyboardInterrupt):
            ui.display_system_message("Session ended.")
            break

        if raw_input.strip().lower() in exit_commands:
            ui.display_system_message("Session ended. See you next time.")
            break

        try:
            turn_result = voice_controller.handle_console_input(raw_input)
        except Exception as exc:
            logger.exception("Failed to process voice input")
            ui.display_system_message("Voice input failed: " + str(exc))
            continue

        if turn_result is None:
            continue
        _display_turn_result(ui, voice_config, turn_result)


def _run_auto_listen_loop(
    ui: TerminalUIAdapter,
    voice_controller: VoiceSessionController,
    voice_config: VoiceConfig,
    logger,
) -> None:
    ui.display_system_message(
        "Auto voice mode is enabled. Serina will listen after each reply. Press Ctrl+C to stop. Headphones are recommended."
    )
    while True:
        try:
            turn_result = voice_controller.run_voice_turn()
        except (EOFError, KeyboardInterrupt):
            ui.display_system_message("Session ended.")
            break
        except Exception as exc:
            logger.exception("Failed to process auto voice turn")
            ui.display_system_message("Voice input failed: " + str(exc))
            continue

        _display_turn_result(ui, voice_config, turn_result)


def _display_turn_result(
    ui: TerminalUIAdapter,
    voice_config: VoiceConfig,
    turn_result: VoiceTurnResult,
) -> None:
    if turn_result.command_handled:
        ui.display_system_message(turn_result.command_output_text or "")
        return

    if (
        turn_result.source_channel == "voice"
        and voice_config.echo_transcript_to_console
        and turn_result.transcript_text
    ):
        ui.display_system_message(f"[asr] {turn_result.transcript_text}")

    if turn_result.reply_text:
        ui.display_assistant_message(turn_result.reply_text)
    elif turn_result.error_message:
        error_stage = turn_result.error_stage or "unknown"
        ui.display_system_message(
            f"[voice error: {error_stage}] {turn_result.error_message}"
        )

    if turn_result.error_message and turn_result.reply_text:
        ui.display_system_message(f"[voice degraded] {turn_result.error_message}")

    if turn_result.diagnostic_text:
        ui.display_debug_message(turn_result.diagnostic_text)


def _build_voice_runtime_banner(
    voice_config: VoiceConfig,
    auto_listen_enabled: bool,
) -> str:
    recording_hint = (
        f"Fixed-duration voice turns ({voice_config.fixed_record_seconds:.1f}s each)"
        if voice_config.recording_mode == "fixed_duration"
        else (
            "Endpoint-detected voice turns"
            if voice_config.recording_mode == "endpoint_once"
            else "Silence-stop voice turns"
        )
    )
    device_hint = f"input_device={voice_config.input_device!r}"
    output_hint = (
        "TTS disabled"
        if voice_config.tts_provider.lower() == "none"
        else "stream playback on"
        if voice_config.stream_playback_enabled
        else "stream playback off"
    )
    if auto_listen_enabled:
        return (
            f"{recording_hint}, {device_hint}, {output_hint}. Auto-listen mode is on. "
            "Use --manual if you want slash commands and Enter-to-record behavior."
        )
    return (
        f"{recording_hint}, {device_hint}, {output_hint}. "
        "Press Enter to record one voice turn. Type /voice devices, /memory, or /trace commands directly. Type exit to leave."
    )


if __name__ == "__main__":
    raise SystemExit(main())
