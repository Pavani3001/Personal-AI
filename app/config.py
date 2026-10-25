from pathlib import Path
import os

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_MODEL = os.getenv("NEBIUS_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_PATH = Path(os.getenv("PERSONAL_AI_DATABASE", str(ROOT_DIR / "data" / "personal_ai.db")))
WORKSPACE_PATH = Path(os.getenv("PERSONAL_AI_WORKSPACE", str(ROOT_DIR / "workspace")))
MAX_AGENT_RETRIES = 2


def validate_configuration() -> None:
    if os.getenv("VERCEL") and not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured for Vercel deployment. "
            "Add a hosted PostgreSQL connection URL to your Vercel project environment variables."
        )
    if not NEBIUS_API_KEY:
        raise RuntimeError("NEBIUS_API_KEY is not configured. Add it to the server .env file.")
