"""FastAPI app — the /v1 REST + SSE surface every frontend talks to.

The investigation runs as an independent asyncio task; SSE events flow through a
queue so a client disconnect never cancels the underlying run (finish-and-cache).
"""

from __future__ import annotations

import asyncio
import uuid

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
    SummaryProgress,
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
    """Yield SSE events while the investigation runs as an independent task.

    The task is deliberately NOT tied to this generator's lifetime: if the client
    disconnects mid-run, sse-starlette cancels the generator but the investigation
    finishes anyway — the work is already paid for, and completing it means the
    result lands in the final-answer/tool caches for the next request.
    """
    events: asyncio.Queue = asyncio.Queue()

    async def runner() -> None:
        try:
            result = await service.analyze(
                raw_query, session_id,
                on_step=lambda label: events.put_nowait(("step", Step(label=label))),
                on_summary=lambda text: events.put_nowait(
                    ("summary", SummaryProgress(text=text))
                ),
                on_started=lambda ticker: events.put_nowait((
                    "investigation_started",
                    InvestigationStarted(ticker=ticker, query=raw_query, session_id=session_id),
                )),
            )
            if result.status == "guardrail":
                events.put_nowait(("guardrail", Guardrail(message=result.error_message)))
            elif result.status == "error":
                events.put_nowait(("error", ApiError(message=result.error_message)))
            else:
                events.put_nowait(("result", result))
        except Exception as exc:  # service.analyze shouldn't raise, but never hang the stream
            events.put_nowait(("error", ApiError(message=str(exc))))
        finally:
            events.put_nowait(_QUEUE_DONE)

    task = asyncio.create_task(runner())
    task.add_done_callback(lambda t: t.exception())  # retrieve, never re-raise

    while True:
        item = await events.get()
        if item is _QUEUE_DONE:
            break
        name, payload = item
        yield {"event": name, "data": payload.model_dump_json()}


@app.post("/v1/analyze")
async def analyze(
    body: AnalyzeRequest,
    stream: bool = True,
    x_session_id: str | None = Header(default=None),
):
    session_id = _session_id(x_session_id)
    if stream:
        return EventSourceResponse(_analyze_event_stream(body.query, session_id))
    return await service.analyze(body.query, session_id)


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
