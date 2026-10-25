from __future__ import annotations

import logging
import re
import urllib.parse
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from app.database.base import BaseRepository, DatabaseError, utc_now

logger = logging.getLogger("app.database.postgres")


def mask_database_url(url: str) -> str:
    """Mask password in a database connection URL for safe logging."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.password:
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return re.sub(r"://([^:@]+):([^@]+)@", r"://\1:****@", url)


class PostgresRepository(BaseRepository):
    """Hosted PostgreSQL implementation of BaseRepository for Vercel production deployment."""

    def __init__(self, database_url: str, min_conn: int = 1, max_conn: int = 5) -> None:
        self.raw_url = database_url
        self.normalized_url = self._normalize_url(database_url)
        self.masked_url = mask_database_url(self.normalized_url)
        self.min_conn = min_conn
        self.max_conn = max_conn
        self._pool: ThreadedConnectionPool | None = None
        self._init_pool()
        self.initialize()

    @property
    def backend_name(self) -> str:
        return "postgresql"

    @staticmethod
    def _normalize_url(url: str) -> str:
        trimmed = url.strip()
        if trimmed.startswith("postgres://"):
            trimmed = "postgresql://" + trimmed[len("postgres://"):]
        return trimmed

    def _init_pool(self) -> None:
        try:
            logger.info("Initializing PostgreSQL connection pool (%s)", self.masked_url)
            self._pool = ThreadedConnectionPool(
                self.min_conn,
                self.max_conn,
                self.normalized_url,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
        except Exception as exc:
            logger.error("Failed to initialize PostgreSQL connection pool: %s", exc)
            self._pool = None

    def _is_alive(self, conn: psycopg2.extensions.connection) -> bool:
        """Check if connection is open and responsive (pre-ping)."""
        if conn.closed != 0:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
            return True
        except Exception:
            return False

    @contextmanager
    def connection(self) -> Iterator[psycopg2.extensions.connection]:
        """Provide a validated, serverless-safe connection from pool or direct connect."""
        conn: psycopg2.extensions.connection | None = None
        from_pool = False

        if self._pool is not None:
            try:
                conn = self._pool.getconn()
                from_pool = True
                if not self._is_alive(conn):
                    logger.debug("Discarding stale connection and reconnecting...")
                    try:
                        self._pool.putconn(conn, close=True)
                    except Exception:
                        pass
                    conn = psycopg2.connect(
                        self.normalized_url,
                        cursor_factory=psycopg2.extras.RealDictCursor,
                    )
                    from_pool = False
            except Exception as exc:
                logger.warning("Could not obtain connection from pool: %s; falling back to direct connection", exc)
                conn = None

        if conn is None:
            try:
                conn = psycopg2.connect(
                    self.normalized_url,
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
                from_pool = False
            except Exception as exc:
                logger.error("Failed to connect to PostgreSQL database: %s", exc)
                raise DatabaseError(f"Database connection error: {exc}") from exc

        try:
            yield conn
            conn.commit()
        except Exception as exc:
            if conn and conn.closed == 0:
                conn.rollback()
            logger.error("PostgreSQL query execution failed: %s", exc)
            raise DatabaseError(f"PostgreSQL query error: {exc}") from exc
        finally:
            if conn is not None:
                if from_pool and self._pool is not None:
                    try:
                        self._pool.putconn(conn)
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
                else:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def initialize(self) -> None:
        """Initialize PostgreSQL tables safely for concurrent serverless environments."""
        statements = [
            """
            CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                run_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled',
                result TEXT,
                created_at TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id SERIAL PRIMARY KEY,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                resource TEXT NOT NULL,
                payload TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS activity_events (
                id SERIAL PRIMARY KEY,
                label TEXT NOT NULL,
                detail TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at TEXT NOT NULL
            );
            """,
        ]
        with self.connection() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    try:
                        cur.execute(statement)
                    except Exception as exc:
                        logger.warning("Table initialization notice: %s", exc)
                # Safe migration check: add payload column to approvals if missing
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'approvals' AND column_name = 'payload';
                    """
                )
                if not cur.fetchone():
                    try:
                        cur.execute("ALTER TABLE approvals ADD COLUMN payload TEXT;")
                    except Exception as exc:
                        logger.warning("Column addition notice: %s", exc)

    def add_memory(self, content: str, memory_type: str, importance: int = 3) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memories(content, memory_type, importance, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *;
                    """,
                    (content.strip(), memory_type, importance, now, now),
                )
                row = cur.fetchone()
        if row is None:
            raise DatabaseError("Memory could not be created.")
        return dict(row)

    def get_memory(self, memory_id: int | None) -> dict[str, Any]:
        if memory_id is None:
            raise DatabaseError("Memory ID must be provided.")
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM memories WHERE id = %s;", (memory_id,))
                row = cur.fetchone()
        if row is None:
            raise KeyError("Memory not found.")
        return dict(row)

    def search_memories(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = [term for term in query.lower().split() if len(term) > 2]
        with self.connection() as conn:
            with conn.cursor() as cur:
                if not terms:
                    cur.execute(
                        "SELECT * FROM memories ORDER BY importance DESC, updated_at DESC LIMIT %s;",
                        (limit,),
                    )
                else:
                    clauses = " OR ".join("(lower(content) LIKE %s OR lower(memory_type) LIKE %s)" for _ in terms)
                    params: list[Any] = [value for term in terms for value in (f"%{term}%", f"%{term}%")]
                    params.append(limit)
                    cur.execute(
                        f"SELECT * FROM memories WHERE {clauses} ORDER BY importance DESC, updated_at DESC LIMIT %s;",
                        params,
                    )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def list_memories(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM memories ORDER BY updated_at DESC;")
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def delete_memory(self, memory_id: int) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memories WHERE id = %s;", (memory_id,))

    def add_conversation(self, role: str, content: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO conversations(role, content, created_at) VALUES (%s, %s, %s);",
                    (role, content, utc_now()),
                )

    def recent_conversations(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM conversations ORDER BY id DESC LIMIT %s;",
                    (limit,),
                )
                rows = cur.fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_activity(self, label: str, detail: str, status: str = "completed") -> dict[str, Any]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO activity_events(label, detail, status, created_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *;
                    """,
                    (label, detail, status, utc_now()),
                )
                row = cur.fetchone()
        if row is None:
            raise DatabaseError("Activity event could not be created.")
        return dict(row)

    def list_activity(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM activity_events ORDER BY id DESC LIMIT %s;",
                    (limit,),
                )
                rows = cur.fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_task(self, title: str, status: str = "pending", result: str | None = None) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tasks(title, status, result, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *;
                    """,
                    (title, status, result, now, now),
                )
                row = cur.fetchone()
        if row is None:
            raise DatabaseError("Task could not be created.")
        return dict(row)

    def list_tasks(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tasks ORDER BY updated_at DESC;")
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def add_schedule(self, title: str, run_at: str) -> dict[str, Any]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO scheduled_tasks(title, run_at, created_at)
                    VALUES (%s, %s, %s)
                    RETURNING *;
                    """,
                    (title, run_at, utc_now()),
                )
                row = cur.fetchone()
        if row is None:
            raise DatabaseError("Scheduled task could not be created.")
        return dict(row)

    def list_schedules(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM scheduled_tasks ORDER BY run_at;")
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def add_approval(self, action: str, reason: str, resource: str, payload: str | None = None) -> dict[str, Any]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO approvals(action, reason, resource, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *;
                    """,
                    (action, reason, resource, payload, utc_now()),
                )
                row = cur.fetchone()
        if row is None:
            raise DatabaseError("Approval could not be created.")
        return dict(row)

    def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM approvals WHERE status = %s ORDER BY created_at DESC;",
                    (status,),
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def resolve_approval(self, approval_id: int, status: str) -> dict[str, Any]:
        if status not in {"approved", "rejected"}:
            raise ValueError("Approval status must be approved or rejected.")
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE approvals
                    SET status = %s, resolved_at = %s
                    WHERE id = %s
                    RETURNING *;
                    """,
                    (status, utc_now(), approval_id),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError("Approval not found.")
        return dict(row)

    def due_schedules(self, now: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM scheduled_tasks WHERE status = 'scheduled' AND run_at <= %s;",
                    (now,),
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def complete_schedule(self, schedule_id: int, result: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE scheduled_tasks SET status = 'completed', result = %s WHERE id = %s;",
                    (result, schedule_id),
                )
