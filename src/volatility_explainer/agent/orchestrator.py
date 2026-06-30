"""Agent orchestrator — Claude-driven tool-use loop for financial investigation."""

from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import anthropic

from volatility_explainer.agent.prompts import SYSTEM_PROMPT
from volatility_explainer.config import get_settings
from volatility_explainer.mcp.tools.events import fetch_events
from volatility_explainer.mcp.tools.macro import fetch_macro
from volatility_explainer.mcp.tools.news import fetch_news
from volatility_explainer.mcp.tools.options import fetch_options_data, fetch_options_positioning
from volatility_explainer.mcp.tools.price import fetch_price_data

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
            "A general look at how the options market is positioned for this stock over the "
            "next 2-4 weeks — where traders expect the price to settle, and which way they're "
            "leaning. Still just a hint of what might be next, not the main story. "
            "If the price move was significant this was ALREADY CALLED FOR YOU — check the "
            "conversation above before calling this. Only call it yourself if there's no result "
            "for it yet and the user asks where the market is positioning the stock to go, or "
            "options activity looks meaningful enough to need more than get_options_data."
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
    "get_price_data":         lambda inp: fetch_price_data(inp["ticker"]),
    "get_news":               lambda inp: fetch_news(inp["ticker"]),
    "get_options_data":       lambda inp: fetch_options_data(inp["ticker"]),
    "get_options_positioning": lambda inp: fetch_options_positioning(inp["ticker"]),
    "get_macro":              lambda _: fetch_macro(),
    "get_events":             lambda inp: fetch_events(inp["ticker"]),
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
    "get_price_data":         "Pulling price data...",
    "get_news":               "Scanning recent news headlines...",
    "get_options_data":       "Checking options market mood...",
    "get_options_positioning": "Checking what options traders expect next...",
    "get_macro":              "Checking broader market context...",
    "get_events":             "Looking up upcoming catalysts...",
}


def _is_significant_move(price_data: dict) -> bool:
    """True if the move is beyond ~2x the stock's normal daily range."""
    change_pct = price_data.get("change_pct")
    rv = price_data.get("realized_vol_annualized_pct")
    if change_pct is None or not rv:
        return False
    daily_expected_move = rv / math.sqrt(252)
    if daily_expected_move <= 0:
        return False
    return abs(change_pct) > 2 * daily_expected_move


def run_explainer(
    ticker: str,
    query: str = "",
    on_step: Callable[[str], None] | None = None,
) -> dict:
    """Run the investigation: a deterministic price/news/options pre-fetch (no LLM round
    trip), then a short Claude-driven loop for optional context (macro, events, deeper
    options positioning), then synthesis.
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
            on_step(_STEP_LABELS["get_options_positioning"])
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(fetch_news, ticker): "get_news",
                pool.submit(fetch_options_data, ticker): "get_options_data",
                pool.submit(fetch_options_positioning, ticker): "get_options_positioning",
            }
            for fut in as_completed(futures):
                name = futures[fut]
                tool_data[name] = fut.result()
        elapsed = time.perf_counter() - t0
        tool_time += elapsed
        print(f"[agent] {'get_news + options (data+positioning)':<25} {elapsed * 1000:6.0f}ms  (deterministic, parallel)")

    if query:
        user_content = f"Investigate {ticker}. User question: {query}"
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
        "tiles": parsed.get("tiles", []),
        "hypotheses": parsed.get("hypotheses", []),
        "status": "complete",
    }
