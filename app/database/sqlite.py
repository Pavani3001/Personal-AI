from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.database.base import BaseRepository, DatabaseError, utc_now

logger = logging.getLogger("app.database.sqlite")


class SQLiteRepository(BaseRepository):
    """SQLite implementation of BaseRepository for local development and testing."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @property
    def backend_name(self) -> str:
        return "sqlite"

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            logger.error("SQLite transaction failed: %s", exc)
            raise DatabaseError(f"SQLite error: {exc}") from exc
        finally:
            conn.close()

    def initialize(self) -> None:
        try:
            with self.connection() as db:
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        importance INTEGER NOT NULL DEFAULT 3,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS conversations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL,
                        result TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS scheduled_tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        run_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'scheduled',
                        result TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS approvals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        payload TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        created_at TEXT NOT NULL,
                        resolved_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS activity_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        label TEXT NOT NULL,
                        detail TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'completed',
                        created_at TEXT NOT NULL
                    );
                    """
                )
                columns = {row["name"] for row in db.execute("PRAGMA table_info(approvals)").fetchall()}
                if "payload" not in columns:
                    db.execute("ALTER TABLE approvals ADD COLUMN payload TEXT")
        except Exception as exc:
            logger.error("Failed to initialize SQLite database: %s", exc)
            raise DatabaseError(f"Failed to initialize SQLite: {exc}") from exc

    def add_memory(self, content: str, memory_type: str, importance: int = 3) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO memories(content, memory_type, importance, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (content.strip(), memory_type, importance, now, now),
            )
            row = db.execute("SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)).fetchone()
        if row is None:
            raise DatabaseError("Memory could not be created.")
        return dict(row)

    def get_memory(self, memory_id: int | None) -> dict[str, Any]:
        if memory_id is None:
            raise DatabaseError("Memory ID must be provided.")
        with self.connection() as db:
            row = db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise KeyError("Memory not found.")
        return dict(row)

    def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = [term for term in query.lower().split() if len(term) > 2]
        with self.connection() as db:
            if not terms:
                rows = db.execute(
                    "SELECT * FROM memories ORDER BY importance DESC, updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                clauses = " OR ".join("(lower(content) LIKE ? OR lower(memory_type) LIKE ?)" for _ in terms)
                params = [value for term in terms for value in (f"%{term}%", f"%{term}%")]
                rows = db.execute(
                    f"SELECT * FROM memories WHERE {clauses} ORDER BY importance DESC, updated_at DESC LIMIT ?",
                    (*params, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_memories(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM memories ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def delete_memory(self, memory_id: int) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

    def add_conversation(self, role: str, content: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO conversations(role, content, created_at) VALUES (?, ?, ?)",
                (role, content, utc_now()),
            )

    def recent_conversations(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_activity(self, label: str, detail: str, status: str = "completed") -> dict[str, Any]:
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO activity_events(label, detail, status, created_at) VALUES (?, ?, ?, ?)",
                (label, detail, status, utc_now()),
            )
            row = db.execute("SELECT * FROM activity_events WHERE id = ?", (cursor.lastrowid,)).fetchone()
        if row is None:
            raise DatabaseError("Activity event could not be created.")
        return dict(row)

    def list_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM activity_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_task(self, title: str, status: str = "pending", result: str | None = None) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO tasks(title, status, result, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (title, status, result, now, now),
            )
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
        if row is None:
            raise DatabaseError("Task could not be created.")
        return dict(row)

    def list_tasks(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM tasks ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def add_schedule(self, title: str, run_at: str) -> dict[str, Any]:
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO scheduled_tasks(title, run_at, created_at) VALUES (?, ?, ?)",
                (title, run_at, utc_now()),
            )
            row = db.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
        if row is None:
            raise DatabaseError("Scheduled task could not be created.")
        return dict(row)

    def list_schedules(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM scheduled_tasks ORDER BY run_at").fetchall()
        return [dict(row) for row in rows]

    def add_approval(self, action: str, reason: str, resource: str, payload: str | None = None) -> dict[str, Any]:
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO approvals(action, reason, resource, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (action, reason, resource, payload, utc_now()),
            )
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (cursor.lastrowid,)).fetchone()
        if row is None:
            raise DatabaseError("Approval could not be created.")
        return dict(row)

    def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_approval(self, approval_id: int, status: str) -> dict[str, Any]:
        if status not in {"approved", "rejected"}:
            raise ValueError("Approval status must be approved or rejected.")
        with self.connection() as db:
            db.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                (status, utc_now(), approval_id),
            )
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError("Approval not found.")
        return dict(row)

    def due_schedules(self, now: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM scheduled_tasks WHERE status = 'scheduled' AND run_at <= ?",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def complete_schedule(self, schedule_id: int, result: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE scheduled_tasks SET status = 'completed', result = ? WHERE id = ?",
                (result, schedule_id),
            )
