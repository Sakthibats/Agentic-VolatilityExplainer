"""The OpenAI adapter, driven through the real agent loop by a scripted fake Responses API.

The same behaviours the Claude tests pin (structured endings, streaming the explanation,
prose ending as incomplete, the prefetch splice) are checked here on the OpenAI wire format,
plus what is specific to it: strict function schemas, reasoning items sent back verbatim,
and usage normalised so cached tokens aren't counted twice.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from volatility_explainer.agent import orchestrator
from volatility_explainer.agent.prompts import SYSTEM_PROMPT
from volatility_explainer.clients.redis_cache import clear_memoized_tool_data
from volatility_explainer.llm import openai_provider
from volatility_explainer.llm.openai_provider import OpenAIProvider

SUBMIT_INPUT = {
    "tiles": [{"agent": "price", "title": "Price", "summary": "Down 4%.", "reasoning": "Move."}],
    "hypotheses": [
        {"rank": 1, "hypothesis": "Delay", "evidence": "Report", "confidence": "high", "caveat": "N/A"},
        {"rank": 2, "hypothesis": "Sector", "evidence": "Limited", "confidence": "low", "caveat": "N/A"},
    ],
    "explanation": "A reported supply-chain delay is the most likely cause of the drop.",
}
PRICE = {"ticker": "AAPL", "price": 100.0, "pct_change": -4.1, "move_assessment": {"overall": "unusual"}}
EVENTS = {"ticker": "AAPL", "events": [], "recent_events": []}
NEWS = {"headlines": [{"source": "Reuters", "url": "https://r.example/1", "headline": "Delay"}]}


class Item:
    """A Responses API output item: attribute access plus model_dump, like the SDK's models."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def model_dump(self, **_):
        return dict(self.__dict__)


def call(name: str, arguments: dict | str, call_id: str | None = None) -> Item:
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return Item(type="function_call", name=name, arguments=args, call_id=call_id or f"call_{name}")


def reasoning(item_id: str = "rs_1") -> Item:
    return Item(type="reasoning", id=item_id, encrypted_content="opaque", summary=[])


def message(text: str) -> Item:
    return Item(type="message", role="assistant", content=[{"type": "output_text", "text": text}])


def response(output: list[Item], *, status="completed", input_tokens=1000, cached=600,
             written=0, output_tokens=200, reasoning_tokens=50) -> SimpleNamespace:
    text = "".join(c["text"] for i in output if i.type == "message" for c in i.content)
    return SimpleNamespace(
        status=status, output=output, output_text=text, error=None,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            input_tokens_details=SimpleNamespace(cached_tokens=cached, cache_write_tokens=written),
            output_tokens=output_tokens,
            output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
        ),
    )


def events_for(resp: SimpleNamespace, chunk: int = 10):
    """The stream events the adapter reads: item added, argument deltas, then the final event."""
    async def gen():
        for index, item in enumerate(resp.output):
            yield SimpleNamespace(type="response.output_item.added", output_index=index, item=item)
            if item.type == "function_call":
                for i in range(0, len(item.arguments), chunk):
                    yield SimpleNamespace(type="response.function_call_arguments.delta",
                                          output_index=index, delta=item.arguments[i : i + chunk])
        final = "response.completed" if resp.status == "completed" else f"response.{resp.status}"
        yield SimpleNamespace(type=final, response=resp)
    return gen()


@pytest.fixture
def env(monkeypatch):
    clear_memoized_tool_data()
    scripted: list[SimpleNamespace] = []
    requests: list[dict] = []

    async def create(**kwargs):
        # Snapshot the input: the adapter builds a fresh list per turn, but be safe.
        requests.append({**kwargs, "input": json.loads(json.dumps(kwargs["input"], default=str))})
        return events_for(scripted.pop(0))

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(openai_provider.openai, "AsyncOpenAI", lambda api_key=None: client)

    monkeypatch.setattr(orchestrator, "get_cached_tool_data", lambda ticker, names: {})
    monkeypatch.setattr(orchestrator, "set_cached_tool_data", lambda ticker, data: None)
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_price_data", lambda inp: PRICE)
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_events", lambda inp: dict(EVENTS))
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_news", lambda inp: NEWS)

    provider = OpenAIProvider(api_key="test", model="gpt-6-luna", reasoning_effort="low")
    return SimpleNamespace(scripted=scripted, requests=requests, provider=provider)


async def run(env, **kwargs):
    return await orchestrator.run_explainer("AAPL", "why did it drop?", provider=env.provider, **kwargs)


async def test_tool_round_then_submit_completes(env):
    env.scripted.extend([
        response([reasoning(), call("get_news", {"ticker": "AAPL"})]),
        response([call("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await run(env)

    assert result["status"] == "complete"
    assert result["summary"] == SUBMIT_INPUT["explanation"]
    assert result["usage"]["tool_rounds"] == [["get_news"]]
    assert result["usage"]["provider"] == "openai"
    assert result["usage"]["model"] == "gpt-6-luna"


async def test_request_forces_a_tool_call_with_strict_schemas_and_no_stored_state(env):
    env.scripted.append(response([call("submit_analysis", SUBMIT_INPUT)]))

    await run(env)

    request = env.requests[0]
    assert request["tool_choice"] == "required"
    assert request["store"] is False
    assert request["instructions"] == SYSTEM_PROMPT
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] > orchestrator._MAX_OUTPUT_TOKENS  # room to think

    def objects(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                yield schema
            for value in schema.values():
                yield from objects(value)
        elif isinstance(schema, list):
            for value in schema:
                yield from objects(value)

    for tool in request["tools"]:
        assert tool["type"] == "function" and tool["strict"] is True
        for obj in objects(tool["parameters"]):
            assert obj["additionalProperties"] is False
            assert set(obj["required"]) == set(obj["properties"])


async def test_prefetched_data_is_spliced_in_as_function_calls_and_outputs(env):
    env.scripted.append(response([call("submit_analysis", SUBMIT_INPUT)]))

    await run(env)

    items = env.requests[0]["input"]
    assert items[0]["role"] == "user" and "why did it drop?" in items[0]["content"]
    calls = [i for i in items if i.get("type") == "function_call"]
    outputs = {i["call_id"]: json.loads(i["output"]) for i in items if i.get("type") == "function_call_output"}
    assert [c["name"] for c in calls] == list(orchestrator._PREFETCH_TOOLS)
    assert outputs[calls[0]["call_id"]] == PRICE


async def test_reasoning_items_are_sent_back_verbatim_and_in_order(env):
    env.scripted.extend([
        response([reasoning("rs_turn1"), call("get_news", {"ticker": "AAPL"}, "call_n")]),
        response([call("submit_analysis", SUBMIT_INPUT)]),
    ])

    await run(env)

    second = env.requests[1]["input"]
    kinds = [(i.get("type"), i.get("id") or i.get("call_id")) for i in second]
    rs = kinds.index(("reasoning", "rs_turn1"))
    assert kinds[rs + 1] == ("function_call", "call_n")
    assert kinds[rs + 2] == ("function_call_output", "call_n")
    assert second[rs]["encrypted_content"] == "opaque"


async def test_explanation_streams_progressively(env):
    env.scripted.append(response([call("submit_analysis", SUBMIT_INPUT)]))
    seen: list[str] = []

    await run(env, on_summary=seen.append)

    assert len(seen) > 1
    assert seen[-1] == SUBMIT_INPUT["explanation"]
    assert all(SUBMIT_INPUT["explanation"].startswith(s) for s in seen)


async def test_a_prose_reply_ends_the_run_as_incomplete(env):
    env.scripted.append(response([message("Here is my analysis in prose.")]))

    result = await run(env)

    assert result["status"] == "incomplete"
    assert result["summary"] == ""


async def test_a_call_cut_off_mid_arguments_is_dropped_not_run(env):
    env.scripted.append(response([call("submit_analysis", '{"tiles": [{"agent": "pri')],
                                 status="incomplete"))

    result = await run(env)

    assert result["status"] == "incomplete"


async def test_usage_counts_cached_and_written_tokens_once(env):
    env.scripted.append(response([call("submit_analysis", SUBMIT_INPUT)],
                                 input_tokens=1000, cached=600, written=300,
                                 output_tokens=200, reasoning_tokens=50))

    usage = (await run(env))["usage"]

    assert (usage["input_tokens"], usage["cache_read_tokens"], usage["cache_write_tokens"]) == (100, 600, 300)
    assert (usage["output_tokens"], usage["reasoning_tokens"]) == (200, 50)
    expected = (100 * 0.10 + 600 * 0.01 + 300 * 0.125 + 200 * 0.50) / 1_000_000
    assert usage["cost_usd"] == pytest.approx(expected)


async def test_a_failed_response_raises(env):
    failed = response([], status="failed")
    failed.error = SimpleNamespace(message="server error")
    env.scripted.append(failed)

    with pytest.raises(RuntimeError, match="server error"):
        await run(env)


def test_complete_does_not_spend_its_budget_reasoning(monkeypatch):
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(output_text='{"ticker": "AAPL"}')

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(openai_provider.openai, "OpenAI", lambda api_key=None: client)

    text = OpenAIProvider(api_key="k", model="gpt-6-luna").complete("which ticker?", max_tokens=30)

    assert text == '{"ticker": "AAPL"}'
    assert seen["reasoning"] == {"effort": "none"}
    assert seen["max_output_tokens"] == 30
