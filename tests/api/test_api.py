"""API tests — routes, SSE event sequence, non-streaming variant, guardrail, health.

The orchestrator and query gate are mocked at the service module's seams; nothing
here touches the network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from volatility_explainer.api import service
from volatility_explainer.api.app import app

client = TestClient(app)

ORCH_RESULT = {
    "ticker": "AAPL",
    "data": {},
    "overview": "AAPL is at $100.00, down 4.1% today.",
    "summary": "AAPL fell 4.1% — over 2x its normal daily swing.",
    "citations": [
        {"number": 1, "source": "Bloomberg", "url": "https://bloom.example/1"},
        "malformed-citation-should-be-skipped",
    ],
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


def _fake_settings(*, default="anthropic", anthropic_key="a-key", openai_key="o-key"):
    def secret(value):
        return SimpleNamespace(get_secret_value=lambda: value)

    return SimpleNamespace(
        llm_provider=default,
        anthropic_api_key=secret(anthropic_key), anthropic_model="claude-haiku-4-5-20251001",
        openai_api_key=secret(openai_key), openai_model="gpt-6-luna", openai_reasoning_effort="low",
    )


@pytest.fixture(autouse=True)
def _both_vendors_configured():
    """Both API keys present (fake ones), so every test reaches the mocked orchestrator."""
    with patch.object(service, "get_settings", lambda: _fake_settings()):
        yield


def _patched(decision=IN_SCOPE, orch=None):
    orch_fn = orch or (lambda t, q, **callbacks: ORCH_RESULT)

    async def async_orch(t, q, **callbacks):
        return orch_fn(t, q, **callbacks)

    return (
        patch.object(service, "evaluate_query", return_value=decision),
        patch.object(service, "run_explainer", side_effect=async_orch),
        patch.object(service, "log_query_background", lambda **kw: None),
        patch.object(service, "get_cached_final_answer", lambda t, provider: None),
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
    assert body["citations"] == [
        {"number": 1, "source": "Bloomberg", "url": "https://bloom.example/1"},
    ]


def test_bare_ticker_is_served_from_the_final_answer_cache():
    # Regression: the gate used to return the raw text as the question, so even "AAPL"
    # skipped the cache — 0 of 319 production runs were ever served from it.
    bare = SimpleNamespace(**{**IN_SCOPE.__dict__, "question": ""})
    p1, p2, p3, _ = _patched(decision=bare)
    with p1, p2 as orch, p3, patch.object(service, "get_cached_final_answer", lambda t, provider: ORCH_RESULT):
        r = client.post("/v1/analyze?stream=false", json={"query": "AAPL"})
    body = r.json()
    assert body["status"] == "complete"
    assert body["query"] == "AAPL"
    orch.assert_not_called()


def test_analyze_sse_event_sequence():
    def orch_with_steps(ticker, query, on_step=None, **callbacks):
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
    assert events[0][1]["ticker"] == "AAPL"  # resolved ticker, emitted pre-tools
    assert names.count("step") == 2
    assert names[-1] == "result"
    result = events[-1][1]
    assert result["status"] == "complete" and result["ticker"] == "AAPL"


def test_analyze_sse_streams_summary_events_before_the_result():
    """The write-up is the longest step in a run; `summary` events carry it to the client
    as it is generated rather than after it lands."""
    def orch_with_summary(ticker, query, on_step=None, on_summary=None, on_overview=None, **_):
        if on_overview:
            on_overview(ORCH_RESULT["overview"])
        if on_step:
            on_step("Synthesizing findings...")
        if on_summary:
            on_summary("AAPL fell")
            on_summary("AAPL fell 4.1%")
        return ORCH_RESULT

    p1, p2, p3, p4 = _patched(orch=orch_with_summary)
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze", json={"query": "why did AAPL drop?"})

    events = _parse_sse(r.text)
    names = [n for n, _ in events]
    summaries = [payload["text"] for name, payload in events if name == "summary"]

    assert summaries == ["AAPL fell", "AAPL fell 4.1%"]
    # Cumulative, and always ahead of the terminal result.
    assert names.index("summary") < names.index("result")
    assert events[-1][1]["summary"].startswith("AAPL fell 4.1%")


def test_analyze_sse_sends_the_overview_before_the_explanation():
    """What happened (computed in code) reaches the reader before why (written by the model)."""
    def orch(ticker, query, on_summary=None, on_overview=None, **callbacks):
        on_overview(ORCH_RESULT["overview"])
        on_summary("A supply-chain delay")
        return ORCH_RESULT

    p1, p2, p3, p4 = _patched(orch=orch)
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze", json={"query": "why did AAPL drop?"})

    events = _parse_sse(r.text)
    names = [n for n, _ in events]
    assert names.count("overview") == 1
    assert names.index("overview") < names.index("summary") < names.index("result")
    assert events[names.index("overview")][1]["text"] == ORCH_RESULT["overview"]
    assert events[-1][1]["overview"] == ORCH_RESULT["overview"]


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
    def boom(ticker, query, **callbacks):
        raise RuntimeError("anthropic down")

    p1, p2, p3, p4 = _patched(orch=boom)
    with p1, p2, p3, p4:
        r = client.post("/v1/analyze", json={"query": "why did AAPL drop?"})
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    # The reader gets a plain retry message; the exception text stays in the server log.
    assert "anthropic down" not in events[-1][1]["message"]
    assert "try again" in events[-1][1]["message"]


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


async def test_client_disconnect_lets_investigation_finish():
    """Closing the SSE generator early (client disconnect) must NOT cancel the
    underlying investigation — it finishes so its result reaches the caches."""
    import asyncio

    from volatility_explainer.api import app as app_module
    from volatility_explainer.api.schemas import AnalysisResult

    finished = asyncio.Event()

    async def slow_analyze(q, sid, on_step=None, on_started=None, **callbacks):
        if on_started:
            on_started("AAPL")
        if on_step:
            on_step("Pulling price data...")
        await asyncio.sleep(0.05)
        finished.set()
        return AnalysisResult(ticker="AAPL", query=q, status="complete")

    with patch.object(app_module.service, "analyze", side_effect=slow_analyze):
        gen = app_module._analyze_event_stream("why did AAPL drop?", "sid-1")
        first = await gen.__anext__()
        assert first["event"] == "investigation_started"
        await gen.aclose()  # simulate the client disconnecting mid-stream
        await asyncio.wait_for(finished.wait(), timeout=2)  # investigation still completes


# ── Model choice (AnalyzeRequest.provider) ──────────────────────────────────


def _run_capturing_vendor(body: dict, decision=IN_SCOPE) -> tuple[dict, dict]:
    """POST body; return (response JSON, what the orchestrator and the cache were given)."""
    seen: dict = {}

    def orch(t, q, provider=None, **callbacks):
        seen["orchestrator"] = (provider.name, provider.model)
        return ORCH_RESULT

    def cache_lookup(t, provider):
        seen["cache"] = provider
        return None

    p1, p2, p3, _ = _patched(decision=decision, orch=orch)
    with p1, p2, p3, patch.object(service, "get_cached_final_answer", cache_lookup), \
            patch.object(service, "set_cached_final_answer", lambda *a: None):
        r = client.post("/v1/analyze?stream=false", json=body)
    return r.json(), seen


def test_the_requested_vendor_runs_the_investigation():
    body, seen = _run_capturing_vendor({"query": "why did AAPL drop?", "provider": "openai"})

    assert body["status"] == "complete"
    assert seen["orchestrator"] == ("openai", "gpt-6-luna")  # the model stays server config


def test_no_vendor_in_the_request_means_the_server_default():
    _, seen = _run_capturing_vendor({"query": "why did AAPL drop?"})

    assert seen["orchestrator"] == ("anthropic", "claude-haiku-4-5-20251001")


def test_the_final_answer_cache_is_looked_up_for_the_chosen_vendor():
    bare = SimpleNamespace(**{**IN_SCOPE.__dict__, "question": ""})
    _, seen = _run_capturing_vendor({"query": "AAPL", "provider": "openai"}, decision=bare)

    assert seen["cache"] == "openai"


def test_a_vendor_without_a_key_fails_fast_with_a_clear_message():
    settings = _fake_settings(openai_key="")
    p1, p2, p3, p4 = _patched()
    with p1 as gate, p2 as orch, p3, p4, patch.object(service, "get_settings", lambda: settings):
        r = client.post("/v1/analyze", json={"query": "why did AAPL drop?", "provider": "openai"})

    events = _parse_sse(r.text)
    assert [name for name, _ in events] == ["error"]
    assert "OpenAI isn't set up" in events[0][1]["message"]
    gate.assert_not_called()  # nothing fetched or resolved for a run that can't happen
    orch.assert_not_called()


def test_an_unknown_vendor_is_rejected():
    r = client.post("/v1/analyze", json={"query": "AAPL", "provider": "gemini"})

    assert r.status_code == 422


def test_models_lists_each_vendor_with_the_model_it_runs_here():
    body = client.get("/v1/models").json()

    assert body["options"] == [
        {"provider": "openai", "vendor": "OpenAI", "model": "gpt-6-luna",
         "reasoning_effort": "low", "available": True, "unavailable_reason": None},
        {"provider": "anthropic", "vendor": "Anthropic", "model": "claude-haiku-4-5-20251001",
         "reasoning_effort": None, "available": True, "unavailable_reason": None},
    ]


def test_models_marks_a_vendor_without_a_key_unavailable():
    with patch.object(service, "get_settings", lambda: _fake_settings(anthropic_key="")):
        options = client.get("/v1/models").json()["options"]

    assert {o["provider"]: o["available"] for o in options} == {"openai": True, "anthropic": False}
    assert {o["provider"]: o["unavailable_reason"] for o in options} == {
        "openai": None, "anthropic": "not_configured",
    }


@pytest.mark.parametrize("path", [
    "/v1/tickers/AAPL/history?period=5Y",       # not a chart period
    "/v1/tickers/not%20a%20ticker/history",     # free text never reaches yfinance
    "/v1/tickers/ABCDEFGHIJKLMNOP/stats",       # too long
])
def test_ticker_routes_reject_invalid_input(path):
    with patch("yfinance.Ticker", side_effect=AssertionError("must not reach yfinance")):
        assert client.get(path).status_code == 422


def test_ticker_routes_accept_index_and_class_share_symbols():
    df = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "close": pd.Series(dtype=float)})
    with patch("volatility_explainer.api.app.fetch_price_history", return_value=df):
        for symbol in ("^VIX", "BRK-B", "brk.b"):
            assert client.get(f"/v1/tickers/{symbol}/history?period=1M").status_code == 200


def test_an_oversized_session_id_is_rejected():
    r = client.post("/v1/analyze", json={"query": "AAPL"}, headers={"x-session-id": "x" * 65})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# The structured per-run log event (observability.py, service._log_run)
# ---------------------------------------------------------------------------

USAGE = {"turns": 2, "input_tokens": 900, "cache_read_tokens": 4000, "cache_write_tokens": 0,
         "output_tokens": 700, "reasoning_tokens": 0, "cost_usd": 0.0014, "llm_ms": 5200,
         "tool_ms": 600, "tool_rounds": [["get_news"]], "provider": "anthropic", "model": "m"}


def _run_events(caplog) -> list[dict]:
    return [r.fields for r in caplog.records if getattr(r, "fields", {}).get("event") == "run"]


def test_a_live_run_logs_one_event_with_cost_origin_and_no_query_text(caplog):
    result = {**ORCH_RESULT, "usage": USAGE, "quality_flags": [], "answer_repairs": ["ranks_rewritten"],
              "data": {"get_price_data": {}, "get_news": {}}, "cache_hits": ["get_price_data"]}
    p1, p2, p3, p4 = _patched(orch=lambda t, q, **cb: result)
    with p1, p2, p3, p4, caplog.at_level("INFO"):
        client.post("/v1/analyze?stream=false", json={"query": "why did AAPL drop?"},
                    headers={"Origin": "https://market-explainer.com"})

    [event] = _run_events(caplog)
    assert event["status"] == "complete"
    assert event["ticker"] == "AAPL" and event["provider"] == "anthropic"
    assert event["origin"] == "https://market-explainer.com"
    assert event["question"] is True and event["final_answer_cached"] is False
    assert event["cost_usd"] == 0.0014 and event["turns"] == 2 and event["output_tokens"] == 700
    assert event["tools"] == ["get_news", "get_price_data"]
    assert event["tools_cached"] == ["get_price_data"]
    assert event["answer_repairs"] == ["ranks_rewritten"]
    assert "why did AAPL drop" not in json.dumps(event)  # never the user's text (PRIVACY.md)


def test_an_answer_from_the_final_answer_cache_is_not_counted_as_spend(caplog):
    bare = SimpleNamespace(**{**IN_SCOPE.__dict__, "question": ""})
    p1, p2, p3, _ = _patched(decision=bare)
    cached = {**ORCH_RESULT, "usage": USAGE}
    with p1, p2, p3, patch.object(service, "get_cached_final_answer", lambda t, provider: cached), \
         caplog.at_level("INFO"):
        client.post("/v1/analyze?stream=false", json={"query": "AAPL"})

    [event] = _run_events(caplog)
    assert event["final_answer_cached"] is True
    assert "cost_usd" not in event and "turns" not in event


def test_guardrail_and_failed_runs_are_logged_too(caplog):
    p1, p2, p3, p4 = _patched(decision=OUT_OF_SCOPE)
    with p1, p2, p3, p4, caplog.at_level("INFO"):
        client.post("/v1/analyze?stream=false", json={"query": "bake a cake"})

    def boom(ticker, query, **callbacks):
        raise RuntimeError("anthropic down")

    p1, p2, p3, p4 = _patched(orch=boom)
    with p1, p2, p3, p4, caplog.at_level("INFO"):
        client.post("/v1/analyze?stream=false", json={"query": "why did AAPL drop?"})

    guardrail, failed = _run_events(caplog)
    assert guardrail["status"] == "guardrail" and "ticker" not in guardrail
    assert failed["status"] == "error" and failed["error"] == "RuntimeError"
    assert failed["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# A vendor account out of credits (llm.base.OutOfCredits)
# ---------------------------------------------------------------------------


def _out_of_credits(vendor="anthropic"):
    from volatility_explainer.llm.base import OutOfCredits

    def orch(ticker, query, **callbacks):
        raise OutOfCredits(vendor)

    return orch


def test_out_of_credits_tells_the_reader_to_switch_and_raises_one_alert(caplog):
    p1, p2, p3, p4 = _patched(orch=_out_of_credits())
    with p1, p2, p3, p4, caplog.at_level("INFO"):
        first = client.post("/v1/analyze?stream=false", json={"query": "why did AAPL drop?"}).json()
        second = client.post("/v1/analyze?stream=false", json={"query": "why did AAPL drop?"}).json()

    for body in (first, second):
        assert body["status"] == "error"
        assert "run out of Claude credits" in body["error_message"]
        assert "Switch to OpenAI" in body["error_message"]
    alerts = [r for r in caplog.records
              if getattr(r, "fields", {}).get("alert") == service.OUT_OF_CREDITS_ALERT]
    assert len(alerts) == 1 and alerts[0].levelname == "ERROR"
    assert alerts[0].fields["vendor"] == "anthropic"
    assert [e["error"] for e in _run_events(caplog)] == ["out_of_credits", "out_of_credits"]


def test_runs_on_an_empty_vendor_stop_before_any_work_until_the_cooldown_ends(monkeypatch):
    p1, p2, p3, p4 = _patched(orch=_out_of_credits())
    with p1, p2, p3, p4:
        client.post("/v1/analyze?stream=false", json={"query": "why did AAPL drop?"})

    with patch.object(service, "evaluate_query") as gate, \
         patch.object(service, "run_explainer") as orch:
        body = client.post("/v1/analyze?stream=false", json={"query": "AAPL"}).json()
    assert body["status"] == "error"
    gate.assert_not_called()   # no ticker lookup, no data fetch, no LLM call
    orch.assert_not_called()

    # The other vendor is unaffected, and the picker shows why Claude is off.
    options = {o["provider"]: o for o in client.get("/v1/models").json()["options"]}
    assert options["openai"]["available"] is True
    assert options["anthropic"]["available"] is False
    assert options["anthropic"]["unavailable_reason"] == "out_of_credits"

    # Topped up: after the cooldown the vendor is tried again.
    later = service.time.monotonic() + service._CREDITS_COOLDOWN_SECONDS + 1
    monkeypatch.setattr(service.time, "monotonic", lambda: later)
    assert {o["provider"]: o["available"] for o in client.get("/v1/models").json()["options"]} == {
        "openai": True, "anthropic": True,
    }
