from __future__ import annotations

import sys


class TerminalUIAdapter:
    def __init__(self, assistant_label: str = "Serina", user_label: str = "老师") -> None:
        self.assistant_label = assistant_label
        self.user_label = user_label

    def get_user_input(self) -> str:
        return input(f"{self.user_label} > ").strip()

    def display_assistant_message(self, message: str) -> None:
        self._display_labeled_message(self.assistant_label, message)

    def display_system_message(self, message: str) -> None:
        self._display_labeled_message("[system]", message)

    def display_debug_message(self, message: str) -> None:
        self._display_labeled_message("[debug]", message)

    def _display_labeled_message(self, label: str, message: str) -> None:
        lines = message.splitlines() or [""]
        self._safe_print(f"{label} > {lines[0]}")
        padding = " " * (len(label) + 3)
        for line in lines[1:]:
            self._safe_print(f"{padding}{line}")

    def _safe_print(self, text: str) -> None:
        try:
            print(text)
        except UnicodeEncodeError:
            encoded = text.encode(
                sys.stdout.encoding or "utf-8",
                errors="replace",
            )
            sys.stdout.buffer.write(encoded + b"\n")
            sys.stdout.flush()
