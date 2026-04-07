from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.app.coordinator import Coordinator
from src.app.ui_adapter import TerminalUIAdapter
from src.config.loader import ConfigError, load_app_config
from src.utils.logger import configure_logging, get_logger


def main() -> int:
    bootstrap_ui = TerminalUIAdapter()

    try:
        config = load_app_config()
    except ConfigError as exc:
        bootstrap_ui.display_system_message(f"配置加载失败：{exc}")
        return 1

    configure_logging(config.runtime.log_level)
    logger = get_logger(__name__)

    ui = TerminalUIAdapter(
        assistant_label=config.persona.name,
        user_label=config.persona.user_name,
    )
    coordinator = Coordinator(config)
    exit_commands = {command.lower() for command in config.runtime.exit_commands}

    ui.display_system_message("Project_Serina v0.1 CLI Demo")
    ui.display_assistant_message(coordinator.get_welcome_message())

    while True:
        try:
            user_input = ui.get_user_input()
        except (EOFError, KeyboardInterrupt):
            ui.display_system_message("会话结束。")
            return 0

        if not user_input:
            continue

        if user_input.lower() in exit_commands:
            ui.display_system_message("会话结束，下次见。")
            return 0

        try:
            reply = coordinator.process_user_message(user_input)
        except Exception as exc:
            logger.exception("Failed to process message")
            ui.display_system_message(f"处理消息时出错：{exc}")
            continue

        ui.display_assistant_message(reply)


if __name__ == "__main__":
    raise SystemExit(main())
