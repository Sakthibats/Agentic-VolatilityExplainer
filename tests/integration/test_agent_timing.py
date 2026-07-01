"""Timing test for each agent tool call against ticker BE.

Run with:
    python -m pytest tests/integration/test_agent_timing.py -v -s

Or directly:
    python tests/integration/test_agent_timing.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import pytest

TICKER = "MRVL"


@dataclass
class TimingResult:
    name: str
    elapsed_ms: float
    success: bool
    error: str | None = None

    def __str__(self) -> str:
        status = "OK" if self.success else f"FAIL ({self.error})"
        return f"  {self.name:<35} {self.elapsed_ms:7.1f}ms  {status}"


def _time(name: str, fn: Callable) -> TimingResult:
    t0 = time.perf_counter()
    try:
        result = fn()
        elapsed = (time.perf_counter() - t0) * 1000
        error = result.get("error") if isinstance(result, dict) else None
        return TimingResult(name=name, elapsed_ms=elapsed, success=error is None, error=error)
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return TimingResult(name=name, elapsed_ms=elapsed, success=False, error=str(exc))


# ── individual tool tests ──────────────────────────────────────────────────────

def test_fetch_price_data():
    from volatility_explainer.mcp.tools.price import fetch_price_data

    r = _time("fetch_price_data", lambda: fetch_price_data(TICKER))
    print(f"\n{r}")
    assert r.success, f"fetch_price_data failed: {r.error}"
    assert r.elapsed_ms < 10_000, f"too slow: {r.elapsed_ms:.0f}ms"


def test_fetch_news():
    from volatility_explainer.mcp.tools.news import fetch_news

    r = _time("fetch_news", lambda: fetch_news(TICKER))
    print(f"\n{r}")
    assert r.success, f"fetch_news failed: {r.error}"
    assert r.elapsed_ms < 15_000, f"too slow: {r.elapsed_ms:.0f}ms"


def test_fetch_options_data():
    from volatility_explainer.mcp.tools.options import fetch_options_data

    r = _time("fetch_options_data", lambda: fetch_options_data(TICKER))
    print(f"\n{r}")
    assert r.success, f"fetch_options_data failed: {r.error}"
    assert r.elapsed_ms < 15_000, f"too slow: {r.elapsed_ms:.0f}ms"


def test_fetch_options_positioning():
    from volatility_explainer.mcp.tools.options import fetch_options_positioning

    r = _time("fetch_options_positioning", lambda: fetch_options_positioning(TICKER))
    print(f"\n{r}")
    assert r.success, f"fetch_options_positioning failed: {r.error}"
    assert r.elapsed_ms < 20_000, f"too slow: {r.elapsed_ms:.0f}ms"


def test_fetch_macro():
    from volatility_explainer.mcp.tools.macro import fetch_macro

    r = _time("fetch_macro", lambda: fetch_macro())
    print(f"\n{r}")
    assert r.success, f"fetch_macro failed: {r.error}"
    assert r.elapsed_ms < 10_000, f"too slow: {r.elapsed_ms:.0f}ms"


def test_fetch_events():
    from volatility_explainer.mcp.tools.events import fetch_events

    r = _time("fetch_events", lambda: fetch_events(TICKER))
    print(f"\n{r}")
    assert r.success, f"fetch_events failed: {r.error}"
    assert r.elapsed_ms < 10_000, f"too slow: {r.elapsed_ms:.0f}ms"


def test_full_orchestrator():
    """End-to-end run_explainer call — times the complete agent loop."""
    from volatility_explainer.agent.orchestrator import run_explainer

    steps: list[str] = []

    t0 = time.perf_counter()
    result = run_explainer(TICKER, on_step=steps.append)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"\n  {'run_explainer (full loop)':<35} {elapsed:7.1f}ms  status={result.get('status')}")
    if steps:
        print(f"  steps: {steps}")

    assert result.get("status") in {"complete", "guardrail"}, f"unexpected status: {result.get('status')}"
    assert elapsed < 120_000, f"orchestrator too slow: {elapsed:.0f}ms"


# ── summary runner (standalone) ───────────────────────────────────────────────

def _run_all_summary() -> None:
    """Print a timing table for every tool call when run as a script."""
    from volatility_explainer.mcp.tools.events import fetch_events
    from volatility_explainer.mcp.tools.macro import fetch_macro
    from volatility_explainer.mcp.tools.news import fetch_news
    from volatility_explainer.mcp.tools.options import fetch_options_data, fetch_options_positioning
    from volatility_explainer.mcp.tools.price import fetch_price_data
    from volatility_explainer.agent.orchestrator import run_explainer

    calls: list[tuple[str, Callable]] = [
        ("fetch_price_data",         lambda: fetch_price_data(TICKER)),
        ("fetch_news",               lambda: fetch_news(TICKER)),
        ("fetch_options_data",       lambda: fetch_options_data(TICKER)),
        ("fetch_options_positioning", lambda: fetch_options_positioning(TICKER)),
        ("fetch_macro",              lambda: fetch_macro()),
        ("fetch_events",             lambda: fetch_events(TICKER)),
    ]

    print(f"\n{'=' * 60}")
    print(f"  Agent tool timing — ticker: {TICKER}")
    print(f"{'=' * 60}")

    results: list[TimingResult] = []
    for name, fn in calls:
        r = _time(name, fn)
        results.append(r)
        print(r)

    print(f"\n  {'─' * 56}")
    total_serial = sum(r.elapsed_ms for r in results)
    print(f"  {'Total (serial)':<35} {total_serial:7.1f}ms")
    slowest = max(results, key=lambda r: r.elapsed_ms)
    print(f"  {'Slowest':<35} {slowest.name} ({slowest.elapsed_ms:.1f}ms)")
    failures = [r for r in results if not r.success]
    print(f"  {'Failures':<35} {len(failures)}/{len(results)}")

    print(f"\n{'─' * 60}")
    print("  Full orchestrator run (includes LLM turns)...")
    steps: list[str] = []
    t0 = time.perf_counter()
    orch_result = run_explainer(TICKER, on_step=steps.append)
    orch_ms = (time.perf_counter() - t0) * 1000
    print(f"  {'run_explainer':<35} {orch_ms:7.1f}ms  status={orch_result.get('status')}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    _run_all_summary()
