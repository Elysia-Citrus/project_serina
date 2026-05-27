from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.app.runtime import build_app_runtime
from src.app.ui_adapter import TerminalUIAdapter
from src.config.loader import ConfigError, load_app_config
from src.utils.logger import configure_logging, get_logger


def main() -> int:
    bootstrap_ui = TerminalUIAdapter()
    configure_logging("INFO")
    logger = get_logger(__name__)

    try:
        config = load_app_config()
    except ConfigError as exc:
        logger.error("Config load failed: %s", exc)
        bootstrap_ui.display_system_message(f"配置加载失败：{exc}")
        return 1

    configure_logging(config.runtime)
    logger = get_logger(__name__)

    app_runtime = build_app_runtime(config)
    ui = app_runtime.ui
    coordinator = app_runtime.coordinator
    command_router = app_runtime.command_router
    exit_commands = {command.lower() for command in config.runtime.exit_commands}

    ui.display_system_message("Project_Serina CLI Demo")
    ui.display_assistant_message(coordinator.get_welcome_message())

    try:
        while True:
            try:
                user_input = ui.get_user_input()
            except (EOFError, KeyboardInterrupt):
                ui.display_system_message("会话结束。")
                break

            if not user_input:
                continue

            if user_input.lower() in exit_commands:
                ui.display_system_message("会话结束，下次见。")
                break

            command_result = command_router.route(user_input)
            if command_result is not None and command_result.handled:
                ui.display_system_message(command_result.output_text or "")
                continue

            try:
                turn_result = coordinator.process_user_message(user_input)
            except Exception as exc:
                logger.exception("Failed to process message")
                ui.display_system_message(f"处理消息时出错：{exc}")
                continue

            ui.display_assistant_message(turn_result.reply_text)
            if turn_result.diagnostic_text:
                ui.display_debug_message(turn_result.diagnostic_text)
    finally:
        try:
            coordinator.finalize_session()
        except Exception:
            logger.exception("Failed to finalize session")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
