"""API tests — routes, SSE event sequence, non-streaming variant, guardrail, health.

The orchestrator and query gate are mocked at the service module's seams; nothing
here touches the network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from volatility_explainer.api import service
from volatility_explainer.api.app import app

client = TestClient(app)

ORCH_RESULT = {
    "ticker": "AAPL",
    "data": {},
    "summary": "AAPL fell 4.1% — over 2x its normal daily swing.",
    "tiles": [
        {"agent": "price", "title": "Price Action", "summary": "Down 4.1%.", "reasoning": "Core move."},
        "malformed-tile-should-be-skipped",
    ],
    "hypotheses": [
        {"rank": 1, "hypothesis": "Supply-chain delay", "evidence": "Bloomberg",
         "confidence": "high", "caveat": "N/A"},
        {"not": "a hypothesis"},
    ],
    "status": "complete",
    "cache_hits": [],
}

IN_SCOPE = SimpleNamespace(in_scope=True, ticker="AAPL", question="why did AAPL drop?",
                           source="ticker_symbol", message="")
OUT_OF_SCOPE = SimpleNamespace(in_scope=False, ticker=None, question="bake a cake",
                               source=None, message="Stocks and ETFs only.")


def _patched(decision=IN_SCOPE, orch=None):
    return (
        patch.object(service, "evaluate_query", return_value=decision),
        patch.object(service, "run_explainer", side_effect=orch or (lambda t, q, on_step=None: ORCH_RESULT)),
        patch.object(service, "log_query_background", lambda **kw: None),
        patch.object(service, "get_cached_final_answer", lambda t: None),
    )


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    current_event = None
    for line in text.splitlines():
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and current_event:
            events.append((current_event, json.loads(line.split(":", 1)[1].strip())))
            current_event = None
    return events


def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_analyze_non_streaming_returns_shaped_result():
    p1, p2, p3, p4 = _patched()
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze?stream=false", json={"query": "why did AAPL drop?"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["ticker"] == "AAPL"
    assert body["summary"].startswith("AAPL fell 4.1%")
    # Malformed model output filtered out by the service shaping layer.
    assert len(body["tiles"]) == 1
    assert len(body["hypotheses"]) == 1


def test_analyze_sse_event_sequence():
    def orch_with_steps(ticker, query, on_step=None):
        if on_step:
            on_step("Pulling price data...")
            on_step("Scanning recent news headlines...")
        return ORCH_RESULT

    p1, p2, p3, p4 = _patched(orch=orch_with_steps)
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze", json={"query": "why did AAPL drop?"})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    names = [n for n, _ in events]
    assert names[0] == "investigation_started"
    assert names.count("step") == 2
    assert names[-1] == "result"
    result = events[-1][1]
    assert result["status"] == "complete" and result["ticker"] == "AAPL"


def test_analyze_sse_guardrail_event():
    p1, p2, p3, p4 = _patched(decision=OUT_OF_SCOPE)
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze", json={"query": "bake a cake"})
    events = _parse_sse(r.text)
    assert [n for n, _ in events] == ["guardrail"]
    assert events[0][1]["message"] == "Stocks and ETFs only."


def test_analyze_non_streaming_guardrail():
    p1, p2, p3, p4 = _patched(decision=OUT_OF_SCOPE)
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze?stream=false", json={"query": "bake a cake"})
    body = r.json()
    assert body["status"] == "guardrail"
    assert body["ticker"] is None
    assert body["error_message"] == "Stocks and ETFs only."


def test_analyze_orchestrator_failure_becomes_error_event():
    def boom(ticker, query, on_step=None):
        raise RuntimeError("anthropic down")

    p1, p2, p3, p4 = _patched(orch=boom)
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze", json={"query": "why did AAPL drop?"})
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert "anthropic down" in events[-1][1]["message"]


def test_analyze_empty_query_rejected():
    r = client.post("/v1/analyze", json={"query": ""})
    assert r.status_code == 422


def test_price_history_endpoint():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-07-24", "2026-07-25"]),
        "close": [211.5, 208.2],
    })
    with patch("volatility_explainer.api.app.fetch_price_history", return_value=df):
        r = client.get("/v1/tickers/aapl/history?period=1M")
    body = r.json()
    assert body["ticker"] == "AAPL"
    assert body["period"] == "1M"
    assert body["points"][0] == {"date": "2026-07-24T00:00:00", "close": 211.5}


def test_ticker_stats_endpoint():
    stat = SimpleNamespace(label="Last Price", value="$211.50", delta="+1.2%")
    with (
        patch("volatility_explainer.api.app.fetch_quick_stats", return_value=[stat]),
        patch("volatility_explainer.api.app.fetch_analyst_stats", return_value=[]),
    ):
        r = client.get("/v1/tickers/AAPL/stats")
    body = r.json()
    assert body["quick"] == [{"label": "Last Price", "value": "$211.50", "delta": "+1.2%"}]
    assert body["analyst"] == []
