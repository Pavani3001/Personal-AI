import sys
from pathlib import Path

# Ensure project root is in sys.path so app module is always importable on Vercel
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app

# Vercel Serverless Function entrypoint
__all__ = ["app"]
