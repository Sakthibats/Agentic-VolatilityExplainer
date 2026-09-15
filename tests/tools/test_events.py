import datetime as real_datetime
from unittest.mock import patch

import pandas as pd
import pytest
from volatility_explainer.tools import events


def _reported_frame(rows):
    """Build the shape yfinance's Ticker.earnings_dates returns: a DataFrame indexed by
    tz-aware announcement timestamp, with estimate/actual/surprise columns.

    rows: (timestamp string, EPS Estimate, Reported EPS) — actual None for a scheduled row.
    """
    index = pd.DatetimeIndex([pd.Timestamp(ts, tz="America/New_York") for ts, _, _ in rows])
    return pd.DataFrame(
        {
            "EPS Estimate": [est for _, est, _ in rows],
            "Reported EPS": [act for _, _, act in rows],
            "Surprise(%)": [None for _ in rows],
        },
        index=index,
    )


def _run(today: str, *, finnhub=None, yf_calendar=None, yf_reported=None):
    """Run fetch_events with the clock frozen and all three upstream sources stubbed.

    finnhub: list of raw Finnhub earningsCalendar entries, or an Exception to raise, or
             None to simulate Finnhub being unconfigured (forces the yfinance fallbacks).
    yf_calendar: the dict yfinance's Ticker.calendar returns, or an Exception to raise.
    yf_reported: the DataFrame Ticker.earnings_dates returns (see _reported_frame), an
             Exception to raise, or None for a ticker with no earnings surface at all.
    """

    def fake_finnhub(ticker, today_arg):
        if isinstance(finnhub, Exception):
            raise finnhub
        return finnhub

    def fake_yf(ticker):
        if isinstance(yf_calendar, Exception):
            raise yf_calendar
        return yf_calendar or {}

    def fake_reported(ticker):
        if isinstance(yf_reported, Exception):
            raise yf_reported
        return yf_reported

    with (
        patch.object(events, "_today", return_value=real_datetime.date.fromisoformat(today)),
        patch.object(events, "_fetch_earnings_finnhub", side_effect=fake_finnhub),
        patch.object(events, "_fetch_yf_calendar", side_effect=fake_yf),
        patch.object(events, "_fetch_yf_earnings_dates", side_effect=fake_reported),
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


# ── Reported earnings via yfinance earnings_dates ─────────────────────────────────


def test_reported_quarter_and_beat_verdict_come_from_yfinance_earnings_dates():
    """The regression this source exists for. Finnhub's calendar went forward-only, so a
    quarter that has already reported — and its beat/miss verdict — can only come from
    earnings_dates. Before this, epsActual was unreachable and _surprise() always
    returned (None, None)."""
    result = _run(
        "2026-07-01",
        finnhub=[],
        yf_reported=_reported_frame([("2026-06-28 16:00", 2.0, 2.4)]),
    )

    reported = _of_type(result, "recent_events", "earnings")[0]
    assert reported["days_ago"] == 3
    assert reported["eps_actual"] == 2.4
    assert reported["eps_estimate"] == 2.0
    assert reported["surprise"] == "beat"
    assert reported["surprise_pct"] == 20.0
    assert reported["source"] == "yfinance"
    assert result["earnings_status"] == "reported"
    assert "after the close" in reported["description"]


def test_finnhub_supplies_the_upcoming_report_and_yfinance_the_reported_one():
    """The intended division of labour: each source contributes the half it still has."""
    result = _run(
        "2026-07-01",
        finnhub=[{"date": "2026-08-01", "hour": "bmo", "quarter": 3, "year": 2026, "epsEstimate": 1.5}],
        yf_reported=_reported_frame([
            ("2026-08-01 08:00", 1.5, None),  # same report Finnhub already described
            ("2026-06-28 16:00", 2.0, 2.4),
        ]),
    )

    assert _of_type(result, "events", "earnings")[0]["source"] == "finnhub"
    assert _of_type(result, "recent_events", "earnings")[0]["surprise"] == "beat"
    assert result["earnings_source"] == "finnhub+yfinance"


def test_the_same_report_dated_a_day_apart_is_not_reported_twice():
    """Yahoo timestamps the announcement, Finnhub dates the calendar entry, and they
    disagree by a day (AAPL Q4 2026: Finnhub 10-28, Yahoo 10-29). One report, one event."""
    result = _run(
        "2026-07-01",
        finnhub=[{"date": "2026-08-01", "hour": "amc", "quarter": 3, "year": 2026, "epsEstimate": 1.5}],
        yf_reported=_reported_frame([("2026-08-02 16:00", 1.5, None)]),
    )

    upcoming = _of_type(result, "events", "earnings")
    assert len(upcoming) == 1
    assert upcoming[0]["date"] == "2026-08-01"  # Finnhub wins: it has the quarter label


def test_a_yfinance_actual_beats_a_finnhub_entry_without_one():
    """Finnhub leads on collisions except when it would throw away the actual EPS."""
    result = _run(
        "2026-07-01",
        finnhub=[{"date": "2026-06-28", "quarter": 2, "year": 2026, "epsEstimate": 2.0}],
        yf_reported=_reported_frame([("2026-06-28 16:00", 2.0, 1.6)]),
    )

    reported = _of_type(result, "recent_events", "earnings")[0]
    assert reported["eps_actual"] == 1.6
    assert reported["surprise"] == "miss"


def test_earnings_dates_rows_outside_the_window_are_dropped():
    result = _run(
        "2026-07-01",
        finnhub=[],
        yf_reported=_reported_frame([
            ("2026-01-28 16:00", 2.0, 2.1),  # 154 days ago — well past the lookback
            ("2027-01-28 16:00", 2.0, None),  # 211 days out — past the lookahead
        ]),
    )

    assert not _of_type(result, "recent_events", "earnings")
    assert not _of_type(result, "events", "earnings")
    assert result["earnings_status"] == "none"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-06-28 08:00", "bmo"),
        ("2026-06-28 16:00", "amc"),
        ("2026-06-28 12:30", "dmh"),
        ("2026-06-28 09:30", "dmh"),  # the open itself is during the session
        ("2026-06-28 00:00", None),  # Yahoo has a date but no time
    ],
)
def test_announcement_time_maps_to_the_finnhub_session_vocabulary(timestamp, expected):
    assert events._hour_code(pd.Timestamp(timestamp)) == expected


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


def test_empty_finnhub_window_still_consults_yfinance_before_concluding_none():
    """An empty Finnhub window is not evidence that a ticker has no earnings — it is now
    the normal answer for any past-dated query. Concluding "none" from it alone told a
    real stock's user "expected for an ETF or fund"."""
    result = _run(
        "2026-07-01",
        finnhub=[],
        yf_calendar={"Earnings Date": [real_datetime.date(2026, 8, 15)]},
    )

    assert result["earnings_status"] == "scheduled"
    assert result["earnings_source"] == "yfinance"
    assert _of_type(result, "events", "earnings")[0]["date"] == "2026-08-15"


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
