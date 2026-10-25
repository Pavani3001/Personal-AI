import asyncio
from pathlib import Path

from app.agent.memory import MemoryManager, detect_memory_candidate
from app.agent.permissions import PermissionManager
from app.agent.skills import select_skill
from app.agent.tools import ToolManager
from app.agent.agent import PersonalAgent
from app.agent.client import NebiusClient
from app.database.database import Database


def test_memory_save_and_retrieve(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    manager = MemoryManager(database)
    saved = manager.save_memory("I prefer concise answers", "preference", 4)
    assert saved["id"] > 0
    assert saved["memory_type"] == "preference"
    assert manager.retrieve_relevant_memories("What answer style do I prefer?")[0]["content"] == "I prefer concise answers"


def test_memory_candidate_detection():
    candidate = detect_memory_candidate("Remember that my goal is to become internship-ready in robotics.")
    assert candidate is not None
    assert candidate.content == "Your goal is to become internship-ready in robotics."
    assert candidate.memory_type == "goal"


def test_memory_candidate_detection_inside_long_task_request():
    candidate = detect_memory_candidate(
        "I want to prepare for a Machine Learning internship. "
        "Remember that my goal is to become internship-ready in machine learning. "
        "Create a 7-day plan."
    )
    assert candidate is not None
    assert candidate.memory_type == "goal"
    assert candidate.content == "Your goal is to become internship-ready in machine learning."


def test_memory_survives_application_restart(tmp_path: Path):
    database_path = tmp_path / "restart.db"
    MemoryManager(Database(database_path)).save_memory("Your goal is to learn robotics.", "goal", 5)
    restarted_manager = MemoryManager(Database(database_path))
    memories = restarted_manager.retrieve_relevant_memories("What is my current goal?")
    assert memories[0]["content"] == "Your goal is to learn robotics."


def test_memory_delete_and_list(tmp_path: Path):
    manager = MemoryManager(Database(tmp_path / "delete.db"))
    saved = manager.save_memory("Your favorite color is blue.", "fact")
    assert len(manager.list_memories()) == 1
    manager.delete_memory(saved["id"])
    assert manager.list_memories() == []


def test_broad_memory_recall_lists_actual_memories(tmp_path: Path):
    manager = MemoryManager(Database(tmp_path / "broad.db"))
    manager.save_memory("Your goal is to become internship-ready in robotics.", "goal", 5)
    memories = manager.retrieve_relevant_memories("What do you remember about me?")
    assert memories[0]["content"] == "Your goal is to become internship-ready in robotics."


def test_skill_routing():
    assert select_skill("research my notes").name == "research"
    assert select_skill("summarize this").name == "summarize"


def test_sensitive_action_requires_approval(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    permission = PermissionManager(database)
    request = permission.assess("write_file", "update", "notes.md")
    assert permission.requires_approval(request)
    assert permission.request_approval(request)["status"] == "pending"


def test_tools_restrict_workspace(tmp_path: Path):
    tools = ToolManager(tmp_path)
    tools.write_file("notes.txt", "hello")
    assert tools.read_file("notes.txt") == "hello"
    try:
        tools.read_file("../outside.txt")
    except ValueError:
        pass
    else:
        raise AssertionError("Path traversal should be rejected")


def test_tools_create_folder(tmp_path: Path):
    tools = ToolManager(tmp_path)
    assert tools.create_folder("robotics") == "robotics"
    assert (tmp_path / "robotics").is_dir()


def test_tools_list_files_returns_nested_files(tmp_path: Path):
    tools = ToolManager(tmp_path)
    tools.write_file("robotics/plan.md", "# Plan")
    tools.write_file("notes.txt", "notes")
    files = tools.list_files()
    assert [item["path"] for item in files] == ["notes.txt", "robotics/plan.md"]
    assert tools.list_files("robotics")[0]["path"] == "robotics/plan.md"


def test_agent_answers_file_count_from_workspace(tmp_path: Path):
    database = Database(tmp_path / "inspection.db")
    agent = PersonalAgent(database)
    agent.tools = ToolManager(tmp_path / "workspace")
    agent.tools.write_file("robotics/plan.md", "# Plan")
    result = asyncio.run(agent.run("How many files did you create in my folder?"))
    assert "1 file(s)" in result["response"]
    assert "robotics/plan.md" in result["response"]
    assert any(item["label"] == "Tool selected" for item in result["trace"])


def test_agent_creates_approval_for_folder_request(tmp_path: Path):
    database = Database(tmp_path / "folder.db")
    result = asyncio.run(PersonalAgent(database).run("Create a folder robotics-notes"))
    assert result["approval"]["action"] == "create_folder"
    assert database.list_approvals()[0]["resource"] == "robotics-notes"


def test_agent_targets_file_inside_named_folder(tmp_path: Path):
    database = Database(tmp_path / "nested.db")
    agent = PersonalAgent(database)

    async def draft(*args, **kwargs):
        return "# Robotics plan"

    agent.client.respond = draft
    result = asyncio.run(
        agent.run("Create the file robotics_7_day_plan.md inside the folder robotics")
    )
    assert result["approval"]["resource"] == "robotics/robotics_7_day_plan.md"
    assert result["approval"]["payload"].startswith("robotics/robotics_7_day_plan.md\n")


def test_project_folder_does_not_invent_folder_name(tmp_path: Path):
    database = Database(tmp_path / "project-folder.db")
    agent = PersonalAgent(database)

    async def draft(*args, **kwargs):
        return "# Plan"

    agent.client.respond = draft
    result = asyncio.run(agent.run("Create ML_7_day_plan.md in my project folder"))
    assert result["approval"]["resource"] == "ML_7_day_plan.md"


def test_agent_recovers_filename_from_follow_up(tmp_path: Path):
    database = Database(tmp_path / "context.db")
    agent = PersonalAgent(database)
    database.add_conversation("assistant", "I can create the file `robotics_7_day_plan.md` after approval.")

    async def draft(*args, **kwargs):
        return "# Robotics plan\nDay 1"

    agent.client.respond = draft
    result = asyncio.run(agent.run("go ahead and add it into the folder now"))
    assert result["approval"]["resource"] == "robotics_7_day_plan.md"


def test_conversational_approval_executes_pending_file(tmp_path: Path):
    database = Database(tmp_path / "approval.db")
    agent = PersonalAgent(database)
    approval = database.add_approval("write_file", "create file", "notes.md", "notes.md\n# Notes")
    try:
        result = asyncio.run(agent.run("yes, I approve it - create it now"))
        assert result["execution"]["success"] is True
        assert result["execution"]["resource"] == "notes.md"
        assert (agent.tools.workspace / "notes.md").read_text(encoding="utf-8") == "# Notes"
        assert database.list_approvals() == []
    finally:
        (agent.tools.workspace / "notes.md").unlink(missing_ok=True)


def test_approved_folder_is_verified(tmp_path: Path):
    database = Database(tmp_path / "folder-approval.db")
    agent = PersonalAgent(database)
    database.add_approval("create_folder", "create folder", "verified-folder")
    try:
        result = asyncio.run(agent.run("approved, create it now"))
        assert result["execution"]["resource"] == "verified-folder"
        assert (agent.tools.workspace / "verified-folder").is_dir()
    finally:
        (agent.tools.workspace / "verified-folder").rmdir()


def test_activity_timeline_persists(tmp_path: Path):
    database = Database(tmp_path / "activity.db")
    database.add_activity("Action completed", "Created robotics/plan.md")
    restarted = Database(tmp_path / "activity.db")
    events = restarted.list_activity()
    assert events[0]["label"] == "Action completed"
    assert events[0]["detail"] == "Created robotics/plan.md"


def test_nebius_client_retries_transient_failure(monkeypatch):
    client = NebiusClient()
    attempts = 0

    def call(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        return type("Response", (), {
            "choices": [type("Choice", (), {
                "message": type("Message", (), {"content": "ok"})()
            })()]
        })()

    monkeypatch.setattr(client.client.chat.completions, "create", call)
    assert asyncio.run(client.respond("system", "user")) == "ok"
    assert attempts == 2


def test_static_files_and_frontend_serving():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Test root and index
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "Personal AI" in res_root.text

    # Test static style and script paths
    res_style_static = client.get("/static/style.css")
    assert res_style_static.status_code == 200
    assert "text/css" in res_style_static.headers["content-type"]

    res_app_static = client.get("/static/app.js")
    assert res_app_static.status_code == 200
    assert "javascript" in res_app_static.headers["content-type"]

    # Test root style and script fallback paths
    res_style_root = client.get("/style.css")
    assert res_style_root.status_code == 200

    res_app_root = client.get("/app.js")
    assert res_app_root.status_code == 200

