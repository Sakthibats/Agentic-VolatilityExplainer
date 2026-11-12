"""Analysis service — scope gate, cache, orchestrator call, result shaping.

Returns structured AnalysisResult data; rendering (markdown, confidence icons) is the
frontend's job.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

from volatility_explainer.agent.orchestrator import run_explainer
from volatility_explainer.analytics.supabase_logger import log_query_background
from volatility_explainer.api.schemas import (
    AnalysisResult,
    Citation,
    Hypothesis,
    ModelCatalog,
    ModelOption,
    Tile,
)
from volatility_explainer.clients.redis_cache import (
    get_cached_final_answer,
    set_cached_final_answer,
)
from volatility_explainer.config import get_settings
from volatility_explainer.llm import get_provider, is_configured
from volatility_explainer.query import evaluate_query

_PROVIDER_LABELS = {"anthropic": "Claude", "openai": "OpenAI"}
_FAILED_MESSAGE = (
    "The investigation couldn't finish (a data source or the model failed). Please try again."
)


def model_catalog() -> ModelCatalog:
    """The vendors a user can pick, with the model each runs here. OpenAI first: it is the
    picker's default. Model IDs come from settings, so the UI never hard-codes them."""
    settings = get_settings()
    return ModelCatalog(options=[
        ModelOption(
            provider="openai", vendor="OpenAI", model=settings.openai_model,
            reasoning_effort=settings.openai_reasoning_effort,
            available=is_configured(settings, "openai"),
        ),
        ModelOption(
            provider="anthropic", vendor="Anthropic", model=settings.anthropic_model,
            available=is_configured(settings, "anthropic"),
        ),
    ])


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
            citations=_shape_citations(t.get("citations", [])),
        )
        for t in good
    ]


def _shape_citations(raw: list) -> list[Citation]:
    return [
        Citation(number=c.get("number", i + 1), source=c.get("source", "Source"), url=c["url"])
        for i, c in enumerate(raw if isinstance(raw, list) else [])
        if isinstance(c, dict) and c.get("url")
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
    on_overview: Callable[[str], None] | None = None,
    provider_name: str | None = None,
) -> AnalysisResult:
    """Run one investigation end to end: scope gate → cache → orchestrator → shaping.

    `provider_name` picks the vendor that runs the loop ("anthropic" | "openai"); None means
    the server default, LLM_PROVIDER. Never raises: failures come back as status "error" so
    API callers always get a well-formed AnalysisResult. Sync/network-bound helpers (scope
    gate, Redis) run on worker threads; the orchestrator itself is awaited natively.
    """
    settings = get_settings()
    provider_name = provider_name or settings.llm_provider
    if not is_configured(settings, provider_name):
        # Checked up front, before any data is fetched: without a key the run can only fail,
        # and the SDK's own error ("api_key must be set") wouldn't tell the user what to do.
        label = _PROVIDER_LABELS.get(provider_name, repr(provider_name))
        return AnalysisResult(
            ticker=None, query=raw_query, status="error",
            error_message=f"{label} isn't set up on this server. Pick the other model and try again.",
        )

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
    provider = None
    try:
        provider = get_provider(settings, provider_name)
        # The no-query path ("explain the recent price action") is generic by
        # construction, so a cache hit can skip tool fetch + LLM synthesis entirely.
        # A query-specific ask always runs fresh. Cached per vendor, so switching models
        # never serves the other model's answer.
        result = None
        if not question:
            redis_t0 = time.perf_counter()
            result = await asyncio.to_thread(get_cached_final_answer, ticker, provider.name)
            redis_elapsed = (time.perf_counter() - redis_t0) * 1000
            print(f"[redis]  final_answer lookup   {redis_elapsed:6.0f}ms  ({'hit' if result else 'miss'})")

        if result is None:
            result = await run_explainer(
                ticker, question, provider=provider,
                on_step=on_step, on_summary=on_summary, on_overview=on_overview,
            )

            if not question and result.get("status") == "complete":
                # Write-back only serves a *future* request — run it off-thread rather
                # than blocking the response the user is waiting on.
                def _write_back(ticker=ticker, result=result, vendor=provider.name) -> None:
                    wb_t0 = time.perf_counter()
                    set_cached_final_answer(ticker, vendor, result)
                    print(f"[redis]  write-back (async)    {(time.perf_counter() - wb_t0) * 1000:6.0f}ms")

                threading.Thread(target=_write_back, daemon=True).start()

        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[run:{ticker}] total {elapsed_ms:.0f}ms")
        log_query_background(
            anonymous_id=session_id, ticker=ticker, query=raw_query.strip(),
            result=result, elapsed_ms=elapsed_ms,
            llm_provider=provider.name, llm_model=provider.model,
        )

        status = result.get("status", "incomplete")
        return AnalysisResult(
            ticker=ticker,
            query=raw_query.strip(),
            status=status if status in ("complete", "incomplete", "guardrail") else "incomplete",
            overview=result.get("overview", ""),  # absent from answers cached before it existed
            summary=result.get("summary", ""),
            citations=_shape_citations(result.get("citations", [])),
            tiles=_shape_tiles(result.get("tiles", []), ticker),
            hypotheses=_shape_hypotheses(result.get("hypotheses", []), ticker),
            cache_hits=result.get("cache_hits", []),
            error_message=result.get("error_message", ""),
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[run:{ticker}] total {elapsed_ms:.0f}ms FAILED — {type(exc).__name__}: {exc}")
        log_query_background(
            anonymous_id=session_id, ticker=ticker, query=raw_query.strip(),
            result={"status": "error", "data": {}, "tiles": [], "hypotheses": []},
            elapsed_ms=elapsed_ms,
            llm_provider=provider_name, llm_model=provider.model if provider else None,
        )
        return AnalysisResult(
            ticker=ticker, query=raw_query.strip(), status="error",
            # The exception stays in the server log: SDK and HTTP errors carry internals
            # (request IDs, upstream URLs) that mean nothing to a reader.
            error_message=_FAILED_MESSAGE,
        )
