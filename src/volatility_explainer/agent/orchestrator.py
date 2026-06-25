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


def _build_context(ticker: str, data: dict) -> str:
    return f"""Analyze the implied volatility for {ticker.upper()}.

=== PRICE & REALIZED VOLATILITY ===
{json.dumps(data.get("price", {}), indent=2, default=str)}

=== OPTIONS CHAIN (IV, SKEW, PUT/CALL RATIO) ===
{json.dumps(data.get("options", {}), indent=2, default=str)}

=== RECENT NEWS (last 7 days) ===
{json.dumps(data.get("news", {}), indent=2, default=str)}

=== MACRO BACKDROP (VIX) ===
{json.dumps(data.get("macro", {}), indent=2, default=str)}

=== UPCOMING EVENTS ===
{json.dumps(data.get("events", {}), indent=2, default=str)}
"""


def run_explainer(ticker: str) -> dict:
    """Fetch all 5 data sources in parallel, then call Claude for synthesis."""
    ticker = ticker.upper()

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
    api_key = get_settings().anthropic_api_key.get_secret_value() or None
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_context(ticker, raw)}],
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

    return {
        "ticker": ticker,
        "data": raw,
        "summary": parsed.get("summary", ""),
        "tiles": parsed.get("tiles", []),
        "hypotheses": parsed.get("hypotheses", []),
        "status": "complete",
    }
