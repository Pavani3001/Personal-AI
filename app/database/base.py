from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class BaseRepository(ABC):
    """Abstract base repository for Personal AI persistent storage."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Name of the database backend (e.g. 'sqlite' or 'postgresql')."""
        pass

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database schema, tables, and migrations."""
        pass

    @abstractmethod
    def add_memory(self, content: str, memory_type: str, importance: int = 3) -> dict[str, Any]:
        """Save a new memory."""
        pass

    @abstractmethod
    def get_memory(self, memory_id: int | None) -> dict[str, Any]:
        """Retrieve a memory by ID."""
        pass

    @abstractmethod
    def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search memories matching query."""
        pass

    @abstractmethod
    def list_memories(self) -> list[dict[str, Any]]:
        """List all memories ordered by updated_at descending."""
        pass

    @abstractmethod
    def delete_memory(self, memory_id: int) -> None:
        """Delete a memory by ID."""
        pass

    @abstractmethod
    def add_conversation(self, role: str, content: str) -> None:
        """Record a conversation message."""
        pass

    @abstractmethod
    def recent_conversations(self, limit: int = 12) -> list[dict[str, Any]]:
        """List recent conversation messages."""
        pass

    @abstractmethod
    def add_activity(self, label: str, detail: str, status: str = "completed") -> dict[str, Any]:
        """Record an activity event."""
        pass

    @abstractmethod
    def list_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        """List recent activity events."""
        pass

    @abstractmethod
    def add_task(self, title: str, status: str = "pending", result: str | None = None) -> dict[str, Any]:
        """Record a task."""
        pass

    @abstractmethod
    def list_tasks(self) -> list[dict[str, Any]]:
        """List all tasks."""
        pass

    @abstractmethod
    def add_schedule(self, title: str, run_at: str) -> dict[str, Any]:
        """Create a scheduled reminder/task."""
        pass

    @abstractmethod
    def list_schedules(self) -> list[dict[str, Any]]:
        """List all scheduled tasks."""
        pass

    @abstractmethod
    def add_approval(self, action: str, reason: str, resource: str, payload: str | None = None) -> dict[str, Any]:
        """Create a pending action approval request."""
        pass

    @abstractmethod
    def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        """List approvals by status."""
        pass

    @abstractmethod
    def resolve_approval(self, approval_id: int, status: str) -> dict[str, Any]:
        """Resolve an approval to 'approved' or 'rejected'."""
        pass

    @abstractmethod
    def due_schedules(self, now: str) -> list[dict[str, Any]]:
        """List schedules due for execution on or before now."""
        pass

    @abstractmethod
    def complete_schedule(self, schedule_id: int, result: str) -> None:
        """Mark a scheduled task as completed with result."""
        pass
