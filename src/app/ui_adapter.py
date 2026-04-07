from __future__ import annotations


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

    def _display_labeled_message(self, label: str, message: str) -> None:
        lines = message.splitlines() or [""]
        print(f"{label} > {lines[0]}")
        padding = " " * (len(label) + 3)
        for line in lines[1:]:
            print(f"{padding}{line}")
