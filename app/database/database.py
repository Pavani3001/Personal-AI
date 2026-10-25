from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import DATABASE_PATH
from app.database.base import BaseRepository, DatabaseError, utc_now
from app.database.postgres import PostgresRepository
from app.database.sqlite import SQLiteRepository

logger = logging.getLogger("app.database")


class Database(BaseRepository):
    """Unified Database repository facade.

    Automatically selects PostgresRepository for Vercel production deployment
    when DATABASE_URL is configured, and SQLiteRepository for local development/testing.
    """

    def __init__(self, target: Path | str | None = None, database_url: str | None = None) -> None:
        self._repo: BaseRepository = self._create_repository(target, database_url)

    @staticmethod
    def _create_repository(target: Path | str | None = None, database_url: str | None = None) -> BaseRepository:
        # 1. Explicit target provided (e.g. tests passing tmp_path / "test.db")
        if target is not None:
            target_str = str(target).strip()
            if target_str.startswith(("postgres://", "postgresql://")):
                return PostgresRepository(target_str)
            if target_str.startswith("sqlite:///"):
                return SQLiteRepository(target_str[len("sqlite:///"):])
            return SQLiteRepository(target)

        # 2. Check environment variable / explicit database_url
        env_url = (database_url or os.getenv("DATABASE_URL", "")).strip()
        if env_url:
            if env_url.startswith(("postgres://", "postgresql://")):
                return PostgresRepository(env_url)
            if env_url.startswith("sqlite:///"):
                return SQLiteRepository(env_url[len("sqlite:///"):])
            return SQLiteRepository(env_url)

        # 3. Running in Vercel production environment without DATABASE_URL
        if os.getenv("VERCEL"):
            raise RuntimeError(
                "DATABASE_URL environment variable is required for Vercel production deployment. "
                "Please add your hosted PostgreSQL connection URL (e.g. from Neon, Supabase) "
                "in your Vercel Project Settings -> Environment Variables."
            )

        # 4. Local development default: persistent SQLite
        logger.info("Using local SQLite storage at %s", DATABASE_PATH)
        return SQLiteRepository(DATABASE_PATH)

    @property
    def repository(self) -> BaseRepository:
        """The underlying active database repository."""
        return self._repo

    @property
    def backend_name(self) -> str:
        """Active storage backend: 'sqlite' or 'postgresql'."""
        return self._repo.backend_name

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Context manager yielding the active database connection."""
        if hasattr(self._repo, "connection"):
            with getattr(self._repo, "connection")() as conn:
                yield conn
        else:
            raise NotImplementedError("Connection context manager not supported on active repository.")

    def initialize(self) -> None:
        self._repo.initialize()

    def add_memory(self, content: str, memory_type: str, importance: int = 3) -> dict[str, Any]:
        return self._repo.add_memory(content, memory_type, importance)

    def get_memory(self, memory_id: int | None) -> dict[str, Any]:
        return self._repo.get_memory(memory_id)

    def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return self._repo.search_memories(query, limit)

    def list_memories(self) -> list[dict[str, Any]]:
        return self._repo.list_memories()

    def delete_memory(self, memory_id: int) -> None:
        self._repo.delete_memory(memory_id)

    def add_conversation(self, role: str, content: str) -> None:
        self._repo.add_conversation(role, content)

    def recent_conversations(self, limit: int = 12) -> list[dict[str, Any]]:
        return self._repo.recent_conversations(limit)

    def add_activity(self, label: str, detail: str, status: str = "completed") -> dict[str, Any]:
        return self._repo.add_activity(label, detail, status)

    def list_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        return self._repo.list_activity(limit)

    def add_task(self, title: str, status: str = "pending", result: str | None = None) -> dict[str, Any]:
        return self._repo.add_task(title, status, result)

    def list_tasks(self) -> list[dict[str, Any]]:
        return self._repo.list_tasks()

    def add_schedule(self, title: str, run_at: str) -> dict[str, Any]:
        return self._repo.add_schedule(title, run_at)

    def list_schedules(self) -> list[dict[str, Any]]:
        return self._repo.list_schedules()

    def add_approval(self, action: str, reason: str, resource: str, payload: str | None = None) -> dict[str, Any]:
        return self._repo.add_approval(action, reason, resource, payload)

    def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        return self._repo.list_approvals(status)

    def resolve_approval(self, approval_id: int, status: str) -> dict[str, Any]:
        return self._repo.resolve_approval(approval_id, status)

    def due_schedules(self, now: str) -> list[dict[str, Any]]:
        return self._repo.due_schedules(now)

    def complete_schedule(self, schedule_id: int, result: str) -> None:
        self._repo.complete_schedule(schedule_id, result)
