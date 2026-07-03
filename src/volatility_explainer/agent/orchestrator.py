"""Agent orchestrator — Claude-driven tool-use loop for financial investigation."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import anthropic

from volatility_explainer.agent.prompts import SYSTEM_PROMPT
from volatility_explainer.config import get_settings
from volatility_explainer.mcp.tools.analyst import fetch_analyst_sentiment
from volatility_explainer.mcp.tools.events import fetch_events
from volatility_explainer.mcp.tools.macro import fetch_macro
from volatility_explainer.mcp.tools.news import fetch_news
from volatility_explainer.mcp.tools.options import fetch_options_data, fetch_options_positioning
from volatility_explainer.mcp.tools.price import fetch_price_data
from volatility_explainer.mcp.tools.sector import fetch_sector_comparison

_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_price_data",
        "description": (
            "Fetch current price, daily % change, and 20-day realized volatility for a ticker. "
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
            "Fetch recent news headlines for a ticker (last 7 days). "
            "If the price move was significant this was ALREADY CALLED FOR YOU — check the "
            "conversation above before calling this. Only call it yourself if there's no result "
            "for it yet and you need a catalyst."
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
            "not a deep dive. "
            "If the price move was significant this was ALREADY CALLED FOR YOU — check the "
            "conversation above before calling this. Only call it yourself if there's no result "
            "for it yet and you need to gauge market sentiment."
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
            "This is NOT pre-fetched automatically — call it yourself when the question "
            "specifically needs this depth: \"where are options traders positioned\", "
            "\"what's the max pain level\", \"is there unusual options activity\", or when "
            "get_options_data (the quick snapshot, which IS pre-fetched for a significant "
            "move) shows something — like an unusually high put/call ratio or IV — that "
            "warrants investigating further. Skip this for routine questions; it is a "
            "deliberate, deeper investigation step, not a default check."
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
            "Wall Street analyst consensus for this stock: rating (buy/hold/sell), average "
            "price target, target range, and how many analysts cover it. Never pre-fetched — "
            "only call this when the question is actually about valuation or sentiment, e.g. "
            "\"is this overbought\", \"is this overvalued\", \"what does the Street think\", "
            "\"should I be worried\", or when a large move raises the question of whether "
            "professional opinion has shifted. Not useful for explaining WHY a move happened "
            "today — it reflects analysts' medium-term view, not a live reaction. ETFs and "
            "some tickers have no analyst coverage; that is a valid, expected result, not a "
            "failure."
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
            "Fetch upcoming scheduled events: earnings date and next FOMC meeting. "
            "Call this when you suspect pre-event positioning is driving options activity, "
            "or when earnings proximity might explain a volatility spike."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
]

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


def _execute_tool(name: str, inputs: dict) -> dict:
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(inputs)
    except Exception as exc:
        return {"error": str(exc)}


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


_STEP_LABELS: dict[str, str] = {
    "get_price_data":          "Pulling price data...",
    "get_news":                "Scanning recent news headlines...",
    "get_options_data":        "Checking options market mood...",
    "get_options_positioning": "Checking what options traders expect next...",
    "get_analyst_sentiment":   "Checking analyst ratings and price targets...",
    "get_sector_comparison":   "Comparing against sector peers...",
    "get_macro":               "Checking broader market context...",
    "get_events":              "Looking up upcoming catalysts...",
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


def _is_significant_move(price_data: dict) -> bool:
    """True if ANY horizon (today, 1w, 2w, 1mo, 1y) is labeled "unusual" (beyond ~2x the
    stock's normal move for that span) in move_assessment. This is the ONLY gate for the
    extra news/options pre-fetch — it is driven purely by the computed numbers, never by how
    alarming the user's wording is, so a question like "why did it crash?" about a move that's
    actually typical does not trigger a bigger tool-use flow than the data justifies.
    """
    assessment = price_data.get("move_assessment") or {}
    return any(horizon.get("level") == "unusual" for horizon in assessment.values())


def run_explainer(
    ticker: str,
    query: str = "",
    on_step: Callable[[str], None] | None = None,
) -> dict:
    """Run the investigation: a deterministic price/news/options-snapshot pre-fetch (no LLM
    round trip), then a Claude-driven loop that genuinely chooses among optional tools
    (options positioning, analyst sentiment, sector comparison, macro, events), then
    synthesis.
    """
    ticker = ticker.upper()
    run_t0 = time.perf_counter()

    api_key = get_settings().anthropic_api_key.get_secret_value() or None
    client = anthropic.Anthropic(api_key=api_key)

    tool_data: dict[str, dict] = {}
    llm_time = 0.0
    tool_time = 0.0

    # ── Deterministic pre-fetch — skip the LLM round trip for tools we always need ──
    if on_step:
        on_step(_STEP_LABELS["get_price_data"])
    t0 = time.perf_counter()
    price_data = fetch_price_data(ticker)
    elapsed = time.perf_counter() - t0
    tool_time += elapsed
    tool_data["get_price_data"] = price_data
    print(f"[agent] {'get_price_data':<25} {elapsed * 1000:6.0f}ms  (deterministic)")

    if _is_significant_move(price_data):
        if on_step:
            on_step(_STEP_LABELS["get_news"])
            on_step(_STEP_LABELS["get_options_data"])
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(fetch_news, ticker): "get_news",
                pool.submit(fetch_options_data, ticker): "get_options_data",
            }
            for fut in as_completed(futures):
                name = futures[fut]
                tool_data[name] = fut.result()
        elapsed = time.perf_counter() - t0
        tool_time += elapsed
        print(f"[agent] {'get_news + get_options_data':<25} {elapsed * 1000:6.0f}ms  (deterministic, parallel)")

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

    response: anthropic.types.Message | None = None

    for turn in range(_MAX_TURNS):
        llm_t0 = time.perf_counter()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=_TOOL_DEFINITIONS,
            messages=messages,
        )
        llm_elapsed = time.perf_counter() - llm_t0
        llm_time += llm_elapsed
        is_final = response.stop_reason != "tool_use"
        print(f"[llm]   turn {turn + 1} {'(synthesis)' if is_final else '(tool selection)':<17} {llm_elapsed * 1000:6.0f}ms")

        messages.append({"role": "assistant", "content": response.content})

        if is_final:
            break

        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        if on_step:
            for block in tool_blocks:
                on_step(_STEP_LABELS.get(block.name, f"Running {block.name}..."))

        def _run_block(block: Any) -> tuple[Any, dict, float]:
            t0 = time.perf_counter()
            result = _execute_tool(block.name, block.input)
            return block, result, time.perf_counter() - t0

        tool_result_blocks: list[dict] = []
        results_by_id: dict[str, tuple[dict, float]] = {}
        turn_tool_max = 0.0

        # The model occasionally re-requests a tool it already called this run (despite
        # the system prompt instruction not to) — serve those from cache instead of
        # paying for a redundant fetch.
        fresh_blocks = []
        for block in tool_blocks:
            if block.name in tool_data:
                print(f"[agent] {block.name:<25}   cached (duplicate call skipped)")
                results_by_id[block.id] = tool_data[block.name]
            else:
                fresh_blocks.append(block)

        with ThreadPoolExecutor(max_workers=len(fresh_blocks) or 1) as pool:
            futures = {pool.submit(_run_block, b): b for b in fresh_blocks}
            for fut in as_completed(futures):
                block, result, elapsed = fut.result()
                turn_tool_max = max(turn_tool_max, elapsed)  # tools run in parallel within a turn
                print(f"[agent] {block.name:<25} {elapsed * 1000:6.0f}ms")
                tool_data[block.name] = result
                results_by_id[block.id] = result
        tool_time += turn_tool_max

        for block in tool_blocks:
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(results_by_id[block.id], default=str),
            })

        messages.append({"role": "user", "content": tool_result_blocks})

    if on_step:
        on_step("Synthesizing findings...")

    # Extract final synthesis text from last assistant message
    final_text = ""
    if response:
        for block in response.content:
            if hasattr(block, "text"):
                final_text = block.text.strip()
                break

    parsed = _parse_json(final_text)

    total_elapsed = time.perf_counter() - run_t0
    print(f"[orchestrator] {ticker:<6} total {total_elapsed * 1000:6.0f}ms  (llm {llm_time * 1000:.0f}ms, tools {tool_time * 1000:.0f}ms)")

    if parsed.get("error"):
        return {
            "ticker": ticker,
            "data": tool_data,
            "summary": "",
            "tiles": [],
            "hypotheses": [],
            "status": "guardrail",
            "error_message": parsed.get("message", ""),
        }

    return {
        "ticker": ticker,
        "data": tool_data,
        "summary": parsed.get("summary", ""),
        "tiles": _attach_news_citations(parsed.get("tiles", []), tool_data),
        "hypotheses": parsed.get("hypotheses", []),
        "status": "complete",
    }
