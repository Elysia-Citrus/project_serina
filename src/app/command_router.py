from __future__ import annotations

from dataclasses import dataclass
import shlex

from src.memory.admin import MemoryAdminResult, MemoryAdminService
from src.observability.trace_admin import TraceAdminResult, TraceAdminService


@dataclass(frozen=True)
class CommandRouteResult:
    handled: bool
    output_text: str | None = None
    success: bool = True


class CommandRouter:
    def __init__(
        self,
        *,
        memory_review_enabled: bool,
        memory_admin: MemoryAdminService,
        trace_admin: TraceAdminService | None = None,
    ) -> None:
        self.memory_review_enabled = memory_review_enabled
        self.memory_admin = memory_admin
        self.trace_admin = trace_admin

    def route(self, user_input: str) -> CommandRouteResult | None:
        if user_input.startswith("/trace"):
            return self._route_trace_command(user_input)
        if user_input.startswith("/badcase"):
            return self._route_badcase_command(user_input)
        if not user_input.startswith("/memory"):
            return None
        if not self.memory_review_enabled:
            return CommandRouteResult(
                handled=True,
                output_text="memory review is currently disabled.",
                success=False,
            )

        try:
            parts = shlex.split(user_input)
        except ValueError as exc:
            return CommandRouteResult(
                handled=True,
                output_text=f"Failed to parse command: {exc}",
                success=False,
            )

        if len(parts) == 1 or parts[1] in {"help", "-h", "--help"}:
            return self._wrap(self.memory_admin.help_text(), success=True)

        action = parts[1]
        if action == "list":
            return self._handle_list(parts[2:])

        if len(parts) < 3:
            return self._wrap("Missing memory id.", success=False)

        memory_id = parts[2]
        if action == "archive":
            return self._from_admin(self.memory_admin.archive(memory_id))
        if action == "delete":
            return self._from_admin(self.memory_admin.delete(memory_id))
        if action == "expire":
            return self._from_admin(self.memory_admin.expire(memory_id))
        if action == "pin":
            return self._from_admin(self.memory_admin.pin(memory_id, True))
        if action == "unpin":
            return self._from_admin(self.memory_admin.pin(memory_id, False))
        if action == "update":
            return self._handle_update(memory_id, parts[3:])

        return self._wrap(
            f"Unknown command: {action}\n{self.memory_admin.help_text()}",
            success=False,
        )

    def _handle_list(self, tokens: list[str]) -> CommandRouteResult:
        memory_type = None
        status = "active"
        for token in tokens:
            if token in {"profile", "episodic"}:
                memory_type = token
                continue
            if token in {"active", "expired", "archived"}:
                status = token
                continue
            return self._wrap(f"Unsupported list filter: {token}", success=False)

        return self._from_admin(
            self.memory_admin.list_memories(
                memory_type=memory_type,
                status=status,
            )
        )

    def _handle_update(self, memory_id: str, raw_updates: list[str]) -> CommandRouteResult:
        if not raw_updates:
            return self._wrap("Missing update fields.", success=False)

        updates: dict[str, object] = {}
        for item in raw_updates:
            if "=" not in item:
                return self._wrap(
                    f"Invalid update parameter: {item}",
                    success=False,
                )
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key not in {"content", "confidence", "expires_at", "summary", "status"}:
                return self._wrap(
                    f"Unsupported update field: {key}",
                    success=False,
                )
            if key == "confidence":
                try:
                    updates[key] = float(value)
                except ValueError:
                    return self._wrap("confidence must be numeric.", success=False)
                continue
            if key == "expires_at" and value.lower() in {"none", "null"}:
                updates[key] = None
                continue
            updates[key] = value

        return self._from_admin(self.memory_admin.update(memory_id, **updates))

    def _route_trace_command(self, user_input: str) -> CommandRouteResult:
        if self.trace_admin is None:
            return self._wrap("trace tools are currently unavailable.", success=False)
        try:
            parts = shlex.split(user_input)
        except ValueError as exc:
            return self._wrap(f"Failed to parse command: {exc}", success=False)

        if len(parts) == 1 or parts[1] in {"help", "-h", "--help"}:
            return self._from_trace(
                TraceAdminResult(True, self.trace_admin.help_text())
            )
        if parts[1] != "summary":
            return self._wrap(
                f"Unknown trace command: {parts[1]}\n{self.trace_admin.help_text()}",
                success=False,
            )

        trace_file = None
        event_name = None
        limit = 12
        index = 2
        while index < len(parts):
            token = parts[index]
            if token == "--file":
                if index + 1 >= len(parts):
                    return self._wrap("Missing value for --file.", success=False)
                trace_file = parts[index + 1]
                index += 2
                continue
            if token == "--limit":
                if index + 1 >= len(parts):
                    return self._wrap("Missing value for --limit.", success=False)
                try:
                    limit = max(1, int(parts[index + 1]))
                except ValueError:
                    return self._wrap("--limit must be numeric.", success=False)
                index += 2
                continue
            if token == "--event":
                if index + 1 >= len(parts):
                    return self._wrap("Missing value for --event.", success=False)
                event_name = parts[index + 1]
                index += 2
                continue
            return self._wrap(f"Unsupported trace option: {token}", success=False)

        return self._from_trace(
            self.trace_admin.summarize_trace_cluster(
                trace_file=trace_file,
                limit=limit,
                event_name=event_name,
            )
        )

    def _route_badcase_command(self, user_input: str) -> CommandRouteResult:
        if self.trace_admin is None:
            return self._wrap("trace tools are currently unavailable.", success=False)
        try:
            parts = shlex.split(user_input)
        except ValueError as exc:
            return self._wrap(f"Failed to parse command: {exc}", success=False)

        if len(parts) == 1 or parts[1] in {"help", "-h", "--help"}:
            return self._from_trace(
                TraceAdminResult(True, self.trace_admin.help_text())
            )
        if parts[1] != "draft":
            return self._wrap(
                f"Unknown badcase command: {parts[1]}\n{self.trace_admin.help_text()}",
                success=False,
            )

        target = "latest"
        trace_file = None
        index = 2
        if index < len(parts) and not parts[index].startswith("--"):
            target = parts[index]
            index += 1
        while index < len(parts):
            token = parts[index]
            if token == "--file":
                if index + 1 >= len(parts):
                    return self._wrap("Missing value for --file.", success=False)
                trace_file = parts[index + 1]
                index += 2
                continue
            return self._wrap(f"Unsupported badcase option: {token}", success=False)

        return self._from_trace(
            self.trace_admin.draft_badcase(target=target, trace_file=trace_file)
        )

    def _from_admin(self, result: MemoryAdminResult) -> CommandRouteResult:
        return CommandRouteResult(
            handled=True,
            output_text=result.message,
            success=result.success,
        )

    def _from_trace(self, result: TraceAdminResult) -> CommandRouteResult:
        return CommandRouteResult(
            handled=True,
            output_text=result.message,
            success=result.success,
        )

    def _wrap(self, message: str, *, success: bool) -> CommandRouteResult:
        return CommandRouteResult(
            handled=True,
            output_text=message,
            success=success,
        )
