import datetime as real_datetime
from unittest.mock import patch

import pytest
from volatility_explainer.mcp.tools import events


def _run(today: str, *, finnhub=None, yf_calendar=None):
    """Run fetch_events with the clock frozen and both upstream sources stubbed.

    finnhub: list of raw Finnhub earningsCalendar entries, or an Exception to raise, or
             None to simulate Finnhub being unconfigured (forces the yfinance fallback).
    yf_calendar: the dict yfinance's Ticker.calendar returns, or an Exception to raise.
    """

    def fake_finnhub(ticker, today_arg):
        if isinstance(finnhub, Exception):
            raise finnhub
        return finnhub

    def fake_yf(ticker):
        if isinstance(yf_calendar, Exception):
            raise yf_calendar
        return yf_calendar or {}

    with (
        patch.object(events, "_today", return_value=real_datetime.date.fromisoformat(today)),
        patch.object(events, "_fetch_earnings_finnhub", side_effect=fake_finnhub),
        patch.object(events, "_fetch_yf_calendar", side_effect=fake_yf),
    ):
        return events.fetch_events("test")


def _of_type(result: str, key: str, event_type: str):
    return [e for e in result[key] if e["type"] == event_type]


# ── Earnings via Finnhub (primary) ────────────────────────────────────────────────


def test_upcoming_earnings_from_finnhub():
    result = _run(
        "2026-07-01",
        finnhub=[{"date": "2026-08-01", "hour": "amc", "quarter": 3, "year": 2026, "epsEstimate": 1.5}],
    )

    earnings = _of_type(result, "events", "earnings")[0]
    assert earnings["date"] == "2026-08-01"
    assert earnings["days_until"] == 31
    assert result["earnings_status"] == "scheduled"
    assert result["earnings_source"] == "finnhub"
    assert result["ticker"] == "TEST"


def test_recently_reported_earnings_land_in_recent_events_with_beat_verdict():
    result = _run(
        "2026-07-01",
        finnhub=[
            {
                "date": "2026-06-28",
                "hour": "amc",
                "quarter": 2,
                "year": 2026,
                "epsEstimate": 2.0,
                "epsActual": 2.4,
            }
        ],
    )

    assert not _of_type(result, "events", "earnings")  # past — must not read as upcoming
    reported = _of_type(result, "recent_events", "earnings")[0]
    assert reported["days_ago"] == 3
    assert reported["surprise"] == "beat"
    assert reported["surprise_pct"] == 20.0
    assert result["earnings_status"] == "reported"
    assert "after the close" in reported["description"]


@pytest.mark.parametrize(
    ("actual", "estimate", "verdict", "pct"),
    [
        (2.4, 2.0, "beat", 20.0),
        (1.6, 2.0, "miss", -20.0),
        (2.0, 2.0, "in line", 0.0),
        (1.995, 2.0, "in line", -0.2),  # inside the rounding band — not a miss
        (-0.5, -1.0, "beat", 50.0),  # negative estimate: smaller loss is still a beat
    ],
)
def test_surprise_verdict_is_deterministic(actual, estimate, verdict, pct):
    assert events._surprise(actual, estimate) == (verdict, pct)


def test_surprise_is_none_when_either_side_missing():
    assert events._surprise(None, 2.0) == (None, None)
    assert events._surprise(2.0, None) == (None, None)
    assert events._surprise(2.0, 0) == (None, None)  # no dividing by a zero estimate


def test_both_past_and_future_earnings_are_split_across_the_two_buckets():
    result = _run(
        "2026-07-01",
        finnhub=[
            {"date": "2026-06-20", "quarter": 2, "year": 2026, "epsEstimate": 1.0, "epsActual": 1.1},
            {"date": "2026-09-20", "quarter": 3, "year": 2026, "epsEstimate": 1.2},
        ],
    )

    assert _of_type(result, "recent_events", "earnings")[0]["days_ago"] == 11
    assert _of_type(result, "events", "earnings")[0]["days_until"] == 81


# ── Earnings fallback via yfinance ────────────────────────────────────────────────


def test_falls_back_to_yfinance_calendar_dict_when_finnhub_unconfigured():
    # Ticker.calendar returns a DICT in yfinance >= 0.2 — the shape this tool must parse.
    result = _run(
        "2026-07-01",
        finnhub=None,
        yf_calendar={"Earnings Date": [real_datetime.date(2026, 8, 15)]},
    )

    earnings = _of_type(result, "events", "earnings")[0]
    assert earnings["date"] == "2026-08-15"
    assert earnings["days_until"] == 45
    assert earnings["estimated"] is False
    assert result["earnings_source"] == "yfinance"


def test_yfinance_fallback_flags_a_two_date_estimated_window():
    result = _run(
        "2026-07-01",
        finnhub=None,
        yf_calendar={
            "Earnings Date": [real_datetime.date(2026, 8, 15), real_datetime.date(2026, 8, 20)]
        },
    )

    earnings = _of_type(result, "events", "earnings")[0]
    assert earnings["estimated"] is True
    assert "not confirmed" in earnings["description"]


def test_yfinance_fallback_skips_past_dates_and_takes_the_nearest_future_one():
    result = _run(
        "2026-07-01",
        finnhub=None,
        yf_calendar={
            "Earnings Date": [
                real_datetime.date(2026, 6, 1),
                real_datetime.date(2026, 8, 15),
                real_datetime.date(2026, 9, 1),
            ]
        },
    )

    assert _of_type(result, "events", "earnings")[0]["date"] == "2026-08-15"


def test_finnhub_failure_falls_back_to_yfinance():
    result = _run(
        "2026-07-01",
        finnhub=RuntimeError("finnhub down"),
        yf_calendar={"Earnings Date": [real_datetime.date(2026, 8, 15)]},
    )

    assert result["earnings_source"] == "yfinance"
    assert _of_type(result, "events", "earnings")[0]["date"] == "2026-08-15"


# ── No-earnings vs. unknown-earnings ──────────────────────────────────────────────


def test_empty_finnhub_result_means_no_earnings_not_a_failure():
    """An ETF legitimately has no earnings — that must be distinguishable from a
    lookup that failed, or the model reads absence as ignorance."""
    result = _run("2026-07-01", finnhub=[], yf_calendar={})

    assert result["earnings_status"] == "none"
    assert "ETF or fund" in result["notes"][0]


def test_both_sources_unavailable_reports_unavailable():
    result = _run("2026-07-01", finnhub=RuntimeError("boom"), yf_calendar=RuntimeError("404"))

    assert result["earnings_status"] == "unavailable"
    assert "earnings_source" not in result
    assert any("could not be retrieved" in n for n in result["notes"])


def test_yfinance_failure_does_not_suppress_finnhub_earnings():
    """The two sources are wrapped separately — one exception must not take out the other
    (the single shared try/except is what silently killed this tool before)."""
    result = _run(
        "2026-07-01",
        finnhub=[{"date": "2026-08-01", "quarter": 3, "year": 2026, "epsEstimate": 1.5}],
        yf_calendar=RuntimeError("no fundamentals for ETF"),
    )

    assert _of_type(result, "events", "earnings")[0]["date"] == "2026-08-01"
    assert result["earnings_status"] == "scheduled"


# ── Ex-dividend ───────────────────────────────────────────────────────────────────


def test_recent_ex_dividend_is_reported_as_mechanical():
    result = _run(
        "2026-07-01",
        finnhub=[],
        yf_calendar={"Ex-Dividend Date": real_datetime.date(2026, 6, 28)},
    )

    ex_div = _of_type(result, "recent_events", "ex_dividend")[0]
    assert ex_div["days_ago"] == 3
    assert "mechanical" in ex_div["description"]


def test_upcoming_ex_dividend_goes_in_the_forward_bucket():
    result = _run(
        "2026-07-01",
        finnhub=[],
        yf_calendar={"Ex-Dividend Date": real_datetime.date(2026, 7, 10)},
    )

    assert _of_type(result, "events", "ex_dividend")[0]["days_until"] == 9


def test_far_away_ex_dividend_is_dropped_as_irrelevant():
    result = _run(
        "2026-07-01",
        finnhub=[],
        yf_calendar={"Ex-Dividend Date": real_datetime.date(2025, 1, 1)},
    )

    assert not _of_type(result, "recent_events", "ex_dividend")
    assert not _of_type(result, "events", "ex_dividend")


def test_missing_ex_dividend_is_simply_absent():
    result = _run("2026-07-01", finnhub=[], yf_calendar={"Earnings High": 2.0})

    assert not _of_type(result, "events", "ex_dividend")


# ── FOMC ──────────────────────────────────────────────────────────────────────────


def test_only_the_next_fomc_meeting_is_included():
    result = _run("2026-07-01", finnhub=[])

    fomc = _of_type(result, "events", "fomc")
    assert len(fomc) == 1
    assert fomc[0]["date"] == "2026-07-29"
    assert fomc[0]["days_until"] == 28


def test_exhausted_fomc_calendar_says_so_out_loud():
    """Past the end of _FOMC_DATES the tool must say the calendar needs updating rather
    than silently reporting no FOMC meetings forever."""
    result = _run("2099-01-01", finnhub=[])

    assert not _of_type(result, "events", "fomc")
    assert any("needs updating" in n for n in result["notes"])


def test_fomc_calendar_has_runway():
    """Fails ~90 days before _FOMC_DATES runs out, so the list gets refreshed from the
    Fed's published calendar before users start seeing a silent gap.

    To fix: add next year's dates from
    https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    """
    last = real_datetime.date.fromisoformat(events._FOMC_DATES[-1])
    days_left = (last - real_datetime.date.today()).days
    assert days_left > 90, (
        f"_FOMC_DATES ends {last.isoformat()} ({days_left} days away) — add the next "
        f"year's FOMC dates from federalreserve.gov"
    )


# ── Ordering ──────────────────────────────────────────────────────────────────────


def test_each_bucket_is_sorted_by_proximity_to_today():
    result = _run(
        "2026-07-01",
        finnhub=[
            {"date": "2026-08-01", "quarter": 3, "year": 2026, "epsEstimate": 1.0},  # +31
            {"date": "2026-06-10", "quarter": 2, "year": 2026, "epsEstimate": 1.0, "epsActual": 1.0},  # -21
        ],
        yf_calendar={"Ex-Dividend Date": real_datetime.date(2026, 6, 28)},  # -3
    )

    # Forward: FOMC (+28) before earnings (+31). Backward: ex-div (3) before earnings (21).
    assert [e["days_until"] for e in result["events"]] == [28, 31]
    assert [e["type"] for e in result["events"]] == ["fomc", "earnings"]
    assert [e["days_ago"] for e in result["recent_events"]] == [3, 21]
    assert [e["type"] for e in result["recent_events"]] == ["ex_dividend", "earnings"]


def test_malformed_finnhub_entry_is_skipped_not_fatal():
    result = _run(
        "2026-07-01",
        finnhub=[
            {"date": None, "quarter": 3, "year": 2026},
            {"date": "2026-08-01", "quarter": 3, "year": 2026, "epsEstimate": 1.0},
        ],
    )

    assert len(_of_type(result, "events", "earnings")) == 1
