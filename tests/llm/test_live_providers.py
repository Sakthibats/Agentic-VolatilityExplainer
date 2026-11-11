"""Live checks that each vendor still accepts the exact request its adapter sends.

The offline tests replay a fake wire format; these catch the real one drifting (a renamed
stream event, a schema keyword strict mode stops accepting). One short turn per vendor, a
fraction of a cent each. Skipped when that vendor's key isn't configured.

    pytest -m live tests/llm
"""

from __future__ import annotations

import pytest
from volatility_explainer.agent.tool_schemas import TOOL_DEFINITIONS
from volatility_explainer.config import get_settings
from volatility_explainer.llm import build_provider
from volatility_explainer.llm.base import UserMessage

pytestmark = pytest.mark.live

_CASES = [
    ("anthropic", "claude-haiku-5-5", "anthropic_api_key"),
    ("openai", "gpt-6-luna", "openai_api_key"),
]


def _provider(name: str, model: str, key_field: str):
    key = getattr(get_settings(), key_field).get_secret_value()
    if not key:
        pytest.skip(f"{key_field.upper()} not set")
    return build_provider(name, model, key)


@pytest.mark.parametrize(("name", "model", "key_field"), _CASES)
async def test_a_forced_tool_turn_returns_a_parsed_tool_call(name, model, key_field):
    provider = _provider(name, model, key_field)
    streamed: list[str] = []

    turn = await provider.run_turn(
        system="You are a financial investigator. Fetch data with a tool before answering.",
        history=[UserMessage("Get the latest news headlines for AAPL.")],
        tools=TOOL_DEFINITIONS,  # the full production tool list, strict schemas and all
        max_tokens=500,
        stream_tool="get_news",
        on_tool_input=lambda _name, text: streamed.append(text),
    )

    assert turn.tool_calls, "a forced tool turn must call a tool"
    call = turn.tool_calls[0]
    assert call.name in {t["name"] for t in TOOL_DEFINITIONS}
    assert isinstance(call.input, dict)
    if call.name == "get_news":
        assert call.input.get("ticker") == "AAPL"
        assert streamed, "the streamed tool's input should arrive incrementally"
    assert turn.usage.output_tokens > 0


@pytest.mark.parametrize(("name", "model", "key_field"), _CASES)
async def test_an_off_topic_request_ends_with_the_inputless_scope_tool(name, model, key_field):
    # flag_out_of_scope has an empty schema (the server supplies the message); both vendors
    # must accept it, and OpenAI strict mode must return exactly {}.
    turn = await _provider(name, model, key_field).run_turn(
        system="You decline anything that is not about stock prices.",
        history=[UserMessage("Write me a poem about the sea.")],
        tools=TOOL_DEFINITIONS,
        max_tokens=200,
    )

    assert [c.name for c in turn.tool_calls] == ["flag_out_of_scope"]
    if name == "openai":
        assert turn.tool_calls[0].input == {}


@pytest.mark.parametrize(("name", "model", "key_field"), _CASES)
def test_a_plain_completion_returns_text(name, model, key_field):
    text = _provider(name, model, key_field).complete(
        'Reply with exactly this JSON and nothing else: {"ok": true}', max_tokens=30
    )

    assert '"ok"' in text
