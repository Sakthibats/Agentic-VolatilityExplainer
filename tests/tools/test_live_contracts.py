"""Upstream response-SHAPE contracts. Network required — excluded from the default run.

    pytest -m live

Every other test in this suite mocks its data source, which means none of them can catch
the failure that actually bit us: yfinance changed `Ticker.calendar` from a DataFrame to a
dict, `fetch_events` kept asking for `.empty`, the broad `except` swallowed the
AttributeError, and the tool returned a hardcoded FOMC date and nothing else — with a
fully green test suite the whole time.

These tests assert only the shapes our parsers depend on, never specific market values, so
they are stable day-to-day. Run them on a schedule and before widening any data-source
version pin. A failure here means an upstream contract moved: fix the parser, then update
the mocked tests to the new shape.

Transport failures are SKIPPED, not failed — see `_upstream_available`. A 503 says nothing
about the shape of a response that never arrived, and a canary that cries wolf every time
Finnhub's CDN hiccups is one nobody reads. Only a response that arrived and looked wrong
turns this red.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import httpx
import pandas as pd
import pytest
from volatility_explainer.config import get_settings

pytestmark = pytest.mark.live

# Upstream is flaky, not broken: Finnhub sits behind a CDN that intermittently answers
# with an HTML 503 page that never reached their API, and Yahoo rate-limits bursts.
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


@contextmanager
def _upstream_available(source: str):
    """Turn a transport failure into a skip, so only a real shape change fails the run.

    FinnhubClient already retries these internally; this catches what survives that.
    """
    try:
        yield
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status not in _TRANSIENT_STATUSES:
            raise
        pytest.skip(f"{source} returned HTTP {status} — upstream blip, not a contract change")
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        pytest.skip(f"{source} unreachable ({type(exc).__name__}) — not a contract change")


_TICKER = "AAPL"  # large, liquid, pays a dividend, has options and analyst coverage
_ETF = "SPY"  # no earnings — exercises the "legitimately absent" path


@pytest.fixture(scope="module")
def yf_ticker():
    import yfinance as yf

    return yf.Ticker(_TICKER)


def _require_finnhub():
    key = get_settings().finnhub_api_key.get_secret_value()
    if not key:
        pytest.skip("FINNHUB_API_KEY not configured")
    return key


# ── yfinance ──────────────────────────────────────────────────────────────────────


def test_yf_calendar_is_a_dict_with_date_values(yf_ticker):
    """The exact contract that broke. `calendar` must be a dict; 'Earnings Date' a list
    of real date objects; 'Ex-Dividend Date' a single date."""
    cal = yf_ticker.calendar

    assert isinstance(cal, dict), f"Ticker.calendar is now {type(cal)} — events.py parses a dict"
    assert "Earnings Date" in cal
    assert isinstance(cal["Earnings Date"], list)
    assert all(isinstance(d, date) for d in cal["Earnings Date"])
    assert isinstance(cal.get("Ex-Dividend Date"), date)


def test_yf_analyst_price_targets_shape(yf_ticker):
    """analyst.py reads current/mean/median/high/low. `median` in particular is why this
    replaced Ticker.info, which does not expose it."""
    targets = yf_ticker.analyst_price_targets

    assert isinstance(targets, dict)
    for key in ("current", "mean", "median", "high", "low"):
        assert isinstance(targets.get(key), (int, float)), f"{key} missing from price targets"


def test_yf_recommendations_shape(yf_ticker):
    """analyst.py reads the rating distribution per period, matched by the 'period' label
    ('0m', '-1m', ...) rather than row order."""
    frame = yf_ticker.recommendations

    assert not frame.empty
    for column in ("period", "strongBuy", "buy", "hold", "sell", "strongSell"):
        assert column in frame.columns
    periods = set(frame["period"])
    assert "0m" in periods
    assert periods & {"-1m", "-2m", "-3m"}, "no prior period — the consensus trend needs one"


def test_yf_upgrades_downgrades_shape(yf_ticker):
    """The dated-actions surface, and the reason this tool can speak to a recent move.
    Indexed by GradeDate; Action is one of the short codes analyst.py maps to labels."""
    frame = yf_ticker.upgrades_downgrades

    assert not frame.empty
    assert isinstance(frame.index, pd.DatetimeIndex)
    for column in ("Firm", "ToGrade", "FromGrade", "Action", "currentPriceTarget", "priorPriceTarget"):
        assert column in frame.columns
    assert set(frame["Action"].str.lower()) <= {"up", "down", "init", "main", "reit"}


def test_yf_info_has_sector(yf_ticker):
    """Key read by mcp/tools/sector.py to pick the comparison ETF."""
    assert yf_ticker.info.get("sector") == "Technology"


def test_yf_history_has_a_close_column(yf_ticker):
    """Frame shape read by price.py, macro.py, sector.py, marketdata/snapshots.py."""
    hist = yf_ticker.history(period="1mo")

    assert not hist.empty
    assert "Close" in hist.columns
    assert hist.index.year is not None  # DatetimeIndex — price.py's YTD slice needs it


def test_yf_news_items_carry_a_content_dict(yf_ticker):
    """news.py's yfinance fallback reads item['content']['title'] and nested url dicts."""
    raw = yf_ticker.news

    assert isinstance(raw, list) and raw
    content = raw[0].get("content")
    assert isinstance(content, dict)
    assert content.get("title")
    assert content.get("canonicalUrl", {}).get("url") or content.get("clickThroughUrl", {}).get("url")


def test_yf_options_chain_shape(yf_ticker):
    """options.py reads .options, .fast_info.last_price, and option_chain(exp).calls/.puts."""
    expirations = yf_ticker.options
    assert isinstance(expirations, tuple | list) and expirations

    spot = getattr(yf_ticker.fast_info, "last_price", None) or getattr(
        yf_ticker.fast_info, "previous_close", None
    )
    assert spot and spot > 0

    chain = yf_ticker.option_chain(expirations[0])
    for side in (chain.calls, chain.puts):
        assert not side.empty
        for column in ("strike", "impliedVolatility", "openInterest", "volume"):
            assert column in side.columns


def test_yf_earnings_dates_carries_reported_actuals(yf_ticker):
    """events.py's only remaining source of a REPORTED quarter's actual EPS, and so of the
    beat/miss verdict. Indexed by announcement timestamp; a past row must carry both an
    estimate and an actual. Had this existed, it would have caught Finnhub's calendar
    going forward-only the week it happened."""
    frame = yf_ticker.earnings_dates

    assert frame is not None and not frame.empty
    assert isinstance(frame.index, pd.DatetimeIndex)
    for column in ("EPS Estimate", "Reported EPS", "Surprise(%)"):
        assert column in frame.columns

    reported = frame[frame["Reported EPS"].notna()]
    assert not reported.empty, "no reported quarter — the beat/miss verdict has no input"
    assert reported["EPS Estimate"].notna().any(), "actuals with no estimate cannot be scored"
    # Announcement times, not bare dates — events.py derives bmo/amc from the clock.
    assert frame.index.tz is not None


def test_yf_earnings_dates_is_none_for_an_etf():
    """yfinance logs "no earnings dates found" and returns None rather than raising, so
    events.py must treat None as an expected absence, not a failure."""
    import yfinance as yf

    assert yf.Ticker(_ETF).earnings_dates is None


def test_yf_calendar_is_empty_for_an_etf():
    """Yahoo has no fundamentals for ETFs: it 404s, but yfinance logs that and hands back
    an empty dict rather than raising. events.py must therefore treat an empty calendar as
    an expected absence — it cannot rely on catching an exception here."""
    import yfinance as yf

    cal = yf.Ticker(_ETF).calendar

    assert cal == {}


# ── Finnhub ───────────────────────────────────────────────────────────────────────


def test_finnhub_earnings_calendar_shape():
    """The UPCOMING report: an ISO date, an estimate, and the session timing events.py
    turns into "before the open"/"after the close".

    Deliberately a forward window. The free tier answers 200 with an empty list for any
    past-dated query, so epsActual is unreachable here — reported quarters come from
    yfinance earnings_dates instead. Nothing asserts the past window stays empty: if
    Finnhub restores history that is good news, not a contract break.
    """
    _require_finnhub()
    from volatility_explainer.clients.finnhub import FinnhubClient

    today = date.today()
    with _upstream_available("finnhub /calendar/earnings"):
        entries = FinnhubClient(get_settings()).get_earnings_calendar(
            _TICKER,
            from_date=today.isoformat(),
            to_date=(today + timedelta(days=180)).isoformat(),
        )

    assert isinstance(entries, list) and entries
    entry = entries[0]
    assert date.fromisoformat(str(entry["date"])[:10])
    assert entry.get("epsEstimate") is not None
    assert entry.get("quarter") and entry.get("year")
    assert entry.get("hour") in {"bmo", "amc", "dmh", "", None}


def test_finnhub_earnings_calendar_is_empty_for_an_etf():
    """An ETF must come back as an empty list, not an error — that is what lets
    events.py report earnings_status 'none' instead of 'unavailable'."""
    _require_finnhub()
    from volatility_explainer.clients.finnhub import FinnhubClient

    today = date.today()
    with _upstream_available("finnhub /calendar/earnings"):
        entries = FinnhubClient(get_settings()).get_earnings_calendar(
            _ETF,
            from_date=today.isoformat(),
            to_date=(today + timedelta(days=180)).isoformat(),
        )

    assert entries == []


def test_finnhub_quote_shape():
    """price.py reads 'c' (current) and 'pc' (previous close)."""
    _require_finnhub()
    from volatility_explainer.clients.finnhub import FinnhubClient

    with _upstream_available("finnhub /quote"):
        quote = FinnhubClient(get_settings()).get_quote(_TICKER)

    assert quote.get("c")
    assert quote.get("pc")


def test_finnhub_company_news_shape():
    """news.py reads headline/summary/datetime/source/url off each item."""
    _require_finnhub()
    from volatility_explainer.clients.finnhub import FinnhubClient

    today = date.today()
    with _upstream_available("finnhub /company-news"):
        raw = FinnhubClient(get_settings()).get_company_news(
            _TICKER,
            from_date=(today - timedelta(days=7)).isoformat(),
            to_date=today.isoformat(),
        )

    assert isinstance(raw, list) and raw
    for key in ("headline", "summary", "datetime", "source", "url"):
        assert key in raw[0]


# ── End-to-end: the tool itself, unmocked ─────────────────────────────────────────
#
# These assert the VALUE the product promises, not merely that a key exists. The weaker
# form is what let the epsActual regression through: `earnings_status in {"reported",
# "scheduled"}` was satisfied by a scheduled date while the beat/miss verdict — the whole
# reason the tool reaches for earnings — had gone silently dead.


def _require_answer(result: dict, field: str, source: str) -> None:
    """Both tools report "unavailable" when no upstream answered. That is correct
    degradation, not a contract break, so it skips rather than fails."""
    if result.get(field) == "unavailable":
        pytest.skip(f"{source} did not answer ({field}=unavailable) — not a contract change")


def test_fetch_events_returns_a_scored_earnings_report(yf_ticker):
    """The regression guard, at full strength: a reported quarter must come back with a
    real actual EPS and a deterministic beat/miss verdict.

    The clock is frozen a few days after the most recent REAL announcement, read from
    live upstream data. Every data source stays unmocked — pinning the date only stops
    the test depending on where in the earnings cycle the Monday cron happens to land,
    which would otherwise leave it asserting nothing for half of each quarter.
    """
    from volatility_explainer.mcp.tools import events

    frame = yf_ticker.earnings_dates
    reported = frame[frame["Reported EPS"].notna()]
    assert not reported.empty, "no reported quarter upstream — see the earnings_dates test"
    as_of = reported.index.max().date() + timedelta(days=3)

    with patch.object(events, "_today", return_value=as_of):
        result = events.fetch_events(_TICKER)

    _require_answer(result, "earnings_status", "events")
    assert result["earnings_status"] == "reported"

    earnings = [e for e in result["recent_events"] if e["type"] == "earnings"]
    assert earnings, f"no reported earnings in {result['recent_events']}"
    latest = earnings[0]
    assert latest["eps_actual"] is not None, "the pre-rewrite failure mode: no actual EPS"
    assert latest["eps_estimate"] is not None
    assert latest["surprise"] in {"beat", "miss", "in line"}
    assert isinstance(latest["surprise_pct"], float)
    assert str(latest["eps_actual"]) in latest["description"]


def test_fetch_events_reports_no_earnings_for_an_etf():
    from volatility_explainer.mcp.tools.events import fetch_events

    result = fetch_events(_ETF)

    _require_answer(result, "earnings_status", "events")
    assert result["earnings_status"] == "none"
    assert any(e["type"] == "fomc" for e in result["events"])


def test_fetch_analyst_sentiment_returns_a_real_consensus():
    from volatility_explainer.mcp.tools.analyst import fetch_analyst_sentiment

    result = fetch_analyst_sentiment(_TICKER)

    _require_answer(result, "analyst_coverage", "analyst")
    assert result["analyst_coverage"] == "covered"
    assert result["consensus"]["analysts"] > 0
    assert 1.0 <= result["consensus"]["score"] <= 5.0
    assert result["price_target"]["median"] is not None


def test_fetch_analyst_sentiment_reports_no_coverage_for_an_etf():
    from volatility_explainer.mcp.tools.analyst import fetch_analyst_sentiment

    result = fetch_analyst_sentiment(_ETF)

    _require_answer(result, "analyst_coverage", "analyst")
    assert result["analyst_coverage"] == "none"
    assert "error" not in result
