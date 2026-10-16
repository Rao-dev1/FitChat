"""Provider-neutral LLM types. Swap providers by writing one new adapter implementing LLMClient."""
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """Any provider failure."""


class LLMRateLimited(LLMError):
    """Provider quota / rate limit hit (HTTP 429)."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema (type=object)


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class ToolResult:
    name: str
    result: dict


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant turns
    tool_results: list[ToolResult] = field(default_factory=list)  # tool turns
    raw: Any = None  # provider-native object; lets adapters preserve things like thought signatures


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    raw: Any = None


class LLMClient(Protocol):
    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...
