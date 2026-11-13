"""OpenAI models via the Responses API, behind the same seam as Claude.

How the loop's needs map onto this API:
- "Must call a tool" is `tool_choice="required"`.
- Tools become strict function tools. Strict mode needs `additionalProperties: false` on every
  object and every property listed as required; the neutral schemas already require every
  property, so only the first is added here.
- The conversation is stateless (`store=False`): every turn resends the full input. The model's
  own output items, reasoning items included, go back verbatim and in order, as the Responses
  API requires for reasoning models that call functions.
- Prompt caching is automatic; `prompt_cache_key` groups every investigation onto the same
  cached prefix (system prompt + tool list).
- Reasoning models spend output tokens thinking before they answer, so a turn's output budget
  gets headroom for that on top of the loop's `max_tokens`.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

import openai

from volatility_explainer.llm.base import (
    AssistantTurn,
    HistoryItem,
    OnToolInput,
    ToolCall,
    ToolResults,
    Usage,
    UserMessage,
)

_logger = logging.getLogger(__name__)

_PROMPT_CACHE_KEY = "volx-agent-v1"
_REASONING_HEADROOM_TOKENS = 4000

# SDK defaults allow a request up to 10 minutes. A streamed turn here takes 2-15s; the
# timeout bounds each network wait (connect, or the gap between streamed chunks), so a
# turn that stalls fails the run instead of holding the stream open. The plain completion
# is the scope gate's ticker fallback, which a user waits on before anything is shown.
_TURN_TIMEOUT_SECONDS = 60.0
_COMPLETE_TIMEOUT_SECONDS = 10.0


def _strict_schema(schema: dict) -> dict:
    """A copy of `schema` with additionalProperties: false on every object."""
    schema = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("properties", {})
                node.setdefault("required", list(node["properties"]))
                node["additionalProperties"] = False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


def _tools_payload(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": _strict_schema(tool["input_schema"]),
            "strict": True,
        }
        for tool in tools
    ]


def _input_payload(history: list[HistoryItem]) -> list[dict]:
    items: list[dict] = []
    for item in history:
        if isinstance(item, UserMessage):
            items.append({"role": "user", "content": item.text})
        elif isinstance(item, AssistantTurn):
            if item.raw is not None:
                items.extend(item.raw)  # the model's own output items, reasoning included
            else:  # built by the loop (the prefetch splice): no reasoning to carry
                items.extend(
                    {"type": "function_call", "call_id": c.id, "name": c.name,
                     "arguments": json.dumps(c.input)}
                    for c in item.tool_calls
                )
        elif isinstance(item, ToolResults):
            items.extend(
                {"type": "function_call_output", "call_id": call_id, "output": content}
                for call_id, content in item.results
            )
    return items


def _usage(usage: Any) -> Usage:
    """OpenAI's input_tokens is the whole prompt, cached and cache-written tokens included;
    the neutral Usage counts only uncached input there."""
    if usage is None:
        return Usage()
    details = usage.input_tokens_details
    cached = (details.cached_tokens or 0) if details else 0
    written = (getattr(details, "cache_write_tokens", 0) or 0) if details else 0
    out_details = usage.output_tokens_details
    return Usage(
        input_tokens=max((usage.input_tokens or 0) - cached - written, 0),
        cache_read_tokens=cached,
        cache_write_tokens=written,
        output_tokens=usage.output_tokens or 0,
        reasoning_tokens=(out_details.reasoning_tokens or 0) if out_details else 0,
    )


def _tool_calls(output: list[Any]) -> list[ToolCall]:
    calls = []
    for item in output:
        if getattr(item, "type", None) != "function_call":
            continue
        try:
            arguments = json.loads(item.arguments or "{}")
        except ValueError:
            # Cut off mid-call (output budget exhausted). A half-written call can't be run or
            # trusted; dropping it lets the loop end the run as incomplete.
            _logger.warning(f"[llm]   dropped {item.name}: arguments were not valid JSON")
            continue
        calls.append(ToolCall(id=item.call_id, name=item.name, input=arguments))
    return calls


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key: str | None, model: str, reasoning_effort: str = "low"):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._api_key = api_key
        self._async_client: openai.AsyncOpenAI | None = None

    def _client(self) -> openai.AsyncOpenAI:
        """One client per provider, so a run's turns share its connection pool. A provider
        lives for one investigation (or one eval run), always inside a single event loop."""
        if self._async_client is None:
            self._async_client = openai.AsyncOpenAI(
                api_key=self._api_key, timeout=_TURN_TIMEOUT_SECONDS
            )
        return self._async_client

    def _reasoning_args(self, effort: str, max_tokens: int) -> dict:
        headroom = 0 if effort == "none" else _REASONING_HEADROOM_TOKENS
        return {"reasoning": {"effort": effort}, "max_output_tokens": max_tokens + headroom}

    async def run_turn(
        self,
        *,
        system: str,
        history: list[HistoryItem],
        tools: list[dict],
        max_tokens: int,
        stream_tool: str | None = None,
        on_tool_input: OnToolInput | None = None,
    ) -> AssistantTurn:
        client = self._client()
        names_by_index: dict[int, str] = {}
        arguments_by_index: dict[int, str] = {}
        response = None

        stream = await client.responses.create(
            model=self.model,
            instructions=system,
            input=_input_payload(history),
            tools=_tools_payload(tools),
            tool_choice="required",
            store=False,
            stream=True,
            prompt_cache_key=_PROMPT_CACHE_KEY,
            **self._reasoning_args(self.reasoning_effort, max_tokens),
        )
        async for event in stream:
            if event.type == "response.output_item.added":
                if getattr(event.item, "type", None) == "function_call":
                    names_by_index[event.output_index] = event.item.name
                    arguments_by_index[event.output_index] = ""
            elif event.type == "response.function_call_arguments.delta":
                name = names_by_index.get(event.output_index)
                arguments_by_index[event.output_index] = (
                    arguments_by_index.get(event.output_index, "") + event.delta
                )
                if on_tool_input is not None and name is not None and name == stream_tool:
                    on_tool_input(name, arguments_by_index[event.output_index])
            elif event.type in ("response.completed", "response.incomplete", "response.failed"):
                response = event.response

        if response is None:
            raise RuntimeError("OpenAI stream ended without a final response")
        if response.status == "failed":
            error = getattr(response, "error", None)
            raise RuntimeError(f"OpenAI response failed: {getattr(error, 'message', error)}")

        return AssistantTurn(
            tool_calls=_tool_calls(response.output),
            text=response.output_text or "",
            usage=_usage(response.usage),
            # Sent back verbatim next turn. by_alias keeps wire names (e.g. "async").
            raw=[item.model_dump(by_alias=True, exclude_none=True) for item in response.output],
        )

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        client = openai.OpenAI(
            api_key=self._api_key, timeout=_COMPLETE_TIMEOUT_SECONDS, max_retries=1
        )
        response = client.responses.create(
            model=self.model,
            input=prompt,
            store=False,
            **self._reasoning_args("none", max(max_tokens, 16)),
        )
        return response.output_text or ""
