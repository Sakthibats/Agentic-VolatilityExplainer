"""Replay a recorded fixture through the real agent loop.

Everything about the investigation is production code (prefetch, tool choice, timeouts,
citations, quality checks); only the data source changes. Every tool reads the fixture
instead of the network, and the tool caches are switched off so one case's data can't leak
into another. The fixture for the case being run lives in a context variable, which
asyncio.to_thread copies into the worker thread, so concurrent replays stay isolated.

Call install() once per process before replaying.
"""

from __future__ import annotations

import contextvars
import copy
import time
from typing import Any

from volatility_explainer.agent import orchestrator
from volatility_explainer.llm.base import LLMProvider
from volatility_explainer.tools.price import _assess_moves

_current_tools: contextvars.ContextVar[dict | None] = contextvars.ContextVar("fixture_tools", default=None)
_installed = False


def _serve(name: str):
    def fetch(_inputs: dict) -> dict:
        tools = _current_tools.get()
        if tools is None:
            raise RuntimeError("replay tool called outside replay(); no fixture is active")
        if name not in tools:
            return {"error": f"{name} was not recorded in this fixture"}
        return copy.deepcopy(tools[name])
    return fetch


def install() -> None:
    """Point every tool at the active fixture and switch the caches off. Idempotent."""
    global _installed
    if _installed:
        return
    for name in list(orchestrator._TOOL_DISPATCH):
        orchestrator._TOOL_DISPATCH[name] = _serve(name)
    orchestrator.get_memoized_tool_data = lambda ticker, name: None
    orchestrator.set_memoized_tool_data = lambda ticker, name, data: None
    orchestrator.get_cached_tool_data = lambda ticker, names: {}
    orchestrator.set_cached_tool_data = lambda ticker, data: None
    _installed = True


def normalize_price(price: dict) -> dict:
    """Make the recorded "today" agree with the recorded quote.

    Fixtures are captured at 16:30 ET, before yfinance's daily history has that day's bar, so
    changes_pct["1d"] (and the significance verdict built on it) is the PREVIOUS day's move,
    while change_pct comes from the live quote. On 136 of the first 168 fixtures the two
    disagreed by more than half a point (TEAM: quote -16.15%, verdict built on -3.47%). Left
    alone, every model would be scored on contradictory data. The quote wins; longer horizons
    still end a day early, which shifts them slightly but doesn't contradict anything.
    """
    today = price.get("change_pct")
    changes = dict(price.get("changes_pct") or {})
    if today is None or not changes or abs(changes.get("1d", today) - today) <= 0.05:
        return price
    changes["1d"] = today
    fixed = {**price, "changes_pct": changes}
    assessment = _assess_moves(changes, price.get("realized_vol_annualized_pct"))
    if assessment:
        fixed["move_assessment"] = assessment
    return fixed


def fixture_tools(fixture: dict) -> dict:
    tools = dict(fixture["tools"])
    tools["get_price_data"] = normalize_price(tools["get_price_data"])
    return tools


async def replay(fixture: dict, query: str, provider: LLMProvider) -> dict[str, Any]:
    """One investigation over recorded data. Never raises: a failure is returned as a result."""
    install()
    token = _current_tools.set(fixture_tools(fixture))
    t0 = time.perf_counter()
    try:
        result = await orchestrator.run_explainer(fixture["ticker"], query, provider=provider)
    except Exception as exc:  # an API error is a finding about the model, not a crash
        result = {"status": "error", "error_message": f"{type(exc).__name__}: {exc}"}
    finally:
        _current_tools.reset(token)
    result["wall_ms"] = round((time.perf_counter() - t0) * 1000)
    return result
