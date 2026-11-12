"""Claude via the Messages API: the loop's original vendor, moved behind the provider seam.

Anthropic-specific choices kept here, not in the neutral tool schemas:
- Prompt caching uses explicit breakpoints: one on the system prompt and one on the LAST tool
  definition, which caches the whole tool list. agent/tool_schemas.py keeps submit_analysis
  last for exactly this reason.
- The streamed tool gets `eager_input_streaming`, so its input arrives in fine-grained chunks
  and the explanation can be shown as it is written. Not a beta feature.
- `tool_choice: any` forces a tool call every turn; a prose reply would end the run as
  incomplete.
"""

from __future__ import annotations

import anthropic

from volatility_explainer.llm.base import (
    AssistantTurn,
    HistoryItem,
    OnToolInput,
    ToolCall,
    ToolResults,
    Usage,
    UserMessage,
)

_CACHE = {"type": "ephemeral"}

# SDK defaults allow a request up to 10 minutes. A streamed turn here takes 2-15s; the
# timeout bounds each network wait (connect, or the gap between streamed chunks), so a
# turn that stalls fails the run instead of holding the stream open. The plain completion
# is the scope gate's ticker fallback, which a user waits on before anything is shown.
_TURN_TIMEOUT_SECONDS = 60.0
_COMPLETE_TIMEOUT_SECONDS = 10.0


def _tools_payload(tools: list[dict], stream_tool: str | None) -> list[dict]:
    payload = []
    for i, tool in enumerate(tools):
        entry = {k: tool[k] for k in ("name", "description", "input_schema")}
        if i == len(tools) - 1:
            entry["cache_control"] = _CACHE
        if tool["name"] == stream_tool:
            entry["eager_input_streaming"] = True
        payload.append(entry)
    return payload


def _messages_payload(history: list[HistoryItem]) -> list[dict]:
    messages: list[dict] = []
    for item in history:
        if isinstance(item, UserMessage):
            messages.append({"role": "user", "content": item.text})
        elif isinstance(item, AssistantTurn):
            # The SDK's own content blocks when the model produced this turn; rebuilt from the
            # tool calls when the loop did (the prefetch splice).
            content = item.raw if item.raw is not None else [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
                for c in item.tool_calls
            ]
            messages.append({"role": "assistant", "content": content})
        elif isinstance(item, ToolResults):
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": content}
                for call_id, content in item.results
            ]})
    return messages


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str | None, model: str):
        self.model = model
        self._api_key = api_key
        self._async_client: anthropic.AsyncAnthropic | None = None

    def _client(self) -> anthropic.AsyncAnthropic:
        """One client per provider, so a run's turns share its connection pool. A provider
        lives for one investigation (or one eval run), always inside a single event loop."""
        if self._async_client is None:
            self._async_client = anthropic.AsyncAnthropic(
                api_key=self._api_key, timeout=_TURN_TIMEOUT_SECONDS
            )
        return self._async_client

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
        streaming_tool: str | None = None
        input_json = ""

        async with client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": _CACHE}],
            tools=_tools_payload(tools, stream_tool),
            tool_choice={"type": "any"},
            messages=_messages_payload(history),
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    streaming_tool = block.name if block.type == "tool_use" else None
                    input_json = ""
                elif (
                    on_tool_input is not None
                    and streaming_tool is not None
                    and streaming_tool == stream_tool
                    and event.type == "content_block_delta"
                    and event.delta.type == "input_json_delta"
                ):
                    input_json += event.delta.partial_json
                    on_tool_input(streaming_tool, input_json)

            response = await stream.get_final_message()

        usage = response.usage
        return AssistantTurn(
            tool_calls=[
                ToolCall(id=b.id, name=b.name, input=b.input)
                for b in response.content if b.type == "tool_use"
            ],
            text="".join(b.text for b in response.content if b.type == "text"),
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
                cache_write_tokens=usage.cache_creation_input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
            ),
            raw=response.content,
        )

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        client = anthropic.Anthropic(
            api_key=self._api_key, timeout=_COMPLETE_TIMEOUT_SECONDS, max_retries=1
        )
        msg = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            # Haiku 5.5 thinks by default, and thinking counts toward max_tokens: a 30-token
            # reply budget was spent entirely on thinking, leaving no answer. Off explicitly
            # (accepted on Haiku 4.5 and 5.5; run_turn needs nothing, since a forced
            # tool_choice already skips thinking).
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")
