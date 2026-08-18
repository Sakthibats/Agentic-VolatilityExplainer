"""Analysis service — scope gate, cache, orchestrator call, result shaping.

Port of the retired Streamlit pipeline (apps/ui/placeholders.run_analysis), with
presentation stripped out: this returns structured AnalysisResult data; rendering
(markdown, confidence icons, stub tiles) is the frontend's job now.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

from volatility_explainer.agent.orchestrator import run_explainer
from volatility_explainer.analytics.supabase_logger import log_query_background
from volatility_explainer.api.schemas import AnalysisResult, Citation, Hypothesis, Tile
from volatility_explainer.clients.redis_cache import (
    get_cached_final_answer,
    set_cached_final_answer,
)
from volatility_explainer.query import evaluate_query


def _shape_tiles(raw_tiles: list, ticker: str) -> list[Tile]:
    """Filter malformed model output defensively and coerce to schema objects.

    Tool-call arguments from the model aren't schema-validated server-side, so an
    occasional malformed entry (e.g. a string where a tile object was expected)
    can slip through — skip those rather than failing the run.
    """
    good = [t for t in raw_tiles if isinstance(t, dict) and t.get("summary")]
    if len(good) < len(raw_tiles):
        print(f"[run:{ticker}] skipped {len(raw_tiles) - len(good)} malformed tile(s) from model output")
    return [
        Tile(
            agent=t.get("agent", ""),
            title=t.get("title", ""),
            summary=t.get("summary", ""),
            reasoning=t.get("reasoning", ""),
            citations=[
                Citation(number=c.get("number", i + 1), source=c.get("source", "Source"), url=c["url"])
                for i, c in enumerate(t.get("citations", []))
                if isinstance(c, dict) and c.get("url")
            ],
        )
        for t in good
    ]


def _shape_hypotheses(raw: list, ticker: str) -> list[Hypothesis]:
    good = [h for h in raw if isinstance(h, dict) and h.get("hypothesis")]
    if len(good) < len(raw):
        print(f"[run:{ticker}] skipped {len(raw) - len(good)} malformed hypothesis/hypotheses from model output")
    shaped = []
    for idx, h in enumerate(good):
        conf = h.get("confidence")
        shaped.append(Hypothesis(
            rank=h.get("rank", idx + 1),
            hypothesis=h["hypothesis"],
            evidence=h.get("evidence", ""),
            confidence=conf if conf in ("high", "medium", "low") else "medium",
            caveat=h.get("caveat", ""),
        ))
    return shaped


async def analyze(
    raw_query: str,
    session_id: str,
    on_step: Callable[[str], None] | None = None,
    on_started: Callable[[str], None] | None = None,
    on_summary: Callable[[str], None] | None = None,
) -> AnalysisResult:
    """Run one investigation end to end: scope gate → cache → orchestrator → shaping.

    Never raises: failures come back as status "error" so API callers always get a
    well-formed AnalysisResult. Sync/network-bound helpers (scope gate, Redis) run on
    worker threads; the orchestrator itself is awaited natively.
    """
    decision = await asyncio.to_thread(evaluate_query, raw_query)
    if not decision.in_scope or not decision.ticker:
        return AnalysisResult(
            ticker=None, query=raw_query, status="guardrail",
            error_message=decision.message or "Out of scope.",
        )

    ticker, question = decision.ticker, decision.question
    if on_started:
        # Fired the moment the scope gate resolves a ticker — before any tool or
        # LLM work — so streaming clients can start loading chart/stats early.
        on_started(ticker)
    t0 = time.perf_counter()
    try:
        # The no-query path ("explain the recent price action") is generic by
        # construction, so a cache hit can skip tool fetch + LLM synthesis entirely.
        # A query-specific ask always runs fresh.
        result = None
        if not question:
            redis_t0 = time.perf_counter()
            result = await asyncio.to_thread(get_cached_final_answer, ticker)
            redis_elapsed = (time.perf_counter() - redis_t0) * 1000
            print(f"[redis]  final_answer lookup   {redis_elapsed:6.0f}ms  ({'hit' if result else 'miss'})")

        if result is None:
            result = await run_explainer(
                ticker, question, on_step=on_step, on_summary=on_summary
            )

            if not question and result.get("status") == "complete":
                # Write-back only serves a *future* request — run it off-thread rather
                # than blocking the response the user is waiting on.
                def _write_back(ticker=ticker, result=result) -> None:
                    wb_t0 = time.perf_counter()
                    set_cached_final_answer(ticker, result)
                    print(f"[redis]  write-back (async)    {(time.perf_counter() - wb_t0) * 1000:6.0f}ms")

                threading.Thread(target=_write_back, daemon=True).start()

        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[run:{ticker}] total {elapsed_ms:.0f}ms")
        log_query_background(
            anonymous_id=session_id, ticker=ticker, query=question,
            result=result, elapsed_ms=elapsed_ms,
        )

        status = result.get("status", "incomplete")
        return AnalysisResult(
            ticker=ticker,
            query=question,
            status=status if status in ("complete", "incomplete", "guardrail") else "incomplete",
            summary=result.get("summary", ""),
            tiles=_shape_tiles(result.get("tiles", []), ticker),
            hypotheses=_shape_hypotheses(result.get("hypotheses", []), ticker),
            cache_hits=result.get("cache_hits", []),
            error_message=result.get("error_message", ""),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[run:{ticker}] total {elapsed_ms:.0f}ms FAILED — {exc}")
        log_query_background(
            anonymous_id=session_id, ticker=ticker, query=question,
            result={"status": "error", "data": {}, "tiles": [], "hypotheses": []},
            elapsed_ms=elapsed_ms,
        )
        return AnalysisResult(
            ticker=ticker, query=question, status="error",
            error_message=f"Live data unavailable ({exc})",
        )
