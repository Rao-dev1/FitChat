from google import genai
from google.genai import errors, types

from .base import LLMError, LLMRateLimited, LLMResponse, Message, ToolCall, ToolSpec


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set (create one in Google AI Studio and put it in .env).")
        self._client = genai.Client(api_key=api_key)
        self._model = model

    @staticmethod
    def _to_contents(messages: list[Message]) -> list[types.Content]:
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=m.text)]))
            elif m.role == "assistant":
                if m.raw is not None:  # reuse the exact model turn (keeps thought signatures intact)
                    contents.append(m.raw)
                else:
                    contents.append(types.Content(role="model", parts=[types.Part.from_text(text=m.text)]))
            elif m.role == "tool":
                parts = [
                    types.Part.from_function_response(name=r.name, response={"result": r.result})
                    for r in m.tool_results
                ]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        decls = [
            types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.4,
        )
        try:
            resp = self._client.models.generate_content(
                model=self._model, contents=self._to_contents(messages), config=config
            )
        except errors.APIError as e:
            if getattr(e, "code", None) == 429:
                raise LLMRateLimited(str(e)) from e
            raise LLMError(str(e)) from e

        if not resp.candidates or not resp.candidates[0].content:
            raise LLMError("Model returned no content (possibly blocked by a safety filter).")
        content = resp.candidates[0].content
        text_parts, calls = [], []
        for p in content.parts or []:
            if p.function_call:
                calls.append(ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {})))
            elif p.text and not p.thought:
                text_parts.append(p.text)
        return LLMResponse(text="".join(text_parts).strip(), tool_calls=calls, raw=content)
