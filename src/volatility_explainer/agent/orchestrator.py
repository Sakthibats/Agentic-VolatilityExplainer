"""Agent orchestrator — parallel data fetch + Claude reasoning."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from volatility_explainer.agent.prompts import SYSTEM_PROMPT
from volatility_explainer.config import get_settings
from volatility_explainer.mcp.tools.events import fetch_events
from volatility_explainer.mcp.tools.macro import fetch_macro
from volatility_explainer.mcp.tools.news import fetch_news
from volatility_explainer.mcp.tools.options import fetch_options_data
from volatility_explainer.mcp.tools.price import fetch_price_data


def _build_context(ticker: str, data: dict, query: str = "") -> str:
    import math

    question_block = (
        f"\n=== USER QUESTION ===\n\"{query}\"\n"
        "Answer this specific question in your summary paragraph 1.\n"
        if query
        else ""
    )

    price_data = data.get("price", {})
    rv = price_data.get("realized_vol_annualized_pct")
    vol_note = ""
    if rv:
        daily_expected = round(rv / math.sqrt(252), 2)
        vol_note = (
            f"\n[Context for volatility comparison: daily_expected_move_pct = ±{daily_expected:.1f}% "
            f"(based on 20-day realized vol of {rv:.1f}% annualized). "
            f"A move within this range is NORMAL for {ticker.upper()}. "
            f"Only moves beyond ±{daily_expected * 2:.1f}% (2 std devs) are genuinely unusual.]\n"
        )

    return f"""You are investigating {ticker.upper()}.{question_block}
Use the data below to answer the user's question and explain the price action.

=== PRICE & REALIZED VOLATILITY ==={vol_note}
{json.dumps(data.get("price", {}), indent=2, default=str)}

=== OPTIONS CHAIN (FLOW, SKEW, PUT/CALL RATIO) ===
{json.dumps(data.get("options", {}), indent=2, default=str)}

=== RECENT NEWS & CATALYSTS (last 7 days) ===
{json.dumps(data.get("news", {}), indent=2, default=str)}

=== MACRO BACKDROP (VIX, MARKET CONTEXT) ===
{json.dumps(data.get("macro", {}), indent=2, default=str)}

=== UPCOMING EVENTS & TRIGGERS ===
{json.dumps(data.get("events", {}), indent=2, default=str)}
"""


def run_explainer(ticker: str, query: str = "") -> dict:
    """Fetch all 5 data sources in parallel, then call Claude for synthesis."""
    ticker = ticker.upper()

    api_key = get_settings().anthropic_api_key.get_secret_value() or None
    client = anthropic.Anthropic(api_key=api_key)

    # Parallel data fetch
    tasks = {
        "price": (fetch_price_data, [ticker]),
        "options": (fetch_options_data, [ticker]),
        "news": (fetch_news, [ticker]),
        "macro": (fetch_macro, []),
        "events": (fetch_events, [ticker]),
    }

    raw: dict = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(fn, *args): name
            for name, (fn, args) in tasks.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                raw[name] = future.result()
            except Exception as exc:
                raw[name] = {"error": str(exc)}

    # Claude synthesis
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_context(ticker, raw, query)}],
    )

    response_text = message.content[0].text.strip()

    # Parse JSON — Claude is instructed to return only JSON
    parsed: dict = {}
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        # Try extracting a JSON block if model wrapped it in prose
        import re as _re
        match = _re.search(r"\{.*\}", response_text, _re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                parsed = {}

    if parsed.get("error"):
        return {
            "ticker": ticker,
            "data": raw,
            "summary": "",
            "tiles": [],
            "hypotheses": [],
            "status": "guardrail",
            "error_message": parsed.get("message", ""),
        }

    return {
        "ticker": ticker,
        "data": raw,
        "summary": parsed.get("summary", ""),
        "tiles": parsed.get("tiles", []),
        "hypotheses": parsed.get("hypotheses", []),
        "status": "complete",
    }
