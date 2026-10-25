from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database.base import BaseRepository, DatabaseError
from app.database.database import Database
from app.database.postgres import PostgresRepository, mask_database_url
from app.database.sqlite import SQLiteRepository
from app.main import app


def test_mask_database_url():
    url = "postgresql://myuser:secret_pass123@ep-cool-db.aws.neon.tech:5432/neondb?sslmode=require"
    masked = mask_database_url(url)
    assert "secret_pass123" not in masked
    assert "myuser:****@ep-cool-db.aws.neon.tech" in masked
    assert "neondb" in masked


def test_database_factory_resolution(tmp_path: Path, monkeypatch):
    # 1. Direct path
    db_path = Database(tmp_path / "custom.db")
    assert db_path.backend_name == "sqlite"
    assert isinstance(db_path.repository, SQLiteRepository)

    # 2. sqlite:/// URL
    db_url = Database(database_url=f"sqlite:///{tmp_path / 'url.db'}")
    assert db_url.backend_name == "sqlite"

    # 3. postgresql URL (without connecting, patch PostgresRepository.__init__)
    with patch.object(PostgresRepository, "__init__", return_value=None):
        db_pg = Database(database_url="postgresql://user:pass@localhost:5432/testdb")
        assert db_pg.backend_name == "postgresql"

    # 4. Vercel environment without DATABASE_URL raises RuntimeError
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL environment variable is required"):
        Database()


def test_sqlite_repository_full_crud(tmp_path: Path):
    repo = SQLiteRepository(tmp_path / "crud.db")
    assert repo.backend_name == "sqlite"

    # Memory
    mem = repo.add_memory("I prefer dark mode", "preference", 4)
    assert mem["id"] > 0
    assert mem["content"] == "I prefer dark mode"
    assert repo.get_memory(mem["id"])["content"] == "I prefer dark mode"
    assert len(repo.list_memories()) == 1
    assert len(repo.search_memories("dark mode")) == 1
    repo.delete_memory(mem["id"])
    assert len(repo.list_memories()) == 0

    # Conversation
    repo.add_conversation("user", "Hello agent")
    repo.add_conversation("assistant", "Hello human")
    recent = repo.recent_conversations(5)
    assert len(recent) == 2
    assert recent[0]["role"] == "user"
    assert recent[1]["role"] == "assistant"

    # Activity
    act = repo.add_activity("Planning", "Created initial plan")
    assert act["label"] == "Planning"
    assert len(repo.list_activity()) == 1

    # Task
    task = repo.add_task("Build feature", "pending")
    assert task["title"] == "Build feature"
    assert len(repo.list_tasks()) == 1

    # Schedule
    now_iso = datetime.now(timezone.utc).isoformat()
    sched = repo.add_schedule("Reminder task", now_iso)
    assert sched["title"] == "Reminder task"
    assert len(repo.list_schedules()) == 1
    due = repo.due_schedules((datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
    assert len(due) == 1
    repo.complete_schedule(sched["id"], "Done successfully")
    assert repo.list_schedules()[0]["status"] == "completed"

    # Approval
    appr = repo.add_approval("write_file", "Create report", "report.md", "report.md\n# Content")
    assert appr["status"] == "pending"
    assert len(repo.list_approvals()) == 1
    resolved = repo.resolve_approval(appr["id"], "approved")
    assert resolved["status"] == "approved"
    assert len(repo.list_approvals("pending")) == 0


def test_persistence_across_restart(tmp_path: Path):
    db_file = tmp_path / "persistent.db"

    # Session 1: Create application state
    db1 = Database(db_file)
    db1.add_memory("Target internship: robotics engineering", "goal", 5)
    db1.add_conversation("user", "Save my goal")
    db1.add_conversation("assistant", "Saved your goal")
    db1.add_task("Weekly Milestone 1", "pending")
    db1.add_schedule("Check progress", "2026-11-01T00:00:00Z")
    db1.add_approval("create_folder", "create folder", "robotics_project")
    db1.add_activity("Init", "Started project")

    # Session 2: "Restart" application by instantiating new Database object pointing to same storage
    db2 = Database(db_file)

    # Verify all entities survive restart
    memories = db2.list_memories()
    assert len(memories) == 1
    assert memories[0]["content"] == "Target internship: robotics engineering"

    conversations = db2.recent_conversations()
    assert len(conversations) == 2
    assert conversations[0]["content"] == "Save my goal"

    tasks = db2.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Weekly Milestone 1"

    schedules = db2.list_schedules()
    assert len(schedules) == 1
    assert schedules[0]["title"] == "Check progress"

    approvals = db2.list_approvals("pending")
    assert len(approvals) == 1
    assert approvals[0]["resource"] == "robotics_project"

    activity = db2.list_activity()
    assert len(activity) == 1
    assert activity[0]["label"] == "Init"


def test_postgres_repository_logic_and_queries():
    """Verify PostgresRepository prepares correct PostgreSQL queries and handles serverless pooling."""
    mock_conn = MagicMock()
    mock_conn.closed = 0
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch.object(PostgresRepository, "initialize", return_value=None), \
         patch.object(PostgresRepository, "_init_pool", return_value=None):
        repo = PostgresRepository("postgresql://user:pass@localhost:5432/testdb")
        repo._pool = None

        # Patch connection context manager
        with patch.object(repo, "connection") as mock_ctx:
            mock_ctx.return_value.__enter__.return_value = mock_conn

            # 1. add_memory uses RETURNING *
            mock_cur.fetchone.return_value = {
                "id": 1, "content": "PG memory", "memory_type": "goal",
                "importance": 5, "created_at": "2026-10-25T00:00:00Z", "updated_at": "2026-10-25T00:00:00Z"
            }
            mem = repo.add_memory("PG memory", "goal", 5)
            assert mem["id"] == 1
            executed_sql = mock_cur.execute.call_args[0][0]
            assert "RETURNING *" in executed_sql
            assert "%s" in executed_sql

            # 2. search_memories uses %s
            mock_cur.fetchall.return_value = [mem]
            res = repo.search_memories("PG memory")
            assert len(res) == 1
            search_sql = mock_cur.execute.call_args[0][0]
            assert "LIKE %s" in search_sql

            # 3. resolve_approval uses RETURNING *
            mock_cur.fetchone.return_value = {"id": 1, "status": "approved"}
            appr = repo.resolve_approval(1, "approved")
            assert appr["status"] == "approved"
            resolve_sql = mock_cur.execute.call_args[0][0]
            assert "RETURNING *" in resolve_sql


def test_api_endpoints_work_and_return_json(tmp_path: Path):
    test_db = Database(tmp_path / "api_test.db")
    # Patch main's database and agent's database references
    with patch("app.main.database", test_db), \
         patch("app.main.agent.database", test_db), \
         patch("app.main.agent.memory.database", test_db), \
         patch("app.main.agent.permissions.database", test_db):
        client = TestClient(app)

        # Verify api/index.py exports the exact same app
        from api.index import app as vercel_app
        assert vercel_app is app

        # 1. Health check via /api/health and /health alias
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/json")
        data = res.json()
        assert data["ok"] is True
        assert "database_backend" in data

        res_alias = client.get("/health")
        assert res_alias.status_code == 200
        assert res_alias.headers["content-type"].startswith("application/json")
        assert res_alias.json()["ok"] is True

        # Verify root returns index html
        res_root = client.get("/")
        assert res_root.status_code == 200

        # 2. Create and Read Memory
        res = client.post("/api/memories", json={"content": "I like fast APIs", "memory_type": "preference", "importance": 4})
        assert res.status_code == 200
        mem = res.json()
        assert mem["id"] > 0
        assert mem["content"] == "I like fast APIs"

        res = client.get("/api/memories")
        assert res.status_code == 200
        mems = res.json()
        assert len(mems) >= 1
        assert any(m["content"] == "I like fast APIs" for m in mems)

        # 3. Create Schedule
        future_iso = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        res = client.post("/api/schedules", json={"title": "Review PR", "run_at": future_iso})
        assert res.status_code == 200
        sched = res.json()
        assert sched["title"] == "Review PR"

        res = client.get("/api/schedules")
        assert res.status_code == 200
        assert len(res.json()) >= 1

        # 4. Approvals
        test_db.add_approval("write_file", "Write docs", "docs.md", "docs.md\n# Docs")
        res = client.get("/api/approvals")
        assert res.status_code == 200
        approvals = res.json()
        assert len(approvals) >= 1

        # 5. Activity
        res = client.get("/api/activity")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

        # 6. Chat endpoint (save a memory via chat)
        res = client.post("/api/chat", json={"message": "Remember that my goal is to deploy on Vercel."})
        assert res.status_code == 200
        chat_data = res.json()
        assert "Saved your memory" in chat_data["response"]
        assert len(chat_data["trace"]) > 0

        # Verify chat persisted conversation and memory
        assert len(test_db.list_memories()) >= 2
        assert len(test_db.recent_conversations()) >= 2


def test_api_errors_return_proper_json(tmp_path: Path):
    test_db = Database(tmp_path / "errors.db")
    with patch("app.main.database", test_db):
        client = TestClient(app, raise_server_exceptions=False)

        # 1. 400 Bad Request returns JSON {"detail": ...}
        res = client.post("/api/chat", json={"message": "   "})
        assert res.status_code == 400
        assert res.headers["content-type"].startswith("application/json")
        assert "detail" in res.json()

        # 2. Database error returns 500 JSON, not plain-text
        with patch.object(test_db, "list_memories", side_effect=DatabaseError("DB read failed")):
            res = client.get("/api/memories")
            assert res.status_code == 500
            assert res.headers["content-type"].startswith("application/json")
            json_resp = res.json()
            assert "detail" in json_resp
            assert "Database operation failed" in json_resp["detail"]

        # 3. Unhandled Exception returns 500 JSON, not plain-text
        with patch.object(test_db, "list_approvals", side_effect=ZeroDivisionError("Unexpected failure")):
            res = client.get("/api/approvals")
            assert res.status_code == 500
            assert res.headers["content-type"].startswith("application/json")
            json_resp = res.json()
            assert "detail" in json_resp
            assert "An internal server error occurred" in json_resp["detail"]
