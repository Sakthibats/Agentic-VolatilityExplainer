"""Agent orchestrator — the vendor-neutral tool-use loop for financial investigation.

The model behind the loop comes from volatility_explainer.llm (Claude or OpenAI); nothing in
this module depends on which one it is. What happens to the model's answer afterwards
(citations resolved to real links, the schema re-applied) lives in agent/answer.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from volatility_explainer.agent.answer import (
    attach_news_citations,
    normalize_answer,
    number_headlines,
    resolve_citations,
)
from volatility_explainer.agent.prompts import SYSTEM_PROMPT
from volatility_explainer.agent.quality import check_explanation
from volatility_explainer.agent.tool_schemas import TERMINAL_TOOLS, TOOL_DEFINITIONS
from volatility_explainer.clients.redis_cache import (
    get_cached_tool_data,
    get_memoized_tool_data,
    set_cached_tool_data,
    set_memoized_tool_data,
)
from volatility_explainer.config import get_settings
from volatility_explainer.llm import get_provider
from volatility_explainer.llm.base import (
    AssistantTurn,
    HistoryItem,
    LLMProvider,
    ToolCall,
    ToolResults,
    Usage,
    UserMessage,
)
from volatility_explainer.llm.pricing import cost_usd
from volatility_explainer.query.parsing import OUT_OF_SCOPE_MESSAGE
from volatility_explainer.significance import describe_move
from volatility_explainer.tools.analyst import apply_reference_price, fetch_analyst_sentiment
from volatility_explainer.tools.events import fetch_events
from volatility_explainer.tools.macro import fetch_macro
from volatility_explainer.tools.news import fetch_news
from volatility_explainer.tools.options import fetch_options_data, fetch_options_positioning
from volatility_explainer.tools.price import fetch_price_data
from volatility_explainer.tools.sector import fetch_sector_comparison

_logger = logging.getLogger(__name__)

# Set VOLX_LOG_LLM_PAYLOAD=1 for per-turn LLM diagnostics: payload sizes, the content-block
# breakdown, and a full dump of the system/tools/messages sent to the model. Off by default;
# timing, token usage, and cache hits are always printed.
_LOG_LLM_PAYLOAD = os.environ.get("VOLX_LOG_LLM_PAYLOAD") == "1"

# Set VOLX_SAVE_RUNS=path/to/runs.jsonl to append every finished run — its text, tool data
# and quality flags — to that file, for scripts/quality_report.py and new regression cases
# in tests/agent/test_quality.py. Off by default; meant for local runs, not production.
_SAVE_RUNS_PATH = os.environ.get("VOLX_SAVE_RUNS") or None

_TOOL_DISPATCH: dict[str, Any] = {
    "get_price_data":          lambda inp: fetch_price_data(inp["ticker"]),
    "get_news":                lambda inp: fetch_news(inp["ticker"]),
    "get_options_data":        lambda inp: fetch_options_data(inp["ticker"]),
    "get_options_positioning": lambda inp: fetch_options_positioning(inp["ticker"]),
    "get_analyst_sentiment":   lambda inp: fetch_analyst_sentiment(inp["ticker"]),
    "get_sector_comparison":   lambda inp: fetch_sector_comparison(inp["ticker"]),
    "get_macro":               lambda _: fetch_macro(),
    "get_events":              lambda inp: fetch_events(inp["ticker"]),
}

_MAX_TURNS = 7

# Output budget per turn. A reasoning model spends part of it thinking before it writes the
# tool call, so this leaves headroom over the ~1,000-token submit_analysis payload.
_MAX_OUTPUT_TOKENS = 2000

# Ceiling on any single tool fetch. Measured tool times are 90-700ms; the retry helper in
# tools/_retry.py can add roughly another second. 15s is far above anything healthy,
# which is the point — it exists to break a hang, not to trim the p99.
_TOOL_TIMEOUT_SECONDS = 15.0

# Fetched deterministically, in parallel, before the first LLM turn. A tool earns a place
# here only if it is needed on essentially every investigation AND informs the FIRST
# tool-selection decision — otherwise it belongs in the model's hands.
#   get_price_data — move_assessment is the input to every subsequent choice.
#   get_events     — whether the stock just reported, or is about to, is what decides
#                    whether the catalyst check is news or earnings; the model cannot make
#                    that call on turn one without it. It also carries the ex-dividend date,
#                    which stops a mechanical drop being explained as a news event — no use
#                    if the model never thinks to ask for it.
# Their fetches overlap, so the batch costs max(), not sum(): measured at ~0ms marginal
# wall time over the price fetch alone, and it saves a whole LLM round trip.
_PREFETCH_TOOLS: tuple[str, ...] = ("get_price_data", "get_events")

# submit_analysis's why-paragraph — the one field streamed to the reader as it is written.
# Surfaced as the result's `summary`; see tool_schemas.py for why it is the LAST property.
_STREAMED_FIELD = "explanation"


def _fetch_with_cache(name: str, ticker: str, fetch_fn: Callable[[], dict]) -> tuple[dict, bool]:
    """Check the caches for this one tool's result before calling its live fetch_fn.

    Two tiers, both under the same per-tool TTL: an in-process memo first (no network at
    all, and the only tier that exists when Redis is not configured), then Redis. Lookup
    happens tool-by-tool, right when a tool is about to be used — not as one big upfront
    batch — so a tool the investigation never needs is never checked at all.

    Returns (result, was_cache_hit). A miss fetches fresh and populates both tiers
    immediately so the next request for this ticker can hit.
    """
    memoized = get_memoized_tool_data(ticker, name)
    if memoized is not None:
        return memoized, True

    cached = get_cached_tool_data(ticker, [name])
    if name in cached:
        set_memoized_tool_data(ticker, name, cached[name])
        return cached[name], True

    result = fetch_fn()
    set_cached_tool_data(ticker, {name: result})
    set_memoized_tool_data(ticker, name, result)
    return result, False


def _execute_tool(name: str, inputs: dict, ticker: str) -> tuple[dict, bool]:
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}, False
    try:
        return _fetch_with_cache(name, ticker, lambda: fn(inputs))
    except Exception as exc:
        return {"error": str(exc)}, False


def _run_tool_timed(name: str, inputs: dict, ticker: str) -> tuple[str, dict, bool, float]:
    """_execute_tool with its own wall-clock timing, for the per-tool diagnostics."""
    t0 = time.perf_counter()
    result, hit = _execute_tool(name, inputs, ticker)
    return name, result, hit, time.perf_counter() - t0


async def _run_tool_guarded(name: str, inputs: dict, ticker: str) -> tuple[str, dict, bool, float]:
    """_run_tool_timed on a worker thread, under a deadline.

    Tools fan out with asyncio.gather, which waits for ALL of them — so without a ceiling
    one unresponsive upstream holds the whole turn, and the SSE stream behind it, open
    indefinitely. Every tool here normally answers in well under a second; the timeout is a
    hang-breaker, not a latency target. On expiry the model is handed an error for that one
    tool and the investigation continues on whatever else returned.

    The worker thread is not actually cancelled — that is a property of to_thread, not an
    oversight. It runs to completion in the background, and if it does eventually succeed
    its cache write still lands, so the next request for this ticker benefits from it.
    """
    t0 = time.perf_counter()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_tool_timed, name, inputs, ticker),
            timeout=_TOOL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        elapsed = time.perf_counter() - t0
        _logger.warning(f"[agent] {name:<25} TIMED OUT after {_TOOL_TIMEOUT_SECONDS:.0f}s — continuing without it")
        return (
            name,
            {"error": f"{name} timed out after {_TOOL_TIMEOUT_SECONDS:.0f}s"},
            False,
            elapsed,
        )


def _with_price_context(name: str, result: dict, tool_data: dict) -> dict:
    """Re-anchor a tool's price-relative numbers to the ONE price this run is built on.

    get_analyst_sentiment computes upside against yfinance's `current`, while the summary
    quotes get_price_data's price (Finnhub when configured). Intraday those diverge, and a
    write-up that names two different prices for one stock is simply wrong. Applied to
    cache hits too — see analyst.apply_reference_price for why that matters.
    """
    if name != "get_analyst_sentiment":
        return result
    return apply_reference_price(result, (tool_data.get("get_price_data") or {}).get("price"))


def _with_run_context(name: str, result: dict, tool_data: dict) -> dict:
    """Every per-run adjustment a tool result gets before the model — or the reader — sees it."""
    return number_headlines(name, _with_price_context(name, result, tool_data))


# Labels for the LLM turns themselves. These are emitted BEFORE the call they describe,
# which is the whole point: a step stays on screen until the NEXT one arrives, so a label
# emitted after its work reports time that has already elapsed — and silently charges its
# own duration to whichever label came before it. The final synthesis turn is the single
# longest step in a run (~10s), and it used to be attributed to whatever tool the model
# happened to name last, making that tool look broken.
_STEP_DECIDING = "Deciding what to investigate..."
_STEP_SYNTHESIZING = "Synthesizing findings..."

_STEP_LABELS: dict[str, str] = {
    "get_price_data":          "Pulling price data...",
    "get_news":                "Scanning recent news headlines...",
    "get_options_data":        "Checking options market mood...",
    "get_options_positioning": "Checking what options traders expect next...",
    "get_analyst_sentiment":   "Checking analyst ratings and price targets...",
    "get_sector_comparison":   "Comparing against sector peers...",
    "get_macro":               "Checking broader market context...",
    "get_events":              "Checking earnings dates and upcoming catalysts...",
}


def _partial_json_string(buffer: str, field: str) -> str | None:
    """Pull a top-level string field out of a JSON object that is still being streamed.

    The model streams submit_analysis's input as raw JSON fragments, so mid-flight the
    buffer is unparseable (`{..., "explanation": "AAPL fell because a supp`). This reads the
    value of `field` out of that partial text so it can be rendered as it is written,
    rather than after the whole payload lands. Returns None until the field's opening
    quote has arrived.

    Escapes are decoded via json.loads on the isolated value, and a trailing half-written
    escape (`\\u00` with the rest still in flight) is trimmed until it parses — so the
    caller never sees a mangled character.
    """
    key = f'"{field}"'
    start = buffer.find(key)
    if start == -1:
        return None
    colon = buffer.find(":", start + len(key))
    if colon == -1:
        return None

    i = colon + 1
    while i < len(buffer) and buffer[i].isspace():
        i += 1
    if i >= len(buffer) or buffer[i] != '"':
        return None  # value hasn't started (or isn't a string)

    chars: list[str] = []
    escaped = False
    for char in buffer[i + 1 :]:
        if escaped:
            chars.append(char)
            escaped = False
        elif char == "\\":
            chars.append(char)
            escaped = True
        elif char == '"':
            break  # closing quote — the value is complete
        else:
            chars.append(char)

    raw = "".join(chars)
    while raw:
        try:
            return json.loads(f'"{raw}"')
        except ValueError:
            raw = raw[:-1]  # trailing escape still arriving — drop it and retry
    return ""


def _save_run(record: dict) -> None:
    """Append one finished run to the VOLX_SAVE_RUNS file, as a JSON line."""
    with open(_SAVE_RUNS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


@dataclass
class _RunStats:
    """What a run measures about itself. Returned as result["usage"], not just printed: the
    eval harness scores cost and tool choice from it."""

    tokens: Usage = field(default_factory=Usage)
    turns: int = 0
    # The model's own tool picks, one list per turn; the deterministic prefetch is excluded.
    tool_rounds: list[list[str]] = field(default_factory=list)
    # Tools whose data came from a cache this run rather than a live fetch.
    cache_hits: set[str] = field(default_factory=set)
    llm_seconds: float = 0.0
    # Wall time: each parallel batch counts as its slowest call, not the sum.
    tool_seconds: float = 0.0

    def add_turn(self, usage: Usage, elapsed: float) -> None:
        self.turns += 1
        self.llm_seconds += elapsed
        for name in vars(self.tokens):
            setattr(self.tokens, name, getattr(self.tokens, name) + getattr(usage, name))

    def as_usage(self, provider: LLMProvider, total_seconds: float) -> dict:
        return {
            "turns": self.turns,
            **vars(self.tokens),
            "provider": provider.name,
            "model": provider.model,
            "cost_usd": cost_usd(provider.model, self.tokens),
            "tool_rounds": self.tool_rounds,
            "llm_ms": round(self.llm_seconds * 1000),
            "tool_ms": round(self.tool_seconds * 1000),
            "total_ms": round(total_seconds * 1000),
        }


async def _prefetch(
    ticker: str, on_step: Callable[[str], None] | None, stats: _RunStats
) -> dict[str, dict]:
    """Fetch _PREFETCH_TOOLS in parallel, before any LLM call. Returns the run's tool_data."""
    if on_step:
        for name in _PREFETCH_TOOLS:
            on_step(_STEP_LABELS[name])

    batch_t0 = time.perf_counter()
    # One worker thread each, overlapped — the batch costs the slowest, not the sum.
    prefetched = await asyncio.gather(
        *(_run_tool_guarded(name, {"ticker": ticker}, ticker) for name in _PREFETCH_TOOLS)
    )
    stats.tool_seconds += time.perf_counter() - batch_t0

    tool_data: dict[str, dict] = {}
    for name, result, hit, elapsed in prefetched:
        tool_data[name] = _with_run_context(name, result, tool_data)
        if hit:
            stats.cache_hits.add(name)
        _logger.info(f"[agent] {name:<25} {elapsed * 1000:6.0f}ms  {'(cached, redis)' if hit else '(deterministic)'}")
    return tool_data


def _opening_history(
    ticker: str, query: str, overview: str, tool_data: dict[str, dict]
) -> list[HistoryItem]:
    """The user turn, then the prefetched results spliced in as the model's own tool call."""
    if query:
        user_content = (
            f"Investigate {ticker}. The user's question, which your explanation must directly "
            f"answer: \"{query}\""
        )
    else:
        user_content = f"Investigate {ticker} — explain the recent price action."
    if overview:
        # The model must know exactly what the reader has already seen, or it restates it.
        user_content += (
            f"\n\nThe reader has already been shown this factual overview, computed from the "
            f"price data: \"{overview}\" Your explanation appears directly beneath it."
        )

    history: list[HistoryItem] = [UserMessage(user_content)]
    # A real assistant tool call / tool result pair is the exact format the model already
    # handles reliably for genuine tool calls, so it reads pre-fetched data the same way it
    # reads its own.
    if tool_data:
        history.append(AssistantTurn(tool_calls=[
            ToolCall(id=f"toolu_prefetch_{name}", name=name, input={"ticker": ticker})
            for name in tool_data
        ]))
        history.append(ToolResults([
            (f"toolu_prefetch_{name}", json.dumps(result, default=str))
            for name, result in tool_data.items()
        ]))
    return history


async def _model_turn(
    provider: LLMProvider,
    history: list[HistoryItem],
    on_summary: Callable[[str], None] | None,
) -> tuple[AssistantTurn, float]:
    """One streamed LLM turn. While submit_analysis is being written, its explanation is
    passed to on_summary as it grows (cumulative text). Returns (turn, elapsed seconds)."""
    streamed_text = ""

    def on_tool_input(_name: str, input_json: str) -> None:
        nonlocal streamed_text
        partial = _partial_json_string(input_json, _STREAMED_FIELD)
        if partial and partial != streamed_text:
            streamed_text = partial
            on_summary(partial)

    t0 = time.perf_counter()
    response = await provider.run_turn(
        system=SYSTEM_PROMPT,
        history=history,
        tools=TOOL_DEFINITIONS,
        max_tokens=_MAX_OUTPUT_TOKENS,
        stream_tool="submit_analysis",
        on_tool_input=on_tool_input if on_summary is not None else None,
    )
    return response, time.perf_counter() - t0


def _log_request(turn: int, history: list[HistoryItem]) -> None:
    """With VOLX_LOG_LLM_PAYLOAD=1: the payload size and full content about to be sent."""
    if not _LOG_LLM_PAYLOAD:
        return
    history_json = json.dumps([vars(item) for item in history], default=str)
    _logger.info(
        f"[llm]   turn {turn + 1} payload          history={len(history)}  "
        f"~{len(SYSTEM_PROMPT) + len(history_json):,} chars (system+history, excl. tool defs)"
    )
    _logger.info(f"[llm]   turn {turn + 1} system:\n{SYSTEM_PROMPT}")
    _logger.info(f"[llm]   turn {turn + 1} history:\n{history_json}")


def _log_response(turn: int, response: AssistantTurn, elapsed: float, final: bool) -> None:
    """Token usage and timing, always; where the output went, with VOLX_LOG_LLM_PAYLOAD=1."""
    usage = response.usage
    _logger.info(
        f"[llm]   turn {turn + 1} usage            in={usage.input_tokens} "
        f"(cache_read={usage.cache_read_tokens}, cache_write={usage.cache_write_tokens})  "
        f"out={usage.output_tokens} (reasoning={usage.reasoning_tokens})"
    )
    # Text is a preamble the model wrote before its tool call, pure overhead; a tool call's
    # size approximates the JSON payload itself (tiles/hypotheses).
    if _LOG_LLM_PAYLOAD:
        if response.text:
            _logger.info(f"[llm]   turn {turn + 1} content block     text       {len(response.text):5d} chars (preamble — unwanted)")
        for call in response.tool_calls:
            size = len(json.dumps(call.input, default=str))
            _logger.info(f"[llm]   turn {turn + 1} content block     tool_use   {size:5d} chars  ({call.name})")
    _logger.info(f"[llm]   turn {turn + 1} {'(final)' if final else '(tool selection)':<17} {elapsed * 1000:6.0f}ms")


async def _run_tool_round(
    tool_calls: list[ToolCall], tool_data: dict[str, dict], ticker: str, stats: _RunStats
) -> ToolResults:
    """Run one turn's tool calls in parallel, add them to tool_data, and return the results
    to send back to the model (one per call, in call order)."""
    results_by_id: dict[str, dict] = {}

    # The model occasionally re-requests a tool it already called this run (despite the
    # system prompt instruction not to) — serve those from the in-memory result instead of
    # paying for a redundant fetch or even a redundant Redis round trip.
    fresh_calls = []
    for call in tool_calls:
        if call.name in tool_data:
            _logger.info(f"[agent] {call.name:<25}   cached (duplicate call skipped)")
            results_by_id[call.id] = tool_data[call.name]
        else:
            fresh_calls.append(call)

    batch_t0 = time.perf_counter()
    # Each sync tool runs on its own worker thread; gather overlaps them so the turn costs
    # max(tool times), not sum, and the event loop stays free.
    batch_results = await asyncio.gather(
        *(_run_tool_guarded(call.name, call.input, ticker) for call in fresh_calls)
    )
    slowest = 0.0
    for call, (_, result, hit, elapsed) in zip(fresh_calls, batch_results, strict=True):
        slowest = max(slowest, elapsed)
        if hit:
            stats.cache_hits.add(call.name)
        _logger.info(f"[agent] {call.name:<25} {elapsed * 1000:6.0f}ms  {'(cached, redis)' if hit else ''}")
        result = _with_run_context(call.name, result, tool_data)
        tool_data[call.name] = result
        results_by_id[call.id] = result
    if _LOG_LLM_PAYLOAD and len(fresh_calls) > 1:
        # Wall time of the whole batch vs. the slowest individual call — if these are close,
        # the fetches genuinely overlapped rather than running one after another.
        batch_elapsed = time.perf_counter() - batch_t0
        _logger.info(f"[agent] {'+'.join(c.name for c in fresh_calls):<25} {batch_elapsed * 1000:6.0f}ms  (batch wall time, n={len(fresh_calls)})")
    stats.tool_seconds += slowest

    return ToolResults([
        (call.id, json.dumps(results_by_id[call.id], default=str)) for call in tool_calls
    ])


def _raw_explanation(final_input: dict) -> str:
    explanation = final_input.get(_STREAMED_FIELD) or ""
    return explanation if isinstance(explanation, str) else ""


def _guardrail_result(ticker: str, tool_data: dict, cache_hits: list[str], usage: dict) -> dict:
    return {
        "ticker": ticker,
        "data": tool_data,
        "overview": "",
        "summary": "",
        "tiles": [],
        "hypotheses": [],
        "status": "guardrail",
        # Always the standard text: flag_out_of_scope takes no input, and an older or
        # off-schema call that still sends a message is ignored.
        "error_message": OUT_OF_SCOPE_MESSAGE,
        "cache_hits": cache_hits,
        "usage": usage,
    }


def _analysis_result(
    *,
    ticker: str,
    query: str,
    overview: str,
    completed: bool,
    final_input: dict,
    tool_data: dict,
    cache_hits: list[str],
    usage: dict,
) -> dict:
    """The run's answer, held to the contract in code (agent/answer.py) and quality-checked.

    completed is False when the model never called submit_analysis (it wrote prose or ran out
    of turns): the result is then "incomplete", built from whatever final_input holds.
    """
    summary, citations, removed = resolve_citations(_raw_explanation(final_input), tool_data)
    tiles, hypotheses, answer_repairs = normalize_answer(final_input)
    tiles = attach_news_citations(tiles, tool_data)
    if answer_repairs and completed:
        _logger.info(f"[answer]  {ticker:<6} repaired: {', '.join(answer_repairs)}")

    # Measured, never enforced: the flags describe the write-up, they don't change it.
    quality_flags: list[str] = []
    if summary:
        try:
            quality_flags = check_explanation(
                summary, ticker=ticker, query=query, overview=overview,
                tool_data=tool_data, tiles=tiles, removed_citations=removed,
            )
            _logger.info(f"[quality] {ticker:<6} {', '.join(quality_flags) or 'clean'}")
        except Exception as exc:  # a heuristic must never cost the reader their answer
            _logger.warning(f"[quality] {ticker:<6} check FAILED — {exc}")

    return {
        "ticker": ticker,
        "data": tool_data,
        "overview": overview,
        "summary": summary,
        "citations": citations,
        "tiles": tiles,
        "hypotheses": hypotheses,
        "status": "complete" if completed else "incomplete",
        "cache_hits": cache_hits,
        "quality_flags": quality_flags,
        # Schema breaks the code fixed before the reader saw them. Measured like the quality
        # flags; deliberately not part of the API response or the Supabase row.
        "answer_repairs": answer_repairs if completed else [],
        "usage": usage,
    }


async def run_explainer(
    ticker: str,
    query: str = "",
    on_step: Callable[[str], None] | None = None,
    on_summary: Callable[[str], None] | None = None,
    on_overview: Callable[[str], None] | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    """Run one investigation and return its result dict.

    1. Prefetch _PREFETCH_TOOLS (price, events) in parallel: deterministic, no LLM.
    2. Send the code-built "what happened" overview to on_overview, before any model output.
    3. Loop at most _MAX_TURNS turns. Each turn the model must call tools: data tools run in
       parallel on worker threads (_run_tool_round) and their results go back to it; the run
       ends only when it calls submit_analysis or flag_out_of_scope. Most runs take two turns.
    4. Hold the answer to the contract in code and quality-check it (_analysis_result).

    Async architecture: LLM turns (the long poles) are awaited natively; tool fetches stay
    sync — every tool can fall back to yfinance, which is sync-only — and run on worker
    threads, so the event loop is never blocked. Every tool fetch checks the caches right
    before calling it (_fetch_with_cache), so a tool the investigation never needs is never
    looked up.

    The write-up reaches the reader in two paragraphs, in the order they can honestly be
    known: on_overview fires once with the deterministic paragraph (significance.describe_move);
    on_summary then receives submit_analysis's `explanation` (the "why") as it is written,
    which the schema places after tiles and hypotheses so it is generated from them. on_summary
    gets the cumulative text each time, not a delta, so a dropped call cannot corrupt it.

    `provider` defaults to the configured one (LLM_PROVIDER); the eval harness passes its own
    to compare models on identical data.
    """
    ticker = ticker.upper()
    run_t0 = time.perf_counter()
    if provider is None:
        provider = get_provider(get_settings())
    stats = _RunStats()

    tool_data = await _prefetch(ticker, on_step, stats)

    # The "what happened" paragraph, straight from code — on screen while the model is still
    # choosing tools, so the why-paragraph can take the time to be written last.
    overview = describe_move(tool_data.get("get_price_data") or {})
    if overview and on_overview:
        on_overview(overview)

    history = _opening_history(ticker, query, overview, tool_data)
    final_kind: str | None = None  # "analysis" | "guardrail" | None (no terminal tool called)
    final_input: dict = {}

    for turn in range(_MAX_TURNS):
        if on_step:
            # Turn 1 picks tools; every later turn is usually the write-up. When a later
            # turn instead asks for more data, its tool labels simply supersede this one.
            on_step(_STEP_DECIDING if turn == 0 else _STEP_SYNTHESIZING)

        _log_request(turn, history)
        response, elapsed = await _model_turn(provider, history, on_summary)
        stats.add_turn(response.usage, elapsed)
        terminal = next((c for c in response.tool_calls if c.name in TERMINAL_TOOLS), None)
        _log_response(turn, response, elapsed, final=terminal is not None)
        history.append(response)

        if terminal:
            # No step emitted here on purpose — _STEP_SYNTHESIZING already went out before
            # this turn's call, so it covered the generation the user actually waited on.
            final_kind = "guardrail" if terminal.name == "flag_out_of_scope" else "analysis"
            final_input = terminal.input
            break

        if not response.tool_calls:
            # Model replied with plain text instead of calling a tool (ignoring the
            # instruction to always finish via submit_analysis/flag_out_of_scope). Nothing
            # to send back — an empty tool_result user turn is rejected by the API — so
            # stop here rather than loop again; falls through to the "incomplete" status.
            break

        stats.tool_rounds.append([c.name for c in response.tool_calls])
        if on_step:
            for call in response.tool_calls:
                on_step(_STEP_LABELS.get(call.name, f"Running {call.name}..."))
        history.append(await _run_tool_round(response.tool_calls, tool_data, ticker, stats))

    total_elapsed = time.perf_counter() - run_t0
    _logger.info(f"[orchestrator] {ticker:<6} total {total_elapsed * 1000:6.0f}ms  (llm {stats.llm_seconds * 1000:.0f}ms, tools {stats.tool_seconds * 1000:.0f}ms)")
    usage = stats.as_usage(provider, total_elapsed)
    cache_hits = sorted(stats.cache_hits)

    if final_kind == "guardrail":
        return _guardrail_result(ticker, tool_data, cache_hits, usage)

    result = _analysis_result(
        ticker=ticker, query=query, overview=overview, completed=final_kind == "analysis",
        final_input=final_input, tool_data=tool_data, cache_hits=cache_hits, usage=usage,
    )
    if _SAVE_RUNS_PATH:
        record = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "query": query,
            "raw_explanation": _raw_explanation(final_input),
            **result,
        }
        await asyncio.to_thread(_save_run, record)
    return result
