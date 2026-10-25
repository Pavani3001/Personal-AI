# Personal AI

A persistent, approval-aware personal AI agent built with FastAPI, intelligent memory management, and dual-backend persistent storage (PostgreSQL for Vercel production & SQLite for local development).

## Problem and solution

Normal chatbots forget context and only answer one prompt at a time. Personal AI keeps useful memories in SQLite, selects reusable skills, plans multi-step work, runs constrained tools, verifies results, and pauses before sensitive actions.

## Features

- Nebius Token Factory inference using NVIDIA `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`.
- Persistent memories, conversations, tasks, approvals, and scheduled reminders.
- Agent trace showing memory retrieval, goal understanding, skill selection, execution, and verification without exposing chain-of-thought.
- Reusable research, summarize, organize, and task-planning skills.
- Workspace-scoped file tools with path traversal protection.
- Approval queue for writes, deletes, and external communication.
- Approved file and folder actions are executed inside `workspace/`; the browser reports the created relative path.
- Workspace questions such as “how many files did you create?” use a real filesystem inspection tool and report verified paths instead of relying on model memory.
- Lightweight always-on scheduler that records due reminders and publishes durable completion events.
- Persistent verified activity timeline providing transparent, verifiable proof of memory, approval, execution, and background work.

## Architecture

The browser calls FastAPI. The agent retrieves memory, creates a plan, selects a skill, assesses permissions, calls the dedicated Nebius OpenAI-compatible client, verifies the response, and stores useful context. Persistent storage is managed via a clean repository abstraction supporting hosted PostgreSQL (for serverless Vercel deployments) and SQLite (for local development). The background manager polls scheduled tasks. Every meaningful state transition is recorded in an activity timeline, so the UI proves what happened instead of relying on model claims.

Nebius Token Factory is part of the runtime inference path, not a mock or an offline fallback. The API key is loaded only by the server from `.env` and is never sent to the browser.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Create `.env`:

```env
NEBIUS_API_KEY=your_server_side_key
# Optional: NEBIUS_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
# Production on Vercel:
# DATABASE_URL=postgresql://user:password@host:5432/database?sslmode=require
```

Open `http://127.0.0.1:8000`. The `workspace/` directory is the only location exposed to file tools. File and folder creation is approval-gated: the agent prepares the action, the UI approval executes it, and the resulting relative path is shown in the chat.

## Testing

```powershell
pytest -q
```

Tests cover persistent memory retrieval, skill routing, approval creation, and safe workspace operations. A live Nebius call is intentionally not made by the unit suite; the server uses the configured key at runtime and `/api/health` reports only whether configuration exists.

## Security and recovery

`.env` and SQLite files are ignored by Git. Inputs are validated with Pydantic, file tools are restricted to `workspace/`, arbitrary shell execution is not available, and sensitive actions require explicit approval. Failed model/tool operations return a safe error to the user rather than a fabricated success. The next iteration can add durable action retries and notifications.

## Roadmap and future work

Personal AI is designed as an approval-first execution companion: it remembers long-term goals, turns them into concrete project artifacts, verifies those artifacts, and continues with scheduled progress support. Future improvements include:
- Semantic memory embeddings and hybrid vector search
- Richer tool adapters and external integrations
- Approval-bound action tokens with expiration
- Native browser push notifications
- Durable retry queue with exponential backoff

## License

MIT.
