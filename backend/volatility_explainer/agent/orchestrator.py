"""Agent orchestrator — Claude-driven tool-use loop for financial investigation."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from typing import Any

import anthropic
from volatility_explainer.agent.prompts import SYSTEM_PROMPT
from volatility_explainer.clients.redis_cache import (
    get_cached_tool_data,
    get_memoized_tool_data,
    set_cached_tool_data,
    set_memoized_tool_data,
)
from volatility_explainer.config import get_settings
from volatility_explainer.mcp.tools.analyst import apply_reference_price, fetch_analyst_sentiment
from volatility_explainer.mcp.tools.events import fetch_events
from volatility_explainer.mcp.tools.macro import fetch_macro
from volatility_explainer.mcp.tools.news import fetch_news
from volatility_explainer.mcp.tools.options import fetch_options_data, fetch_options_positioning
from volatility_explainer.mcp.tools.price import fetch_price_data
from volatility_explainer.mcp.tools.sector import fetch_sector_comparison

# Set VOLX_LOG_LLM_PAYLOAD=1 for per-turn LLM diagnostics: payload sizes, the content-block
# breakdown, and a full dump of the system/tools/messages sent to the model. Off by default;
# timing, token usage, and cache hits are always printed.
_LOG_LLM_PAYLOAD = os.environ.get("VOLX_LOG_LLM_PAYLOAD") == "1"

_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_price_data",
        "description": (
            "Fetch current price, daily % change, and 20-day realized volatility for a ticker, "
            "plus move_assessment — a deterministic significance verdict (overall level plus "
            "one plain-English flag per non-typical horizon). "
            "ALREADY CALLED FOR YOU — check the conversation above for its result before calling this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_news",
        "description": (
            "Fetch recent news headlines for a ticker (last 7 days). Not pre-fetched — decide "
            "whether to call it based on price_data (already given) and the question. Almost "
            "always worth calling when the horizon relevant to the question has a flag in "
            "move_assessment (especially an 'unusual' one) and the question is (or implies) "
            "'why did this move' — that's the catalyst check. Skip it for questions that "
            "aren't about causation (e.g. pure valuation/analyst-opinion questions) or for an "
            "unflagged, plainly typical move."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_options_data",
        "description": (
            "Quick snapshot of how the options market is pricing the next 2-4 weeks for this "
            "stock (implied volatility, put/call ratio, skew) — a general hint of market mood, "
            "not a deep dive. Not pre-fetched — worth calling alongside get_news as a brief "
            "secondary signal for a significant move, or whenever the question touches on what "
            "the market expects next. Skip it if the question doesn't relate to market "
            "positioning/expectations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_options_positioning",
        "description": (
            "A deeper look at how the options market is positioned for this stock over the "
            "next 2-4 weeks: max pain (the strike price options traders are effectively "
            "betting the stock settles near), call/put open-interest walls (support/resistance "
            "levels), IV term structure across the horizon, and unusual volume vs. open "
            "interest (signals fresh positioning being put on today, not stale interest). "
            "This is NOT called in the first tool-selection pass — only call it, in a later "
            "turn, when the question specifically needs this depth (\"where are options "
            "traders positioned\", \"what's the max pain level\", \"is there unusual options "
            "activity\") or when get_options_data's quick snapshot showed something — like an "
            "unusually high put/call ratio or IV — that warrants investigating further. Skip "
            "this for routine questions; it is a deliberate, deeper second-layer step, not a "
            "default check."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_analyst_sentiment",
        "description": (
            "The Wall Street analyst view, in two parts. recent_actions: DATED rating "
            "changes from the last 30 days — which firm upgraded or downgraded the stock, "
            "and whether they raised or cut their price target. consensus and price_target: "
            "where the Street stands now — rating, a plain-English verdict, whether that "
            "consensus has been improving or deteriorating over recent months, and the mean/"
            "median/high/low targets with how dispersed they are. Never pre-fetched. "
            "Call it when the question is about valuation or sentiment (\"is this "
            "overvalued\", \"what does the Street think\", \"should I be worried\"), AND "
            "also as a catalyst check on a flagged move: a downgrade with a price-target cut "
            "a few days ago is a genuine, datable cause of a drop, so a non-empty "
            "recent_actions is real evidence for a \"why did it move\" answer. The standing "
            "consensus on its own is NOT — that is a medium-term view, not a live reaction, "
            "so do not offer it as the cause of a single day's move. "
            "analyst_coverage of 'none' means the ticker genuinely has no analysts (an ETF "
            "or fund) — a valid, expected result, not a failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_sector_comparison",
        "description": (
            "Compares this stock's % move over the same horizons (today, 1 week, 2 weeks, "
            "1 month, 1 year) against its own sector's ETF (e.g. Technology stocks vs. XLK). "
            "Never pre-fetched — call this when you need a MORE PRECISE stock-specific-vs-"
            "industry-wide check than get_macro provides. get_macro only tells you if the "
            "whole market moved (S&P 500 / VIX); this tells you if the stock's SECTOR moved "
            "with it, which is the better test when the news or the user's question points to "
            "an industry-wide theme (e.g. \"did all bank stocks drop\", \"is this a tech "
            "selloff or just this stock\", chip-sector news, sector-wide regulation). Prefer "
            "get_macro first for a broad market check; reach for this when the question is "
            "specifically about sector/peer behavior or get_macro doesn't fully explain the move."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_macro",
        "description": (
            "Fetch macro indicators: VIX level and S&P 500 daily change. "
            "Call this to determine if a move is stock-specific or part of a broader market move. "
            "If VIX spiked and SPX dropped broadly, that is market context — not a stock catalyst."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_events",
        "description": (
            "ALREADY CALLED FOR YOU — check the conversation above for its result before "
            "calling this. "
            "Fetches this ticker's event calendar in BOTH directions: recent_events (already "
            "happened — earnings it just reported, with the actual-vs-expected EPS beat/miss, "
            "and any ex-dividend date it just passed) and events (still ahead — next earnings "
            "date and next FOMC meeting). "
            "Use the backward-looking half whenever the question is \"why did this move\" and "
            "a horizon is flagged in move_assessment: a quarter reported in the last few days "
            "is one of the most common explanations there is, and an ex-dividend date makes a "
            "price drop MECHANICAL rather than a catalyst — do not invent a news explanation "
            "for a move that lands on one. Use the forward-looking half when pre-event "
            "positioning might be driving options activity, or when earnings proximity might "
            "explain a volatility spike. "
            "earnings_status of 'none' means this ticker genuinely has no earnings (an ETF or "
            "fund) — a valid answer, not a failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "flag_out_of_scope",
        "description": (
            "Call this INSTEAD of any data tool, and before calling anything else, if the "
            "request is not about a stock/ETF/market price movement. This is the only way "
            "to end the investigation as out-of-scope — do not write an error as plain text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Plain sentence telling the user this tool only investigates stock and ETF price movements.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "submit_analysis",
        "description": (
            "Call this to deliver your final write-up once the investigation is complete — "
            "this is the ONLY way to finish; never write the final answer as plain text. "
            "Call it exactly once, after you've gathered all the evidence you need."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "50-80 words, 2-3 sentences max: FIRST sentence must directly answer "
                        "the user's actual question using a real number from the data, from "
                        "the horizon they actually asked about (today/week/2 weeks/month/YTD/"
                        "year) — not a generic price-move restatement, and not silently "
                        "substituted with a different horizon's number. Keep it tight — the "
                        "supporting detail (catalyst, options lean, etc.) belongs in the tiles "
                        "and hypotheses below, not repeated here."
                    ),
                },
                "tiles": {
                    "type": "array",
                    "description": (
                        "One tile per tool result that MEANINGFULLY informed the answer — not "
                        "one per tool merely called. Skip a tile for any tool whose result "
                        "turned out uninformative or redundant with another tile (e.g. macro "
                        "showed nothing unusual and sector already covers the same ground). "
                        "get_price_data almost always earns a tile; news/options usually do too "
                        "when you called them. Curate like an analyst presenting findings, not a "
                        "log of every data source touched. Hard cap of 4 — if you have more "
                        "candidates, drop the least informative ones rather than including all."
                    ),
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent": {
                                "type": "string",
                                "enum": ["price", "news", "options", "macro", "events", "analyst", "sector"],
                            },
                            "title": {"type": "string", "description": "e.g. Price Action"},
                            "summary": {
                                "type": "string",
                                "description": "1-2 plain sentences (<=35 words) with a real number — easy for a beginner to read",
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "ONE short sentence (<=18 words): why this data mattered",
                            },
                        },
                        "required": ["agent", "title", "summary", "reasoning"],
                    },
                },
                "hypotheses": {
                    "type": "array",
                    "description": (
                        "At least TWO plausible drivers, ranked by confidence (rank 1 = most "
                        "likely). Even when one cause clearly dominates, include a genuinely "
                        "distinct second (or third) explanation — e.g. a broader sector/macro "
                        "contributor, a secondary catalyst, or 'no unusual driver found, within "
                        "normal noise' — rather than manufacturing a redundant near-duplicate of "
                        "the top hypothesis."
                    ),
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "rank": {"type": "integer"},
                            "hypothesis": {"type": "string", "description": "short phrase, max 10 words"},
                            "evidence": {"type": "string", "description": "one plain fact or number, or Limited"},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "caveat": {"type": "string", "description": "one clause or N/A"},
                        },
                        "required": ["rank", "hypothesis", "evidence", "confidence", "caveat"],
                    },
                },
            },
            "required": ["summary", "tiles", "hypotheses"],
        },
        "cache_control": {"type": "ephemeral"},
    },
]

_TERMINAL_TOOLS = {"submit_analysis", "flag_out_of_scope"}

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

# Ceiling on any single tool fetch. Measured tool times are 90-700ms; the retry helper in
# mcp/tools/_retry.py can add roughly another second. 15s is far above anything healthy,
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
        print(f"[agent] {name:<25} TIMED OUT after {_TOOL_TIMEOUT_SECONDS:.0f}s — continuing without it")
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


def _attach_news_citations(tiles: list[dict], tool_data: dict) -> list[dict]:
    """Attach numbered {number, source, url} citations to the news tile, sourced directly
    from get_news's headlines — not from the LLM — so links are always real, never
    hallucinated. Up to the first 3 headlines that actually have a url.
    """
    headlines = (tool_data.get("get_news") or {}).get("headlines") or []
    linked = [h for h in headlines if h.get("url")][:3]
    citations = [
        {"number": i + 1, "source": h.get("source") or "Source", "url": h["url"]}
        for i, h in enumerate(linked)
    ]
    if not citations:
        return tiles
    for tile in tiles:
        if tile.get("agent") == "news":
            tile["citations"] = citations
            break
    return tiles


async def run_explainer(
    ticker: str,
    query: str = "",
    on_step: Callable[[str], None] | None = None,
) -> dict:
    """Run the investigation: a deterministic parallel pre-fetch of _PREFETCH_TOOLS (price —
    non-negotiable, it also feeds the sideline chart — plus events), then a Claude-driven
    loop whose first turn is the real tool-selection layer. Informed by move_assessment, the
    event calendar and the user's question, it picks whichever of
    news/options/macro/analyst/sector genuinely help and calls them together in one turn. A
    second round only happens if the first round's results specifically warrant deeper
    digging; most investigations resolve in the first round.

    Async architecture: LLM turns (the long poles) are awaited natively; tool fetches stay
    sync — every tool can fall back to yfinance, which is sync-only — and run quarantined
    on worker threads, fanned out per turn with asyncio.gather. The event loop is never
    blocked, so many investigations can run concurrently in one process.

    Every tool fetch checks Redis right before calling it (see _fetch_with_cache) — there is
    no upfront bulk cache lookup, so a tool the investigation never needs is never checked.
    """
    ticker = ticker.upper()
    run_t0 = time.perf_counter()

    api_key = get_settings().anthropic_api_key.get_secret_value() or None
    client = anthropic.AsyncAnthropic(api_key=api_key)

    tool_data: dict[str, dict] = {}
    cache_hit_names: set[str] = set()
    llm_time = 0.0
    tool_time = 0.0

    # ── Deterministic pre-fetch — skip the LLM round trip for tools we always need ──
    if on_step:
        for name in _PREFETCH_TOOLS:
            on_step(_STEP_LABELS[name])

    batch_t0 = time.perf_counter()
    # One worker thread each, overlapped — the batch costs the slowest, not the sum.
    prefetched = await asyncio.gather(
        *(_run_tool_guarded(name, {"ticker": ticker}, ticker) for name in _PREFETCH_TOOLS)
    )
    tool_time += time.perf_counter() - batch_t0  # wall time of the batch, not the sum
    for name, result, hit, elapsed in prefetched:
        tool_data[name] = _with_price_context(name, result, tool_data)
        if hit:
            cache_hit_names.add(name)
        print(f"[agent] {name:<25} {elapsed * 1000:6.0f}ms  {'(cached, redis)' if hit else '(deterministic)'}")

    if query:
        user_content = (
            f"Investigate {ticker}. The user's question, which your summary must directly "
            f"answer: \"{query}\""
        )
    else:
        user_content = f"Investigate {ticker} — explain the recent price action."

    messages: list[dict] = [{"role": "user", "content": user_content}]

    # Splice the deterministically pre-fetched results in as a real assistant tool_use /
    # user tool_result turn — this is the exact format the model already handles reliably
    # for genuine tool calls, so it reads pre-fetched data the same way it reads its own.
    if tool_data:
        assistant_blocks = [
            {"type": "tool_use", "id": f"toolu_prefetch_{name}", "name": name, "input": {"ticker": ticker}}
            for name in tool_data
        ]
        result_blocks = [
            {"type": "tool_result", "tool_use_id": f"toolu_prefetch_{name}", "content": json.dumps(result, default=str)}
            for name, result in tool_data.items()
        ]
        messages.append({"role": "assistant", "content": assistant_blocks})
        messages.append({"role": "user", "content": result_blocks})

    # system is a single static block across every turn of this run (and identical across
    # runs) — mark it cacheable so only the growing tool-result tail gets re-processed each
    # turn. _TOOL_DEFINITIONS carries its own cache_control on its last entry (see above).
    system_blocks = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    final_kind: str | None = None  # "analysis" | "guardrail" | None (ran out of turns)
    final_input: dict = {}

    for turn in range(_MAX_TURNS):
        if _LOG_LLM_PAYLOAD:
            messages_json = json.dumps(messages, default=str)
            print(
                f"[llm]   turn {turn + 1} payload          messages={len(messages)}  "
                f"~{len(SYSTEM_PROMPT) + len(messages_json):,} chars (system+history, excl. tool defs)"
            )
            print(f"[llm]   turn {turn + 1} system:\n{SYSTEM_PROMPT}")
            print(f"[llm]   turn {turn + 1} messages:\n{json.dumps(messages, indent=2, default=str)}")

        llm_t0 = time.perf_counter()
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=system_blocks,
            tools=_TOOL_DEFINITIONS,
            tool_choice={"type": "any"},
            messages=messages,
        )
        llm_elapsed = time.perf_counter() - llm_t0
        llm_time += llm_elapsed

        usage = response.usage
        print(
            f"[llm]   turn {turn + 1} usage            in={usage.input_tokens} "
            f"(cache_read={usage.cache_read_input_tokens or 0}, "
            f"cache_write={usage.cache_creation_input_tokens or 0})  out={usage.output_tokens}"
        )
        # Breakdown of where output tokens actually went — a "text" block here is a preamble
        # the model wrote before its tool call, pure overhead we could suppress with a forced
        # tool_choice; "tool_use" size approximates the JSON payload itself (tiles/hypotheses).
        if _LOG_LLM_PAYLOAD:
            for block in response.content:
                if block.type == "text":
                    print(f"[llm]   turn {turn + 1} content block     text       {len(block.text):5d} chars (preamble — unwanted)")
                elif block.type == "tool_use":
                    size = len(json.dumps(block.input, default=str))
                    print(f"[llm]   turn {turn + 1} content block     tool_use   {size:5d} chars  ({block.name})")

        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        terminal_block = next((b for b in tool_blocks if b.name in _TERMINAL_TOOLS), None)
        print(f"[llm]   turn {turn + 1} {'(final)' if terminal_block else '(tool selection)':<17} {llm_elapsed * 1000:6.0f}ms")

        messages.append({"role": "assistant", "content": response.content})

        if terminal_block:
            if on_step and terminal_block.name == "submit_analysis":
                on_step("Synthesizing findings...")
            final_kind = "guardrail" if terminal_block.name == "flag_out_of_scope" else "analysis"
            final_input = terminal_block.input
            break

        if not tool_blocks:
            # Model replied with plain text instead of calling a tool (ignoring the
            # instruction to always finish via submit_analysis/flag_out_of_scope). Nothing
            # to send back — an empty tool_result user turn is rejected by the API — so
            # stop here rather than loop again; falls through to the "incomplete" status.
            break

        if on_step:
            for block in tool_blocks:
                on_step(_STEP_LABELS.get(block.name, f"Running {block.name}..."))

        tool_result_blocks: list[dict] = []
        results_by_id: dict[str, dict] = {}
        turn_tool_max = 0.0

        # The model occasionally re-requests a tool it already called this run (despite
        # the system prompt instruction not to) — serve those from the in-memory result
        # instead of paying for a redundant fetch or even a redundant Redis round trip.
        fresh_blocks = []
        for block in tool_blocks:
            if block.name in tool_data:
                print(f"[agent] {block.name:<25}   cached (duplicate call skipped)")
                results_by_id[block.id] = tool_data[block.name]
            else:
                fresh_blocks.append(block)

        batch_t0 = time.perf_counter()
        # Each sync tool runs on its own worker thread; gather overlaps them so the
        # turn costs max(tool times), not sum, and the event loop stays free.
        batch_results = await asyncio.gather(
            *(_run_tool_guarded(b.name, b.input, ticker) for b in fresh_blocks)
        )
        for block, (_, result, hit, elapsed) in zip(fresh_blocks, batch_results, strict=True):
            turn_tool_max = max(turn_tool_max, elapsed)  # tools run in parallel within a turn
            if hit:
                cache_hit_names.add(block.name)
            print(f"[agent] {block.name:<25} {elapsed * 1000:6.0f}ms  {'(cached, redis)' if hit else ''}")
            result = _with_price_context(block.name, result, tool_data)
            tool_data[block.name] = result
            results_by_id[block.id] = result
        if _LOG_LLM_PAYLOAD and len(fresh_blocks) > 1:
            # Wall time of the whole batch vs. the slowest individual call — if these are
            # close, the fetches genuinely overlapped rather than running one after another.
            batch_elapsed = time.perf_counter() - batch_t0
            print(f"[agent] {'+'.join(b.name for b in fresh_blocks):<25} {batch_elapsed * 1000:6.0f}ms  (batch wall time, n={len(fresh_blocks)})")
        tool_time += turn_tool_max

        for block in tool_blocks:
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(results_by_id[block.id], default=str),
            })

        messages.append({"role": "user", "content": tool_result_blocks})

    total_elapsed = time.perf_counter() - run_t0
    print(f"[orchestrator] {ticker:<6} total {total_elapsed * 1000:6.0f}ms  (llm {llm_time * 1000:.0f}ms, tools {tool_time * 1000:.0f}ms)")

    # Tools whose data came from Redis this run rather than a live fetch.
    cache_hits = sorted(cache_hit_names)

    if final_kind == "guardrail":
        return {
            "ticker": ticker,
            "data": tool_data,
            "summary": "",
            "tiles": [],
            "hypotheses": [],
            "status": "guardrail",
            "error_message": final_input.get("message", ""),
            "cache_hits": cache_hits,
        }

    return {
        "ticker": ticker,
        "data": tool_data,
        "summary": final_input.get("summary", ""),
        "tiles": _attach_news_citations(final_input.get("tiles", []), tool_data),
        "hypotheses": final_input.get("hypotheses", []),
        "status": "complete" if final_kind == "analysis" else "incomplete",
        "cache_hits": cache_hits,
    }
