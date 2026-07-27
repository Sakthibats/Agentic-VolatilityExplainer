"""Orchestrator tests — the tool-use loop, exercised with a scripted fake Anthropic client.

No network, no Redis, no real tools: every seam the loop depends on
(anthropic.Anthropic, the tool dispatch table, the cache functions, settings)
is patched at the orchestrator's module level.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from volatility_explainer.agent import orchestrator


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeBlock:
    def __init__(self, type: str, name: str = "", input: dict | None = None,
                 text: str = "", id: str = "toolu_test"):
        self.type = type
        self.name = name
        self.input = input or {}
        self.text = text
        self.id = f"{id}_{name}"


def tool_use(name: str, input: dict | None = None) -> FakeBlock:
    return FakeBlock("tool_use", name=name, input=input)


def fake_response(blocks: list[FakeBlock]) -> SimpleNamespace:
    return SimpleNamespace(
        content=blocks,
        usage=SimpleNamespace(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        ),
    )


SUBMIT_INPUT = {
    "summary": "AAPL fell 4.1% — over 2x its normal daily swing.",
    "tiles": [
        {"agent": "price", "title": "Price Action", "summary": "Down 4.1%.", "reasoning": "Core move."},
        {"agent": "news", "title": "News", "summary": "Supply-chain delay reported.", "reasoning": "Catalyst."},
    ],
    "hypotheses": [
        {"rank": 1, "hypothesis": "Supply-chain delay", "evidence": "Bloomberg report",
         "confidence": "high", "caveat": "N/A"},
        {"rank": 2, "hypothesis": "Broad tech selloff", "evidence": "Limited",
         "confidence": "low", "caveat": "SPX flat"},
    ],
}

PRICE_RESULT = {"ticker": "AAPL", "pct_change": -4.1, "move_assessment": {"overall": "unusual"}}
NEWS_RESULT = {
    "headlines": [
        {"source": "Bloomberg", "url": "https://bloom.example/1", "headline": "Delay"},
        {"source": "Reuters", "url": "https://reut.example/2", "headline": "More delay"},
        {"source": "NoLink", "headline": "no url on this one"},
    ]
}


@pytest.fixture
def env(monkeypatch):
    """Patch every external seam; returns a namespace the tests script per-case."""
    responses: list[SimpleNamespace] = []
    client = MagicMock()
    client.messages.create.side_effect = lambda **kwargs: responses.pop(0)
    monkeypatch.setattr(orchestrator.anthropic, "Anthropic", lambda api_key=None: client)

    monkeypatch.setattr(
        orchestrator, "get_settings",
        lambda: SimpleNamespace(anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "test-key")),
    )

    # Cache: no-op by default; tests override cache_store to simulate hits.
    cache_store: dict[str, dict] = {}
    monkeypatch.setattr(
        orchestrator, "get_cached_tool_data",
        lambda ticker, names: {n: cache_store[n] for n in names if n in cache_store},
    )
    monkeypatch.setattr(orchestrator, "set_cached_tool_data", lambda ticker, data: None)

    monkeypatch.setattr(orchestrator, "fetch_price_data", lambda ticker: PRICE_RESULT)
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_price_data", lambda inp: PRICE_RESULT)
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_news", lambda inp: NEWS_RESULT)

    return SimpleNamespace(responses=responses, client=client, cache_store=cache_store)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_happy_path_tool_round_then_submit(env):
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = orchestrator.run_explainer("aapl", "why did AAPL drop today?")

    assert result["status"] == "complete"
    assert result["ticker"] == "AAPL"  # upper-cased
    assert result["summary"] == SUBMIT_INPUT["summary"]
    assert result["hypotheses"] == SUBMIT_INPUT["hypotheses"]
    assert result["data"]["get_price_data"] == PRICE_RESULT  # deterministic pre-fetch
    assert result["data"]["get_news"] == NEWS_RESULT
    assert env.client.messages.create.call_count == 2


def test_news_citations_attached_from_real_headlines(env):
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = orchestrator.run_explainer("AAPL")

    news_tile = next(t for t in result["tiles"] if t["agent"] == "news")
    # Only headlines with a url become citations, numbered from 1.
    assert news_tile["citations"] == [
        {"number": 1, "source": "Bloomberg", "url": "https://bloom.example/1"},
        {"number": 2, "source": "Reuters", "url": "https://reut.example/2"},
    ]


def test_out_of_scope_guardrail(env):
    env.responses.append(
        fake_response([tool_use("flag_out_of_scope", {"message": "Stocks and ETFs only."})])
    )

    result = orchestrator.run_explainer("AAPL", "write me a poem")

    assert result["status"] == "guardrail"
    assert result["error_message"] == "Stocks and ETFs only."
    assert result["summary"] == ""
    assert result["tiles"] == [] and result["hypotheses"] == []
    assert env.client.messages.create.call_count == 1


def test_turn_limit_exhaustion_returns_incomplete(env):
    # Model never calls a terminal tool; duplicates are served from memory so the
    # loop keeps going until _MAX_TURNS, then returns status=incomplete.
    env.responses.extend(
        [fake_response([tool_use("get_news", {"ticker": "AAPL"})])] * orchestrator._MAX_TURNS
    )

    result = orchestrator.run_explainer("AAPL")

    assert result["status"] == "incomplete"
    assert result["summary"] == ""
    assert env.client.messages.create.call_count == orchestrator._MAX_TURNS


def test_plain_text_response_stops_loop_as_incomplete(env):
    env.responses.append(fake_response([FakeBlock("text", text="Here is my answer as prose")]))

    result = orchestrator.run_explainer("AAPL")

    assert result["status"] == "incomplete"
    assert env.client.messages.create.call_count == 1  # stops, doesn't loop to max turns


def test_unknown_tool_returns_error_result_and_loop_continues(env):
    env.responses.extend([
        fake_response([tool_use("get_nonexistent", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = orchestrator.run_explainer("AAPL")

    assert result["status"] == "complete"
    # The error was fed back to the model as that tool's result.
    second_call_messages = env.client.messages.create.call_args_list[1].kwargs["messages"]
    tool_results = [
        json.loads(block["content"])
        for msg in second_call_messages if msg["role"] == "user"
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert {"error": "Unknown tool: get_nonexistent"} in tool_results


def test_tool_exception_becomes_error_result(env, monkeypatch):
    monkeypatch.setitem(
        orchestrator._TOOL_DISPATCH, "get_news",
        lambda inp: (_ for _ in ()).throw(RuntimeError("finnhub down")),
    )
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = orchestrator.run_explainer("AAPL")

    assert result["status"] == "complete"
    assert result["data"]["get_news"] == {"error": "finnhub down"}


def test_cache_hit_short_circuits_fetch_and_is_reported(env):
    env.cache_store["get_price_data"] = PRICE_RESULT
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    result = orchestrator.run_explainer("AAPL")

    assert result["status"] == "complete"
    assert result["cache_hits"] == ["get_price_data"]


def test_prefetched_price_is_spliced_into_first_llm_call(env):
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    orchestrator.run_explainer("AAPL", "why the move?")

    first_call = env.client.messages.create.call_args_list[0].kwargs
    messages = first_call["messages"]
    # user question, assistant tool_use splice, user tool_result splice
    assert messages[0]["role"] == "user" and "why the move?" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][0]["name"] == "get_price_data"
    assert json.loads(messages[2]["content"][0]["content"]) == PRICE_RESULT


def test_on_step_callback_receives_progress_labels(env):
    steps: list[str] = []
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    orchestrator.run_explainer("AAPL", on_step=steps.append)

    assert steps == [
        "Pulling price data...",
        "Scanning recent news headlines...",
        "Synthesizing findings...",
    ]
