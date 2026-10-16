"""Scripted LLM for tests and offline development: no network, fully deterministic."""
from .base import LLMResponse, Message, ToolCall, ToolSpec


class ScriptedLLM:
    def __init__(self, script: list[LLMResponse]):
        self.script = list(script)
        self.calls: list[list[Message]] = []

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        self.calls.append(list(messages))
        return self.script.pop(0)


def say(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[])


def call(tool: str, /, **args) -> LLMResponse:
    return LLMResponse(text="", tool_calls=[ToolCall(name=tool, args=args)])
