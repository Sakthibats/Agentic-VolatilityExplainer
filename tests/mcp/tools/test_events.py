import datetime as real_datetime
from unittest.mock import MagicMock, patch

import pandas as pd
from volatility_explainer.mcp.tools import events


def _frozen_today(today: str):
    """Patch events.date so date.today() is fixed while fromisoformat/comparisons
    still behave like the real datetime.date."""
    patcher = patch("volatility_explainer.mcp.tools.events.date")
    mock_date = patcher.start()
    mock_date.today.return_value = real_datetime.date.fromisoformat(today)
    mock_date.fromisoformat.side_effect = real_datetime.date.fromisoformat
    return patcher


def test_earnings_read_from_calendar_when_present():
    patcher = _frozen_today("2026-07-01")
    try:
        cal = pd.DataFrame({"2026-08-01": [1]})
        yf_ticker = MagicMock(calendar=cal)
        with patch("yfinance.Ticker", return_value=yf_ticker):
            result = events.fetch_events("test")
    finally:
        patcher.stop()

    earnings = next(e for e in result["events"] if e["type"] == "earnings")
    assert earnings["date"] == "2026-08-01"
    assert earnings["days_until"] == 31
    assert result["ticker"] == "TEST"


def test_earnings_falls_back_to_earnings_dates_when_calendar_empty():
    patcher = _frozen_today("2026-07-01")
    try:
        ed = pd.DataFrame(
            {"EPS Estimate": [1, 2, 3]}, index=pd.DatetimeIndex(["2026-06-01", "2026-08-15", "2026-09-01"])
        )
        yf_ticker = MagicMock(calendar=pd.DataFrame(), earnings_dates=ed)
        with patch("yfinance.Ticker", return_value=yf_ticker):
            result = events.fetch_events("TEST")
    finally:
        patcher.stop()

    earnings = next(e for e in result["events"] if e["type"] == "earnings")
    # The nearest FUTURE date must win — 2026-06-01 is in the past and must be skipped.
    assert earnings["date"] == "2026-08-15"


def test_only_the_next_fomc_meeting_is_included():
    patcher = _frozen_today("2026-07-01")
    try:
        yf_ticker = MagicMock(calendar=pd.DataFrame())
        yf_ticker.earnings_dates = pd.DataFrame(index=pd.DatetimeIndex([]))
        with patch("yfinance.Ticker", return_value=yf_ticker):
            result = events.fetch_events("TEST")
    finally:
        patcher.stop()

    fomc_events = [e for e in result["events"] if e["type"] == "fomc"]
    assert len(fomc_events) == 1
    assert fomc_events[0]["date"] == "2026-07-29"
    assert fomc_events[0]["days_until"] == 28


def test_events_sorted_ascending_by_days_until():
    patcher = _frozen_today("2026-07-01")
    try:
        cal = pd.DataFrame({"2026-08-01": [1]})  # 31 days out, after the 07-29 FOMC (28 days out)
        yf_ticker = MagicMock(calendar=cal)
        with patch("yfinance.Ticker", return_value=yf_ticker):
            result = events.fetch_events("TEST")
    finally:
        patcher.stop()

    days = [e["days_until"] for e in result["events"]]
    assert days == sorted(days)
    assert result["events"][0]["type"] == "fomc"


def test_yfinance_exception_still_returns_fomc_events():
    patcher = _frozen_today("2026-07-01")
    try:
        with patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
            result = events.fetch_events("TEST")
    finally:
        patcher.stop()

    assert any(e["type"] == "fomc" for e in result["events"])
    assert not any(e["type"] == "earnings" for e in result["events"])
