"""Vercel entry point: Vercel looks for an ASGI app called `app` in this file."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402,F401
