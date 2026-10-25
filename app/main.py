from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.agent import PersonalAgent
from app.agent.memory import MemoryManager
from app.agent.tools import ToolManager
from app.background.scheduler import BackgroundTaskManager
from app.config import NEBIUS_API_KEY, ROOT_DIR, validate_configuration
from app.database.base import DatabaseError
from app.database.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.main")

database = Database()
agent = PersonalAgent(database)
scheduler = BackgroundTaskManager(database)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        validate_configuration()
    except RuntimeError as exc:
        logger.warning("Configuration validation notice: %s", exc)
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(title="Personal AI", lifespan=lifespan, redirect_slashes=False)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "frontend"), name="static")


@app.exception_handler(DatabaseError)
async def database_exception_handler(_: Request, exc: DatabaseError) -> JSONResponse:
    logger.error("Database operation failed: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Database operation failed.", "error": str(exc)},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def global_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred.", "error": str(exc)},
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    memory_type: str = "fact"
    importance: int = Field(default=3, ge=1, le=5)


class ScheduleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    run_at: datetime


class ApprovalRequest(BaseModel):
    status: str


# Root and index handlers
@app.get("/")
@app.get("/api/index")
@app.get("/api/index.py")
async def index() -> FileResponse:
    return FileResponse(ROOT_DIR / "frontend" / "index.html")


# API Router handling both /api/* and prefixed requests cleanly
api_router = APIRouter()


@api_router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "nebius_configured": bool(NEBIUS_API_KEY),
        "database_backend": database.backend_name,
    }


@api_router.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        return await agent.run(request.message)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api_router.get("/memories")
async def memories() -> list[dict[str, Any]]:
    return MemoryManager(database).list_memories()


@api_router.post("/memories")
async def save_memory(request: MemoryRequest) -> dict[str, Any]:
    try:
        return MemoryManager(database).save_memory(request.content, request.memory_type, request.importance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@api_router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int) -> dict[str, bool]:
    MemoryManager(database).delete_memory(memory_id)
    return {"deleted": True}


@api_router.get("/approvals")
async def approvals() -> list[dict[str, Any]]:
    return database.list_approvals()


@api_router.post("/approvals/{approval_id}")
async def resolve_approval(approval_id: int, request: ApprovalRequest) -> dict[str, Any]:
    try:
        approval = database.resolve_approval(approval_id, request.status)
        if request.status == "approved":
            tool_manager = ToolManager()
            if approval["action"] == "write_file":
                filename, content = (approval.get("payload") or "").split("\n", 1)
                result = tool_manager.write_file(filename, content)
                if tool_manager.read_file(filename) != content:
                    raise RuntimeError("File verification failed after writing.")
                approval["execution"] = {"success": True, "resource": result}
            elif approval["action"] == "create_folder":
                result = tool_manager.create_folder(approval["resource"])
                if not (tool_manager.workspace / approval["resource"]).is_dir():
                    raise RuntimeError("Folder verification failed after creation.")
                approval["execution"] = {"success": True, "resource": result}
            else:
                raise ValueError(f"Unsupported approved action: {approval['action']}")
            database.add_activity("Action completed", f"Verified {result}")
        return approval
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Approved action failed: {exc}") from exc


@api_router.get("/schedules")
async def schedules() -> list[dict[str, Any]]:
    return database.list_schedules()


@api_router.post("/schedules")
async def schedule(request: ScheduleRequest) -> dict[str, Any]:
    if request.run_at <= datetime.now(request.run_at.tzinfo):
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future.")
    return database.add_schedule(request.title, request.run_at.isoformat())


@api_router.get("/activity")
async def activity() -> list[dict[str, Any]]:
    return database.list_activity()


# Mount api_router under /api (for /api/health, /api/chat, etc.) AND at root (for /health, /chat, etc.)
app.include_router(api_router, prefix="/api")
app.include_router(api_router)
