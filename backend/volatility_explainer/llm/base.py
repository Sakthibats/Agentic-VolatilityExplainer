"""The seam between the agent loop and an LLM vendor.

The orchestrator owns the investigation: prefetch, tool dispatch, timeouts, citations,
quality checks and the rule that a run ends only through a terminal tool. A provider owns one
thing: turning a vendor-neutral conversation into one model turn, streamed. Everything
vendor-specific (message shapes, tool-call formats, cache markers, streaming event names,
how usage is reported) stays inside the adapter.

Tool definitions are passed in the neutral shape `{"name", "description", "input_schema"}`
(see agent/tool_schemas.py); each adapter translates them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Usage:
    """Token counts for one turn, normalised across vendors.

    input_tokens counts only uncached input. Anthropic reports it that way; OpenAI reports
    a total that includes cached tokens, which its adapter subtracts. reasoning_tokens is a
    breakdown already included in output_tokens, never added on top of it.
    """

    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class UserMessage:
    text: str


@dataclass
class AssistantTurn:
    """What the model produced in one turn.

    `raw` holds the vendor's own output for this turn, opaque to the loop. The adapter that
    produced it sends it back verbatim on later turns: OpenAI reasoning items, for example,
    must be returned as they were received. A turn built by the loop itself (the prefetch
    splice) has no raw output, so adapters rebuild it from `tool_calls`.
    """

    tool_calls: list[ToolCall]
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


@dataclass
class ToolResults:
    """The results of every tool call in the previous assistant turn: (call id, JSON text)."""

    results: list[tuple[str, str]]


HistoryItem = UserMessage | AssistantTurn | ToolResults

# Called with (tool name, the tool's input JSON received so far) as it streams in.
OnToolInput = Callable[[str, str], None]


class LLMProvider(Protocol):
    name: str   # "anthropic" | "openai"
    model: str

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
        """Run one turn in which the model MUST call at least one tool.

        Input for `stream_tool` is streamed to `on_tool_input` as it is generated (the
        cumulative JSON text so far, not a delta); every other tool's input arrives whole.
        """
        ...

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        """A plain, non-streamed, synchronous text completion with no tools."""
        ...
