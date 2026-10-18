from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from . import accounts
from .config import get_settings
from .db import get_db
from .llm.base import LLMClient, LLMError, LLMResponse
from .llm.gemini import GeminiClient


class _Unavailable:
    """Stands in when the LLM can't be built (e.g. missing API key) so chat degrades instead of 500-ing."""

    def __init__(self, reason: str):
        self.reason = reason

    def generate(self, *args, **kwargs) -> LLMResponse:
        raise LLMError(self.reason)


@lru_cache
def _build() -> LLMClient:
    s = get_settings()
    try:
        return GeminiClient(s.gemini_api_key, s.gemini_model)
    except LLMError as e:
        return _Unavailable(str(e))


@lru_cache(maxsize=64)
def _build_own(key: str) -> LLMClient:
    try:
        return GeminiClient(key, get_settings().gemini_model)
    except LLMError as e:
        return _Unavailable(str(e))


def get_llm(db: Session = Depends(get_db)) -> LLMClient:
    """FastAPI dependency. Uses the user's own Gemini key when they saved one, else the server's. Tests override this."""
    key = accounts.own_key(db)
    return _build_own(key) if key else _build()
