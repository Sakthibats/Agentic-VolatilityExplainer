"""Orchestrator tests — the tool-use loop, exercised with a scripted fake Anthropic client.

No network, no Redis, no real tools: every seam the loop depends on
(anthropic.Anthropic, the tool dispatch table, the cache functions, settings)
is patched at the orchestrator's module level.
"""

from __future__ import annotations

import itertools
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from volatility_explainer.agent import orchestrator, tool_schemas
from volatility_explainer.clients.redis_cache import clear_memoized_tool_data

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


class FakeStream:
    """Stands in for anthropic's async streaming context manager.

    Replays a scripted response as the SSE events the orchestrator actually reads: a
    content_block_start per block, then — for tool_use blocks — the block's input
    serialized and handed back in small input_json_delta chunks, so the partial-JSON
    extraction runs for real rather than being stubbed out.
    """

    CHUNK = 12  # small enough that `summary` arrives across several deltas

    def __init__(self, response: SimpleNamespace):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def events():
            for block in self._response.content:
                yield SimpleNamespace(
                    type="content_block_start",
                    content_block=SimpleNamespace(type=block.type, name=block.name),
                )
                if block.type != "tool_use":
                    continue
                payload = json.dumps(block.input)
                for i in range(0, len(payload), self.CHUNK):
                    yield SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="input_json_delta", partial_json=payload[i : i + self.CHUNK]
                        ),
                    )

        return events()

    async def get_final_message(self) -> SimpleNamespace:
        return self._response


# Key order mirrors the schema the model follows: the tiles' own nested `summary` keys stream
# first, so the partial-JSON reader is exercised against them before `explanation` arrives.
SUBMIT_INPUT = {
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
    "explanation": "A reported supply-chain delay is the most likely cause, and the evidence is strong.",
}

PRICE_RESULT = {
    "ticker": "AAPL", "price": 100.0, "pct_change": -4.1,
    "move_assessment": {"overall": "unusual"},
}
EVENTS_RESULT = {
    "ticker": "AAPL",
    "earnings_status": "reported",
    "events": [],
    "recent_events": [{"type": "earnings", "days_ago": 2, "description": "AAPL reported Q3"}],
}
ANALYST_RESULT = {
    "ticker": "AAPL",
    "analyst_coverage": "covered",
    # current_price/upside deliberately anchored to a DIFFERENT price than PRICE_RESULT's,
    # the way yfinance's `current` drifts from Finnhub's quote intraday.
    "price_target": {"mean": 120.0, "median": 130.0, "current_price": 80.0,
                     "upside_vs_mean_pct": 50.0, "upside_vs_median_pct": 62.5},
}
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
    # The in-process memo in front of Redis is module-level state. Left alone it carries
    # results between tests and masks the fetches a test means to observe — the same way
    # it would carry them between requests in a live process.
    clear_memoized_tool_data()

    responses: list[SimpleNamespace] = []
    client = MagicMock()

    # messages.stream() is NOT awaited — it returns an async context manager directly.
    client.messages.stream = MagicMock(side_effect=lambda **kwargs: FakeStream(responses.pop(0)))
    monkeypatch.setattr(orchestrator.anthropic, "AsyncAnthropic", lambda api_key=None: client)

    monkeypatch.setattr(
        orchestrator, "get_settings",
        lambda: SimpleNamespace(
            anthropic_api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
            anthropic_model="claude-test-model",
        ),
    )

    # Cache: no-op by default; tests override cache_store to simulate hits.
    cache_store: dict[str, dict] = {}
    monkeypatch.setattr(
        orchestrator, "get_cached_tool_data",
        lambda ticker, names: {n: cache_store[n] for n in names if n in cache_store},
    )
    monkeypatch.setattr(orchestrator, "set_cached_tool_data", lambda ticker, data: None)

    monkeypatch.setattr(orchestrator, "fetch_price_data", lambda ticker: PRICE_RESULT)
    # Every pre-fetched tool must be stubbed here, or the suite silently starts hitting
    # the network on each run.
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_price_data", lambda inp: PRICE_RESULT)
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_events", lambda inp: dict(EVENTS_RESULT))
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_news", lambda inp: NEWS_RESULT)
    monkeypatch.setitem(
        orchestrator._TOOL_DISPATCH, "get_analyst_sentiment",
        lambda inp: {**ANALYST_RESULT, "price_target": dict(ANALYST_RESULT["price_target"])},
    )

    return SimpleNamespace(responses=responses, client=client, cache_store=cache_store)


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_happy_path_tool_round_then_submit(env):
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer("aapl", "why did AAPL drop today?")

    assert result["status"] == "complete"
    assert result["ticker"] == "AAPL"  # upper-cased
    assert result["summary"] == SUBMIT_INPUT["explanation"]
    assert result["hypotheses"] == SUBMIT_INPUT["hypotheses"]
    assert result["data"]["get_price_data"] == PRICE_RESULT  # deterministic pre-fetch
    assert [h["headline"] for h in result["data"]["get_news"]["headlines"]] == [
        h["headline"] for h in NEWS_RESULT["headlines"]
    ]
    assert env.client.messages.stream.call_count == 2


async def test_news_citations_attached_from_real_headlines(env):
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer("AAPL")

    news_tile = next(t for t in result["tiles"] if t["agent"] == "news")
    # Only headlines with a url become citations, numbered from 1.
    assert news_tile["citations"] == [
        {"number": 1, "source": "Bloomberg", "url": "https://bloom.example/1"},
        {"number": 2, "source": "Reuters", "url": "https://reut.example/2"},
    ]


async def test_model_is_shown_numbered_headlines_it_can_cite(env):
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    await orchestrator.run_explainer("AAPL")

    messages = env.client.messages.stream.call_args_list[1].kwargs["messages"]
    news = next(
        json.loads(block["content"])
        for message in messages
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("tool_use_id", "").endswith("get_news")
    )
    # Only linked headlines get a number, and the stubbed (or memoized) original is untouched.
    assert [h.get("ref") for h in news["headlines"]] == [1, 2, None]
    assert all("ref" not in h for h in NEWS_RESULT["headlines"])


async def test_explanation_citations_resolve_to_real_headlines_and_bad_ones_are_dropped(env):
    submit = {**SUBMIT_INPUT, "explanation": "A delay was reported [2], and a rival said so too [7]."}
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", submit)]),
    ])

    result = await orchestrator.run_explainer("AAPL")

    # The model wrote only numbers; the links come from this run's headlines.
    assert result["summary"] == "A delay was reported [2], and a rival said so too."
    assert result["citations"] == [
        {"number": 2, "source": "Reuters", "url": "https://reut.example/2"},
    ]
    assert "invalid_citation" in result["quality_flags"]


async def test_citation_markers_with_no_news_fetched_are_all_removed(env):
    submit = {**SUBMIT_INPUT, "explanation": "Something was reported [1]."}
    env.responses.append(fake_response([tool_use("submit_analysis", submit)]))

    result = await orchestrator.run_explainer("AAPL")

    assert result["summary"] == "Something was reported."
    assert result["citations"] == []


async def test_quality_flags_measure_the_explanation_without_rewriting_it(env):
    long = " ".join(["word"] * 100) + "."
    env.responses.append(
        fake_response([tool_use("submit_analysis", {**SUBMIT_INPUT, "explanation": long})])
    )

    result = await orchestrator.run_explainer("AAPL")

    assert "too_long" in result["quality_flags"]
    assert result["summary"] == long


async def test_finished_runs_are_saved_when_volx_save_runs_is_set(env, monkeypatch, tmp_path):
    path = tmp_path / "runs.jsonl"
    monkeypatch.setattr(orchestrator, "_SAVE_RUNS_PATH", str(path))
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    await orchestrator.run_explainer("AAPL", "why did AAPL drop?")

    [record] = [json.loads(line) for line in path.read_text().splitlines()]
    assert record["query"] == "why did AAPL drop?"
    assert record["raw_explanation"] == SUBMIT_INPUT["explanation"]
    assert record["quality_flags"] == []


async def test_out_of_scope_guardrail(env):
    env.responses.append(
        fake_response([tool_use("flag_out_of_scope", {"message": "Stocks and ETFs only."})])
    )

    result = await orchestrator.run_explainer("AAPL", "write me a poem")

    assert result["status"] == "guardrail"
    assert result["error_message"] == "Stocks and ETFs only."
    assert result["summary"] == ""
    assert result["tiles"] == [] and result["hypotheses"] == []
    assert env.client.messages.stream.call_count == 1


async def test_turn_limit_exhaustion_returns_incomplete(env):
    # Model never calls a terminal tool; duplicates are served from memory so the
    # loop keeps going until _MAX_TURNS, then returns status=incomplete.
    env.responses.extend(
        [fake_response([tool_use("get_news", {"ticker": "AAPL"})])] * orchestrator._MAX_TURNS
    )

    result = await orchestrator.run_explainer("AAPL")

    assert result["status"] == "incomplete"
    assert result["summary"] == ""
    assert env.client.messages.stream.call_count == orchestrator._MAX_TURNS


async def test_plain_text_response_stops_loop_as_incomplete(env):
    env.responses.append(fake_response([FakeBlock("text", text="Here is my answer as prose")]))

    result = await orchestrator.run_explainer("AAPL")

    assert result["status"] == "incomplete"
    assert env.client.messages.stream.call_count == 1  # stops, doesn't loop to max turns


async def test_unknown_tool_returns_error_result_and_loop_continues(env):
    env.responses.extend([
        fake_response([tool_use("get_nonexistent", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer("AAPL")

    assert result["status"] == "complete"
    # The error was fed back to the model as that tool's result.
    second_call_messages = env.client.messages.stream.call_args_list[1].kwargs["messages"]
    tool_results = [
        json.loads(block["content"])
        for msg in second_call_messages if msg["role"] == "user"
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert {"error": "Unknown tool: get_nonexistent"} in tool_results


async def test_tool_exception_becomes_error_result(env, monkeypatch):
    monkeypatch.setitem(
        orchestrator._TOOL_DISPATCH, "get_news",
        lambda inp: (_ for _ in ()).throw(RuntimeError("finnhub down")),
    )
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer("AAPL")

    assert result["status"] == "complete"
    assert result["data"]["get_news"] == {"error": "finnhub down"}


async def test_cache_hit_short_circuits_fetch_and_is_reported(env):
    env.cache_store["get_price_data"] = PRICE_RESULT
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    result = await orchestrator.run_explainer("AAPL")

    assert result["status"] == "complete"
    assert result["cache_hits"] == ["get_price_data"]


async def test_prefetched_tools_are_spliced_into_first_llm_call(env):
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    await orchestrator.run_explainer("AAPL", "why the move?")

    first_call = env.client.messages.stream.call_args_list[0].kwargs
    messages = first_call["messages"]
    # user question, assistant tool_use splice, user tool_result splice
    assert messages[0]["role"] == "user" and "why the move?" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
    assert [b["name"] for b in messages[1]["content"]] == list(orchestrator._PREFETCH_TOOLS)

    spliced = {
        block["tool_use_id"]: json.loads(block["content"]) for block in messages[2]["content"]
    }
    assert spliced["toolu_prefetch_get_price_data"] == PRICE_RESULT
    assert spliced["toolu_prefetch_get_events"] == EVENTS_RESULT


async def test_events_are_prefetched_without_an_extra_llm_turn(env):
    """The whole point of promoting get_events: the model has the event calendar on turn
    one, so it never has to spend a round trip asking for it."""
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    result = await orchestrator.run_explainer("AAPL")

    assert result["data"]["get_events"] == EVENTS_RESULT
    assert env.client.messages.stream.call_count == 1


async def test_both_prefetched_tools_report_cache_hits(env):
    env.cache_store["get_price_data"] = PRICE_RESULT
    env.cache_store["get_events"] = EVENTS_RESULT
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    result = await orchestrator.run_explainer("AAPL")

    assert result["cache_hits"] == ["get_events", "get_price_data"]


async def test_analyst_upside_is_reanchored_to_the_runs_price(env):
    """The tool computes upside against yfinance's own `current`; the summary quotes
    get_price_data's price. One run must never contain two prices for one stock."""
    env.responses.extend([
        fake_response([tool_use("get_analyst_sentiment", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer("AAPL")

    target = result["data"]["get_analyst_sentiment"]["price_target"]
    assert target["current_price"] == PRICE_RESULT["price"]  # not the stubbed 80.0
    assert target["upside_vs_mean_pct"] == 20.0  # 120 vs 100, not vs 80
    assert target["upside_vs_median_pct"] == 30.0


async def test_reanchoring_also_applies_to_a_cached_analyst_result(env):
    """Analyst data is cached 12h but price 15min — an upside baked in at fetch time goes
    stale long before the entry expires."""
    env.cache_store["get_analyst_sentiment"] = {
        **ANALYST_RESULT, "price_target": dict(ANALYST_RESULT["price_target"])
    }
    env.responses.extend([
        fake_response([tool_use("get_analyst_sentiment", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer("AAPL")

    target = result["data"]["get_analyst_sentiment"]["price_target"]
    assert target["current_price"] == 100.0
    assert target["upside_vs_mean_pct"] == 20.0


async def test_second_run_is_served_from_the_in_process_memo(env, monkeypatch):
    """Redis is optional, so without this tier every request re-fetched every tool from
    the upstream API."""
    calls: list[str] = []
    monkeypatch.setitem(
        orchestrator._TOOL_DISPATCH, "get_price_data",
        lambda inp: (calls.append("price"), PRICE_RESULT)[1],
    )
    env.responses.extend([
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    await orchestrator.run_explainer("AAPL")
    assert calls == ["price"]

    result = await orchestrator.run_explainer("AAPL")

    assert calls == ["price"]  # no second upstream fetch
    assert "get_price_data" in result["cache_hits"]


async def test_memo_is_scoped_per_ticker(env, monkeypatch):
    calls: list[str] = []
    monkeypatch.setitem(
        orchestrator._TOOL_DISPATCH, "get_price_data",
        lambda inp: (calls.append(inp["ticker"]), PRICE_RESULT)[1],
    )
    env.responses.extend([
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    await orchestrator.run_explainer("AAPL")
    await orchestrator.run_explainer("NVDA")

    assert calls == ["AAPL", "NVDA"]


async def test_a_hanging_tool_times_out_without_stalling_the_turn(env, monkeypatch):
    """gather waits for every tool, so one unresponsive upstream would otherwise hold the
    turn — and the SSE stream behind it — open indefinitely."""
    import time as real_time

    monkeypatch.setattr(orchestrator, "_TOOL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setitem(
        orchestrator._TOOL_DISPATCH, "get_news", lambda inp: real_time.sleep(0.5) or NEWS_RESULT
    )
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    started = real_time.perf_counter()
    result = await orchestrator.run_explainer("AAPL")
    elapsed = real_time.perf_counter() - started

    assert elapsed < 0.4  # returned on the deadline, not after the 0.5s sleep
    assert "timed out" in result["data"]["get_news"]["error"]
    assert result["status"] == "complete"  # the investigation still finished


async def test_a_timed_out_tool_is_still_reported_to_the_model(env, monkeypatch):
    import time as real_time

    monkeypatch.setattr(orchestrator, "_TOOL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setitem(
        orchestrator._TOOL_DISPATCH, "get_news", lambda inp: real_time.sleep(0.5) or NEWS_RESULT
    )
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    await orchestrator.run_explainer("AAPL")

    # messages is mutated in place across turns, so scan for the tool_result turn rather
    # than indexing a position that has since moved.
    messages = env.client.messages.stream.call_args_list[1].kwargs["messages"]
    tool_results = [
        json.loads(block["content"])
        for message in messages
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert any("timed out" in result.get("error", "") for result in tool_results)


async def test_on_step_callback_receives_progress_labels(env):
    steps: list[str] = []
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    await orchestrator.run_explainer("AAPL", on_step=steps.append)

    assert steps == [
        "Pulling price data...",
        "Checking earnings dates and upcoming catalysts...",
        "Deciding what to investigate...",
        "Scanning recent news headlines...",
        "Synthesizing findings...",
    ]


# ── Streaming the summary ────────────────────────────────────────────────────


async def test_summary_streams_progressively_while_it_is_written(env):
    """The final turn is ~10s of generation. on_summary surfaces the write-up as it is
    produced so the reader sees prose instead of a spinner."""
    partials: list[str] = []
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer("AAPL", on_summary=partials.append)

    assert len(partials) > 1, "summary arrived in one chunk — not actually streaming"
    assert partials[-1] == SUBMIT_INPUT["explanation"]
    assert result["summary"] == SUBMIT_INPUT["explanation"]


async def test_streamed_summary_is_cumulative_and_monotonic(env):
    """Each event carries the whole summary so far, so a dropped event can't corrupt the
    client's buffer. Every emission must extend the previous one."""
    partials: list[str] = []
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    await orchestrator.run_explainer("AAPL", on_summary=partials.append)

    for earlier, later in itertools.pairwise(partials):
        assert later.startswith(earlier), f"{later!r} does not extend {earlier!r}"
    assert partials == sorted(partials, key=len)


async def test_no_summary_events_for_a_tool_selection_turn(env):
    """Only submit_analysis carries a summary — a tool-selection turn must emit nothing."""
    partials: list[str] = []
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("flag_out_of_scope", {"message": "Stocks and ETFs only."})]),
    ])

    await orchestrator.run_explainer("AAPL", on_summary=partials.append)

    assert partials == []


async def test_run_works_without_an_on_summary_callback(env):
    """The callback is optional — the non-streaming callers must be unaffected."""
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    result = await orchestrator.run_explainer("AAPL")

    assert result["status"] == "complete"
    assert result["summary"] == SUBMIT_INPUT["explanation"]


def test_explanation_is_written_after_tiles_and_hypotheses():
    """The model emits properties in schema order. The why-paragraph must come LAST, so it
    is generated from the evidence and ranked hypotheses rather than ahead of them — a
    summary-first schema had the model concluding before it had reasoned."""
    properties = list(tool_schemas.TOOL_DEFINITIONS[-1]["input_schema"]["properties"])

    assert properties[-1] == orchestrator._STREAMED_FIELD
    assert properties.index("hypotheses") < properties.index(orchestrator._STREAMED_FIELD)
    assert properties.index("tiles") < properties.index(orchestrator._STREAMED_FIELD)


def test_no_nested_submit_analysis_property_shares_the_streamed_field_name():
    """The partial-JSON reader takes the first occurrence of the key. With the field last,
    any nested key of the same name (as tiles' `summary` is) would stream instead of it."""
    def keys(schema: dict) -> set[str]:
        found = set(schema.get("properties", {}))
        for child in schema.get("properties", {}).values():
            found |= keys(child)
        if "items" in schema:
            found |= keys(schema["items"])
        return found

    schema = tool_schemas.TOOL_DEFINITIONS[-1]["input_schema"]
    nested = set().union(*(keys(p) for p in schema["properties"].values()))

    assert orchestrator._STREAMED_FIELD not in nested


# ── The deterministic overview ───────────────────────────────────────────────


async def test_overview_is_emitted_once_before_any_llm_call(env):
    """The "what happened" paragraph comes from code, so it must reach the reader while the
    model is still picking tools — not after the write-up."""
    timeline: list[str] = []

    def recording_stream(**kwargs):
        timeline.append("<llm call>")
        return FakeStream(env.responses.pop(0))

    env.client.messages.stream = MagicMock(side_effect=recording_stream)
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    result = await orchestrator.run_explainer(
        "AAPL", on_overview=lambda text: timeline.append(f"overview: {text}")
    )

    overviews = [t for t in timeline if t.startswith("overview: ")]
    assert overviews == [f"overview: {orchestrator.describe_move(PRICE_RESULT)}"]
    assert timeline.index(overviews[0]) < timeline.index("<llm call>")
    assert result["overview"] == orchestrator.describe_move(PRICE_RESULT)
    assert result["summary"] == SUBMIT_INPUT["explanation"]


async def test_model_is_shown_the_overview_the_reader_already_has(env):
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    await orchestrator.run_explainer("AAPL", "why did AAPL drop?")

    first_user_turn = env.client.messages.stream.call_args_list[0].kwargs["messages"][0]["content"]
    assert orchestrator.describe_move(PRICE_RESULT) in first_user_turn


async def test_no_overview_when_price_data_failed(env, monkeypatch):
    """Nothing factual to say — send nothing rather than a paragraph of blanks."""
    monkeypatch.setitem(orchestrator._TOOL_DISPATCH, "get_price_data", lambda inp: {"error": "down"})
    overviews: list[str] = []
    env.responses.append(fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]))

    result = await orchestrator.run_explainer("AAPL", on_overview=overviews.append)

    assert overviews == []
    assert result["overview"] == ""
    first_user_turn = env.client.messages.stream.call_args_list[0].kwargs["messages"][0]["content"]
    assert "overview" not in first_user_turn


def test_submit_analysis_opts_into_fine_grained_streaming():
    assert tool_schemas.TOOL_DEFINITIONS[-1]["eager_input_streaming"] is True


async def test_every_llm_turn_is_covered_by_a_label_emitted_before_it(env):
    """A step stays on screen until the next one arrives, so a label emitted AFTER its work
    charges that duration to whichever label preceded it. The final synthesis turn is the
    longest step in a run — it used to be attributed to whatever tool the model named last,
    making that tool look broken. Every LLM call must be preceded by its own label.
    """
    timeline: list[str] = []

    def recording_stream(**kwargs):
        timeline.append("<llm call>")
        return FakeStream(env.responses.pop(0))

    env.client.messages.stream = MagicMock(side_effect=recording_stream)
    env.responses.extend([
        fake_response([tool_use("get_news", {"ticker": "AAPL"})]),
        fake_response([tool_use("submit_analysis", SUBMIT_INPUT)]),
    ])

    await orchestrator.run_explainer("AAPL", on_step=timeline.append)

    assert timeline == [
        "Pulling price data...",
        "Checking earnings dates and upcoming catalysts...",
        "Deciding what to investigate...",
        "<llm call>",                               # tool selection, covered above
        "Scanning recent news headlines...",
        "Synthesizing findings...",
        "<llm call>",                               # the ~10s write-up, covered above
    ]


async def test_guardrail_turn_still_gets_a_label(env):
    steps: list[str] = []
    env.responses.append(
        fake_response([tool_use("flag_out_of_scope", {"message": "Stocks and ETFs only."})])
    )

    result = await orchestrator.run_explainer("AAPL", on_step=steps.append)

    assert result["status"] == "guardrail"
    assert steps[-1] == "Deciding what to investigate..."


# ── Partial-JSON extraction ──────────────────────────────────────────────────


def _extract(buffer: str) -> str | None:
    return orchestrator._partial_json_string(buffer, "summary")


def test_partial_json_returns_none_before_the_value_starts():
    assert _extract("") is None
    assert _extract('{"summ') is None
    assert _extract('{"summary"') is None
    assert _extract('{"summary":') is None
    assert _extract('{"summary": ') is None


def test_partial_json_finds_a_field_that_follows_earlier_properties():
    buffer = '{"tiles": [{"summary": "Down 4.1%."}], "hypotheses": [], "explanation": "A supply'
    assert orchestrator._partial_json_string(buffer, "explanation") == "A supply"


def test_partial_json_reads_a_value_still_being_written():
    assert _extract('{"summary": "AAPL fell 4.1% beca') == "AAPL fell 4.1% beca"


def test_partial_json_reads_a_completed_value():
    assert _extract('{"summary": "AAPL fell.", "tiles": []}') == "AAPL fell."


def test_partial_json_decodes_escapes():
    assert _extract('{"summary": "He said \\"buy\\" today') == 'He said "buy" today'
    assert _extract('{"summary": "line one\\nline two') == "line one\nline two"
    assert _extract('{"summary": "back\\\\slash') == "back\\slash"


def test_partial_json_trims_a_half_written_escape():
    """A \\uXXXX escape can be split across two deltas — the caller must never see a
    mangled character while the rest is in flight."""
    assert _extract('{"summary": "caf\\u00e') == "caf"
    assert _extract('{"summary": "caf\\u00e9') == "café"
    # Buffer ends on a lone backslash — the escaped character hasn't arrived yet.
    assert _extract('{"summary": "trailing\\') == "trailing"
    # A COMPLETE escaped backslash is a real character and must survive.
    assert _extract('{"summary": "back\\\\slash') == "back\\slash"


def test_partial_json_handles_an_escaped_quote_not_ending_the_value():
    assert _extract('{"summary": "a \\" b') == 'a " b'


def test_partial_json_matches_the_first_occurrence_of_the_field():
    """Documents the limitation the streamed field's unique name exists to avoid — see
    test_no_nested_submit_analysis_property_shares_the_streamed_field_name."""
    buffer = '{"summary": "top level", "tiles": [{"summary": "tile text"'
    assert _extract(buffer) == "top level"


def test_partial_json_returns_none_when_the_field_is_absent():
    assert _extract('{"tiles": [], "hypotheses": []}') is None


def test_partial_json_empty_value():
    assert _extract('{"summary": "') == ""
