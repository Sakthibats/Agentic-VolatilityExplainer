"""FastAPI app — the /v1 REST + SSE surface every frontend talks to.

The orchestrator is still synchronous (async refactor is Phase 2), so the SSE
endpoint bridges it: the investigation runs on a worker thread, progress labels
flow through a queue, and an async generator drains that queue into SSE events.
"""

from __future__ import annotations

import queue
import threading
import uuid

import anyio
from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from volatility_explainer import __version__
from volatility_explainer.api import service
from volatility_explainer.api.schemas import (
    AnalyzeRequest,
    ApiError,
    Guardrail,
    Health,
    InvestigationStarted,
    PriceHistory,
    PricePoint,
    Stat,
    Step,
    TickerStats,
)
from volatility_explainer.marketdata import (
    fetch_analyst_stats,
    fetch_price_history,
    fetch_quick_stats,
)

_QUEUE_DONE = object()

app = FastAPI(title="Agentic Market Explainer API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened to the frontend origin in Phase 4
    allow_methods=["*"],
    allow_headers=["*"],
)


def _session_id(header_value: str | None) -> str:
    return header_value or str(uuid.uuid4())


async def _analyze_event_stream(raw_query: str, session_id: str):
    """Run service.analyze on a thread; yield SSE events as progress arrives."""
    events: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            result = service.analyze(
                raw_query, session_id,
                on_step=lambda label: events.put(("step", Step(label=label))),
            )
            if result.status == "guardrail":
                events.put(("guardrail", Guardrail(message=result.error_message)))
            elif result.status == "error":
                events.put(("error", ApiError(message=result.error_message)))
            else:
                events.put(("result", result))
        except Exception as exc:  # service.analyze shouldn't raise, but never hang the stream
            events.put(("error", ApiError(message=str(exc))))
        finally:
            events.put(_QUEUE_DONE)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    started = False
    while True:
        item = await anyio.to_thread.run_sync(events.get)
        if item is _QUEUE_DONE:
            break
        name, payload = item
        # The ticker isn't known until the scope gate has run inside the worker, so
        # investigation_started is emitted lazily before the first real event.
        if not started and name in ("step", "result"):
            started = True
            first = InvestigationStarted(ticker="", query=raw_query, session_id=session_id)
            yield {"event": "investigation_started", "data": first.model_dump_json()}
        yield {"event": name, "data": payload.model_dump_json()}


@app.post("/v1/analyze")
def analyze(
    body: AnalyzeRequest,
    stream: bool = True,
    x_session_id: str | None = Header(default=None),
):
    session_id = _session_id(x_session_id)
    if stream:
        return EventSourceResponse(_analyze_event_stream(body.query, session_id))
    return service.analyze(body.query, session_id)


@app.get("/v1/tickers/{ticker}/history", response_model=PriceHistory)
def price_history(ticker: str, period: str = "6M") -> PriceHistory:
    df = fetch_price_history(ticker, period)
    points = [
        PricePoint(date=row.date.isoformat(), close=float(row.close))
        for row in df.itertuples(index=False)
    ]
    return PriceHistory(ticker=ticker.upper(), period=period, points=points)


@app.get("/v1/tickers/{ticker}/stats", response_model=TickerStats)
def ticker_stats(ticker: str) -> TickerStats:
    quick = [Stat(label=s.label, value=s.value, delta=s.delta) for s in fetch_quick_stats(ticker)]
    analyst = [Stat(label=s.label, value=s.value, delta=s.delta) for s in fetch_analyst_stats(ticker)]
    return TickerStats(ticker=ticker.upper(), quick=quick, analyst=analyst)


@app.get("/v1/health", response_model=Health)
def health() -> Health:
    return Health(version=__version__)
