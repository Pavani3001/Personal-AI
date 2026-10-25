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
def _is_serverless_or_readonly() -> bool:
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return True
    try:
        test_dir = ROOT_DIR / "workspace"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / ".perm_check"
        test_file.touch()
        test_file.unlink(missing_ok=True)
        return False
    except OSError:
        return True


def get_default_workspace() -> Path:
    if _is_serverless_or_readonly():
        import tempfile
        return Path(tempfile.gettempdir()) / "personal_ai_workspace"
    return ROOT_DIR / "workspace"


WORKSPACE_PATH = Path(os.getenv("PERSONAL_AI_WORKSPACE", str(get_default_workspace())))
MAX_AGENT_RETRIES = 2


def validate_configuration() -> None:
    if os.getenv("VERCEL") and not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured for Vercel deployment. "
            "Add a hosted PostgreSQL connection URL to your Vercel project environment variables."
        )
    if not NEBIUS_API_KEY:
        raise RuntimeError("NEBIUS_API_KEY is not configured. Add it to the server .env file.")
