from __future__ import annotations

from dataclasses import dataclass

from src.memory.manager import MemoryManager
from src.memory.models import MemoryItem


_UNSET = object()


@dataclass(frozen=True)
class MemoryAdminResult:
    success: bool
    message: str


class MemoryAdminService:
    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    def list_memories(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = "active",
        limit: int = 50,
    ) -> MemoryAdminResult:
        items = self.memory_manager.list_memories(
            memory_type=memory_type,
            status=status,
            limit=limit,
        )
        title_parts = [status or "all", memory_type or "all"]
        header = f"{' '.join(title_parts)} memories: {len(items)}"
        if not items:
            return MemoryAdminResult(True, f"{header}\n- empty")
        lines = [header]
        for item in items:
            lines.append(self._format_item(item))
        return MemoryAdminResult(True, "\n".join(lines))

    def archive(self, memory_id: str) -> MemoryAdminResult:
        item = self.memory_manager.archive_memory(memory_id)
        if item is None:
            return MemoryAdminResult(False, f"Memory not found: {memory_id}")
        return MemoryAdminResult(True, f"Archived: {self._format_item(item)}")

    def delete(self, memory_id: str) -> MemoryAdminResult:
        deleted = self.memory_manager.delete_memory(memory_id)
        if not deleted:
            return MemoryAdminResult(False, f"Memory not found: {memory_id}")
        return MemoryAdminResult(True, f"Deleted: {memory_id}")

    def expire(self, memory_id: str) -> MemoryAdminResult:
        item = self.memory_manager.expire_memory(memory_id)
        if item is None:
            return MemoryAdminResult(False, f"Memory not found: {memory_id}")
        return MemoryAdminResult(True, f"Expired: {self._format_item(item)}")

    def pin(self, memory_id: str, pinned: bool) -> MemoryAdminResult:
        item = self.memory_manager.set_pinned(memory_id, pinned)
        if item is None:
            return MemoryAdminResult(False, f"Memory not found: {memory_id}")
        action = "Pinned" if pinned else "Unpinned"
        return MemoryAdminResult(True, f"{action}: {self._format_item(item)}")

    def update(
        self,
        memory_id: str,
        *,
        content: str | object = _UNSET,
        confidence: float | object = _UNSET,
        expires_at: str | None | object = _UNSET,
        summary: str | None | object = _UNSET,
        status: str | object = _UNSET,
    ) -> MemoryAdminResult:
        update_kwargs: dict[str, object] = {}
        if content is not _UNSET:
            update_kwargs["content"] = content
        if confidence is not _UNSET:
            update_kwargs["confidence"] = confidence
        if expires_at is not _UNSET:
            update_kwargs["expires_at"] = expires_at
        if summary is not _UNSET:
            update_kwargs["summary"] = summary
        if status is not _UNSET:
            update_kwargs["status"] = status
        item = self.memory_manager.update_memory(memory_id, **update_kwargs)
        if item is None:
            return MemoryAdminResult(False, f"Memory not found: {memory_id}")
        return MemoryAdminResult(True, f"Updated: {self._format_item(item)}")

    def help_text(self) -> str:
        return "\n".join(
            [
                "/memory list",
                "/memory list profile",
                "/memory list episodic active",
                "/memory list archived",
                "/memory archive <id>",
                "/memory delete <id>",
                "/memory expire <id>",
                "/memory pin <id>",
                "/memory unpin <id>",
                '/memory update <id> content="..." confidence=0.95',
            ]
        )

    def _format_item(self, item: MemoryItem) -> str:
        tags = ",".join(item.tags) if item.tags else "-"
        due_at = item.followup_due_at or "-"
        expires_at = item.expires_at or "-"
        return (
            f"- {item.id} | {item.memory_type} | status={item.status} | "
            f"conf={item.confidence:.2f} | pinned={'yes' if item.pinned else 'no'} | "
            f"merge={item.merge_count} | tags={tags} | expires={expires_at} | "
            f"followup_due={due_at} | {item.display_text()}"
        )
