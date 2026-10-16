from functools import lru_cache

from .config import get_settings
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


def get_llm() -> LLMClient:
    """FastAPI dependency. Tests override this with a ScriptedLLM."""
    return _build()
