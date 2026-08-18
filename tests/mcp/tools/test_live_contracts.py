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
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from volatility_explainer.config import get_settings

pytestmark = pytest.mark.live

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


def test_yf_calendar_is_empty_for_an_etf():
    """Yahoo has no fundamentals for ETFs: it 404s, but yfinance logs that and hands back
    an empty dict rather than raising. events.py must therefore treat an empty calendar as
    an expected absence — it cannot rely on catching an exception here."""
    import yfinance as yf

    cal = yf.Ticker(_ETF).calendar

    assert cal == {}


# ── Finnhub ───────────────────────────────────────────────────────────────────────


def test_finnhub_earnings_calendar_shape():
    """The primary earnings source. Needs past entries to carry epsActual (the beat/miss
    verdict depends on it) and every entry to carry an ISO date."""
    _require_finnhub()
    from volatility_explainer.clients.finnhub import FinnhubClient

    today = date.today()
    entries = FinnhubClient(get_settings()).get_earnings_calendar(
        _TICKER,
        from_date=today.replace(year=today.year - 1).isoformat(),
        to_date=today.isoformat(),
    )

    assert isinstance(entries, list) and entries
    entry = entries[0]
    assert date.fromisoformat(str(entry["date"])[:10])
    assert entry.get("epsActual") is not None
    assert entry.get("epsEstimate") is not None
    assert entry.get("hour") in {"bmo", "amc", "dmh", "", None}


def test_finnhub_earnings_calendar_is_empty_for_an_etf():
    """An ETF must come back as an empty list, not an error — that is what lets
    events.py report earnings_status 'none' instead of 'unavailable'."""
    _require_finnhub()
    from volatility_explainer.clients.finnhub import FinnhubClient

    today = date.today()
    entries = FinnhubClient(get_settings()).get_earnings_calendar(
        _ETF,
        from_date=today.replace(year=today.year - 1).isoformat(),
        to_date=today.isoformat(),
    )

    assert entries == []


def test_finnhub_quote_shape():
    """price.py reads 'c' (current) and 'pc' (previous close)."""
    _require_finnhub()
    from volatility_explainer.clients.finnhub import FinnhubClient

    quote = FinnhubClient(get_settings()).get_quote(_TICKER)

    assert quote.get("c")
    assert quote.get("pc")


def test_finnhub_company_news_shape():
    """news.py reads headline/summary/datetime/source/url off each item."""
    _require_finnhub()
    from datetime import timedelta

    from volatility_explainer.clients.finnhub import FinnhubClient

    today = date.today()
    raw = FinnhubClient(get_settings()).get_company_news(
        _TICKER,
        from_date=(today - timedelta(days=7)).isoformat(),
        to_date=today.isoformat(),
    )

    assert isinstance(raw, list) and raw
    for key in ("headline", "summary", "datetime", "source", "url"):
        assert key in raw[0]


# ── End-to-end: the tool itself, unmocked ─────────────────────────────────────────


def test_fetch_events_returns_real_earnings_for_a_real_ticker():
    """The regression guard. Before the rewrite this returned FOMC and nothing else."""
    from volatility_explainer.mcp.tools.events import fetch_events

    result = fetch_events(_TICKER)

    assert result["earnings_status"] in {"reported", "scheduled"}
    all_events = result["events"] + result["recent_events"]
    assert any(e["type"] == "earnings" for e in all_events), (
        f"no earnings in {all_events} — the pre-rewrite failure mode"
    )


def test_fetch_events_reports_no_earnings_for_an_etf():
    from volatility_explainer.mcp.tools.events import fetch_events

    result = fetch_events(_ETF)

    assert result["earnings_status"] == "none"
    assert any(e["type"] == "fomc" for e in result["events"])


def test_fetch_analyst_sentiment_returns_a_real_consensus():
    from volatility_explainer.mcp.tools.analyst import fetch_analyst_sentiment

    result = fetch_analyst_sentiment(_TICKER)

    assert result["analyst_coverage"] == "covered"
    assert result["consensus"]["analysts"] > 0
    assert 1.0 <= result["consensus"]["score"] <= 5.0
    assert result["price_target"]["median"] is not None


def test_fetch_analyst_sentiment_reports_no_coverage_for_an_etf():
    from volatility_explainer.mcp.tools.analyst import fetch_analyst_sentiment

    result = fetch_analyst_sentiment(_ETF)

    assert result["analyst_coverage"] == "none"
    assert "error" not in result
