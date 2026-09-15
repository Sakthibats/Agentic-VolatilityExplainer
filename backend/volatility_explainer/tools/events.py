"""Recent and upcoming market events — earnings, ex-dividend, and FOMC dates.

Three independent sources, fetched in parallel so the tool costs max(), not sum():

- yfinance Ticker.earnings_dates — REPORTED quarters: announcement timestamp, EPS
  estimate and actual. The beat/miss verdict is computed from these here, in code,
  before the model ever sees them, because "it reported two days ago and missed"
  answers "why did it move" far more often than "it reports next month" does.
- Finnhub /calendar/earnings — the UPCOMING report. Preferred forward-looking because
  it carries the session timing (bmo/amc) and the fiscal quarter label. It is now
  forward-only: the free tier answers 200 with an empty list for any past window, so
  epsActual never arrives from here any more — hence earnings_dates above.
- yfinance Ticker.calendar — the ex-dividend date (a mechanical gap-down that is not a
  news catalyst and must not be mistaken for one), and a last-resort earnings date when
  both sources above come up empty.

Each source is wrapped separately: one failing degrades that field alone and is logged,
never silently swallowing the others' results too. A source that did not answer is held
distinct from one that answered "nothing" — see `earnings_status`.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from volatility_explainer.config import get_settings

_logger = logging.getLogger(__name__)

# FOMC meeting dates, from the Fed's published calendar. When this list runs low,
# tests/tools/test_events.py::test_fomc_calendar_has_runway fails on purpose —
# refresh from https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm rather
# than letting the tool silently stop reporting FOMC meetings.
_FOMC_DATES = [
    "2025-01-29",
    "2025-03-19",
    "2025-05-07",
    "2025-06-18",
    "2025-07-30",
    "2025-09-17",
    "2025-10-29",
    "2025-12-10",
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
    "2027-01-27",
    "2027-03-17",
    "2027-04-28",
    "2027-06-09",
    "2027-07-28",
    "2027-09-15",
    "2027-10-27",
    "2027-12-08",
]

# How far back to look for an already-reported quarter, and how far forward for the next
# one. 45 days back covers a full reporting cycle's aftermath without dragging in the
# prior quarter; 90 forward reaches the next scheduled report for any ticker.
_EARNINGS_LOOKBACK_DAYS = 45
_EARNINGS_LOOKAHEAD_DAYS = 90

# EPS surprises inside this band are rounding, not a beat or a miss.
_IN_LINE_PCT = 1.0

# Yahoo timestamps the announcement; Finnhub dates the calendar entry. They routinely
# disagree by a day for the same report (AAPL Q4 2026: Finnhub 10-28, Yahoo 10-29), so
# dates this close are merged as one report rather than reported as two.
_SAME_REPORT_TOLERANCE_DAYS = 3

_HOUR_PHRASE = {"bmo": "before the open", "amc": "after the close", "dmh": "during the session"}


def _today() -> date:
    """Indirection so tests can freeze the clock without mocking out the date class
    itself — the parsing here needs the real date type for isinstance/fromisoformat."""
    return date.today()


def _surprise(eps_actual: float | None, eps_estimate: float | None) -> tuple[str | None, float | None]:
    """Deterministic beat/miss verdict — decided here so the model never has to eyeball
    two floats and decide for itself. Returns (verdict, surprise_pct)."""
    if eps_actual is None or eps_estimate is None or not eps_estimate:
        return None, None
    pct = round((eps_actual - eps_estimate) / abs(eps_estimate) * 100, 1)
    verdict = "in line" if abs(pct) < _IN_LINE_PCT else "beat" if pct > 0 else "miss"
    return verdict, pct


def _describe_earnings(ticker: str, entry: dict, reported: bool) -> str:
    """One plain-English sentence a beginner can read, built from real numbers."""
    quarter = entry.get("quarter")
    year = entry.get("year")
    label = f"Q{quarter} {year}" if quarter and year else "quarterly"
    timing = _HOUR_PHRASE.get((entry.get("hour") or "").lower())

    if not reported:
        when = f" ({timing})" if timing else ""
        return f"{ticker} {label} earnings scheduled{when}"

    verdict, pct = _surprise(entry.get("epsActual"), entry.get("epsEstimate"))
    when = f" {timing}" if timing else ""
    if verdict is None:
        return f"{ticker} reported {label} earnings{when}"
    return (
        f"{ticker} reported {label} earnings{when} — EPS {entry['epsActual']} vs "
        f"{entry['epsEstimate']} expected ({verdict}, {pct:+}%)"
    )


def _earnings_event(ticker: str, entry: dict, today: date, source: str) -> dict | None:
    """Normalize one Finnhub earnings-calendar entry into an event dict."""
    try:
        when = date.fromisoformat(str(entry["date"])[:10])
    except (KeyError, TypeError, ValueError):
        return None

    reported = when < today
    event = {
        "type": "earnings",
        "date": when.isoformat(),
        "description": _describe_earnings(ticker, entry, reported),
        "source": source,
    }
    if reported:
        event["days_ago"] = (today - when).days
        verdict, pct = _surprise(entry.get("epsActual"), entry.get("epsEstimate"))
        event["eps_actual"] = entry.get("epsActual")
        event["eps_estimate"] = entry.get("epsEstimate")
        event["surprise"] = verdict
        event["surprise_pct"] = pct
    else:
        event["days_until"] = (when - today).days
        event["eps_estimate"] = entry.get("epsEstimate")
    if entry.get("hour"):
        event["hour"] = entry["hour"]
    return event


def _fetch_earnings_finnhub(ticker: str, today: date) -> list[dict] | None:
    """Raw Finnhub earnings entries in [today-45d, today+90d].

    Returns None when Finnhub is unconfigured (so the caller knows to fall back) or a
    list — possibly empty, which legitimately means "this ticker has no earnings".
    """
    settings = get_settings()
    if not settings.finnhub_api_key.get_secret_value():
        return None
    from volatility_explainer.clients.finnhub import FinnhubClient

    return FinnhubClient(settings).get_earnings_calendar(
        ticker,
        from_date=(today - timedelta(days=_EARNINGS_LOOKBACK_DAYS)).isoformat(),
        to_date=(today + timedelta(days=_EARNINGS_LOOKAHEAD_DAYS)).isoformat(),
    )


def _fetch_yf_earnings_dates(ticker: str):
    """yfinance Ticker.earnings_dates — a DataFrame indexed by announcement timestamp
    (tz-aware, exchange local) with 'EPS Estimate', 'Reported EPS' and 'Surprise(%)'.

    The only remaining source of a reported quarter's ACTUAL EPS. Requires lxml, which
    yfinance uses to parse this surface. Returns None when the ticker has no earnings
    surface at all — yfinance logs "no earnings dates found" and hands back None for
    ETFs rather than raising.
    """
    import yfinance as yf

    frame = yf.Ticker(ticker).earnings_dates
    if frame is None or frame.empty:
        return None
    return frame


def _hour_code(timestamp) -> str | None:
    """Map an announcement time to Finnhub's bmo/amc/dmh vocabulary, so both sources
    describe timing the same way. Midnight means Yahoo has no time, only a date."""
    hour, minute = timestamp.hour, timestamp.minute
    if hour == 0 and minute == 0:
        return None
    if (hour, minute) < (9, 30):
        return "bmo"
    if hour >= 16:
        return "amc"
    return "dmh"


def _earnings_from_yf_earnings_dates(ticker: str, frame, today: date) -> list[dict]:
    """Normalize the earnings_dates frame into event dicts, limited to the same window
    the Finnhub query uses. Rows with a 'Reported EPS' are past reports; rows without
    are scheduled ones."""
    if frame is None:
        return []

    import pandas as pd

    events: list[dict] = []
    for timestamp, row in frame.iterrows():
        when = timestamp.date()
        delta = (when - today).days
        if delta < -_EARNINGS_LOOKBACK_DAYS or delta > _EARNINGS_LOOKAHEAD_DAYS:
            continue

        actual = row.get("Reported EPS")
        estimate = row.get("EPS Estimate")
        entry = {
            "epsActual": None if pd.isna(actual) else float(actual),
            "epsEstimate": None if pd.isna(estimate) else float(estimate),
            "hour": _hour_code(timestamp),
        }
        event = _earnings_event(ticker, {**entry, "date": when.isoformat()}, today, "yfinance")
        if event is not None:
            events.append(event)
    return events


def _same_report(a: dict, b: dict) -> bool:
    gap = date.fromisoformat(a["date"]) - date.fromisoformat(b["date"])
    return abs(gap.days) <= _SAME_REPORT_TOLERANCE_DAYS


def _merge_reports(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """Combine two earnings-event lists, treating near-identical dates as one report.

    `primary` wins a collision, with one exception: an entry carrying eps_actual always
    beats one without it. That is what lets Finnhub own the upcoming report (it has the
    session timing and quarter label) while yfinance owns the reported one (it is the
    only source left with the actual).
    """
    merged = list(primary)
    for candidate in secondary:
        match = next((e for e in merged if _same_report(e, candidate)), None)
        if match is None:
            merged.append(candidate)
        elif match.get("eps_actual") is None and candidate.get("eps_actual") is not None:
            merged[merged.index(match)] = candidate
    return merged


def _fetch_yf_calendar(ticker: str) -> dict:
    """yfinance Ticker.calendar — a dict since yfinance 0.2 (it was a DataFrame before;
    assuming the old shape is what silently broke this tool). Keys of interest:
    'Earnings Date' (list of date), 'Ex-Dividend Date' (date).

    Yahoo has no fundamentals for ETFs and funds, so this 404s for them — an expected
    outcome, not a failure.
    """
    import yfinance as yf

    cal = yf.Ticker(ticker).calendar
    return cal if isinstance(cal, dict) else {}


def _earnings_from_yf_calendar(ticker: str, cal: dict, today: date) -> dict | None:
    """Fallback next-earnings from the yfinance calendar dict. A one-date list is a
    confirmed date; two dates are Yahoo's estimated window, which we say out loud rather
    than passing off a guess as a scheduled date."""
    dates = [d for d in (cal.get("Earnings Date") or []) if isinstance(d, date)]
    upcoming = sorted(d for d in dates if d >= today)
    if not upcoming:
        return None

    when = upcoming[0]
    estimated = len(dates) > 1
    suffix = " (estimated window, not confirmed)" if estimated else ""
    return {
        "type": "earnings",
        "date": when.isoformat(),
        "days_until": (when - today).days,
        "description": f"{ticker} quarterly earnings scheduled{suffix}",
        "estimated": estimated,
        "source": "yfinance",
    }


def _ex_dividend_event(ticker: str, cal: dict, today: date) -> dict | None:
    """Ex-dividend date, past or upcoming. A stock opening ~the dividend lower on its
    ex-date is mechanical, not a catalyst — the model needs this to avoid inventing a
    news explanation for it."""
    when = cal.get("Ex-Dividend Date")
    if not isinstance(when, date):
        return None
    delta = (when - today).days
    if delta < -_EARNINGS_LOOKBACK_DAYS or delta > _EARNINGS_LOOKAHEAD_DAYS:
        return None

    event = {
        "type": "ex_dividend",
        "date": when.isoformat(),
        "source": "yfinance",
        "description": (
            f"{ticker} went ex-dividend — the price drops by roughly the dividend on this "
            "date mechanically, with no news behind it"
            if delta < 0
            else f"{ticker} goes ex-dividend — expect a mechanical price drop of roughly the dividend"
        ),
    }
    if delta < 0:
        event["days_ago"] = -delta
    else:
        event["days_until"] = delta
    return event


def _next_fomc(today: date) -> dict | None:
    for fomc_str in _FOMC_DATES:
        fomc_date = date.fromisoformat(fomc_str)
        if fomc_date >= today:
            return {
                "type": "fomc",
                "date": fomc_str,
                "days_until": (fomc_date - today).days,
                "description": "FOMC interest rate decision",
                "source": "static",
            }
    return None


def fetch_events(ticker: str) -> dict:
    """Return recent and upcoming earnings, ex-dividend, and FOMC dates for context.

    Split into `recent_events` (already happened — the catalyst check) and `events`
    (still ahead — the positioning check), because "reported 2 days ago" and "reports in
    2 days" lead to opposite conclusions and must never be conflated.
    """
    ticker = ticker.upper()
    today = _today()

    # Three independent sources — overlap them so the tool costs the slowest one, not all.
    with ThreadPoolExecutor(max_workers=3) as pool:
        finnhub_fut = pool.submit(_fetch_earnings_finnhub, ticker, today)
        yf_reported_fut = pool.submit(_fetch_yf_earnings_dates, ticker)
        yf_calendar_fut = pool.submit(_fetch_yf_calendar, ticker)

        try:
            finnhub_raw = finnhub_fut.result()
        except Exception:
            _logger.warning("[events:%s] finnhub earnings calendar failed", ticker, exc_info=True)
            finnhub_raw = None

        try:
            yf_earnings = yf_reported_fut.result()
        except Exception:
            _logger.warning("[events:%s] yfinance earnings_dates failed", ticker, exc_info=True)
            yf_earnings = None

        try:
            yf_calendar = yf_calendar_fut.result()
        except Exception:
            # Expected for ETFs/funds (Yahoo has no fundamentals for them); logged at
            # debug so a genuinely broken Yahoo doesn't drown in ETF noise. None rather
            # than {}, so "Yahoo never answered" stays distinct from "Yahoo said empty".
            _logger.debug("[events:%s] yfinance calendar unavailable", ticker, exc_info=True)
            yf_calendar = None

    finnhub_events = [
        event
        for event in (
            _earnings_event(ticker, entry, today, "finnhub") for entry in finnhub_raw or []
        )
        if event is not None
    ]
    # Finnhub leads — it carries the session timing and quarter label — but yfinance wins
    # any collision where it holds the actual EPS, which Finnhub no longer serves at all.
    earnings_events = _merge_reports(
        finnhub_events, _earnings_from_yf_earnings_dates(ticker, yf_earnings, today)
    )

    if not earnings_events:
        # Only now is the coarse calendar date worth having. Reached when Finnhub answered
        # an empty window as well as when it never answered: an empty Finnhub result is not
        # on its own evidence that the ticker has no earnings.
        fallback = _earnings_from_yf_calendar(ticker, yf_calendar or {}, today)
        if fallback is not None:
            earnings_events = [fallback]

    sources = sorted({event["source"] for event in earnings_events})
    earnings_source = "+".join(sources) if sources else None

    if finnhub_raw is None and yf_earnings is None and yf_calendar is None:
        # Nothing answered — we genuinely don't know, which is different from knowing
        # there are no earnings.
        earnings_status = "unavailable"
    elif not earnings_events:
        earnings_status = "none"
    elif any("days_ago" in e for e in earnings_events):
        earnings_status = "reported"
    else:
        earnings_status = "scheduled"

    ex_dividend = _ex_dividend_event(ticker, yf_calendar or {}, today)
    fomc = _next_fomc(today)

    candidates = [*earnings_events, ex_dividend, fomc]
    recent_events = [e for e in candidates if e and "days_ago" in e]
    events = [e for e in candidates if e and "days_until" in e]

    recent_events.sort(key=lambda e: e["days_ago"])  # most recent first
    events.sort(key=lambda e: e["days_until"])  # soonest first

    notes: list[str] = []
    if earnings_status == "none":
        notes.append(
            f"No earnings calendar for {ticker} — expected for an ETF or fund, not a data failure."
        )
    elif earnings_status == "unavailable":
        notes.append(f"Earnings dates could not be retrieved for {ticker}.")
    if fomc is None:
        notes.append("No upcoming FOMC date on file — the meeting calendar needs updating.")

    result = {
        "ticker": ticker,
        "as_of": today.isoformat(),
        "events": events,
        "recent_events": recent_events,
        "earnings_status": earnings_status,
    }
    if earnings_source:
        result["earnings_source"] = earnings_source
    if notes:
        result["notes"] = notes
    return result
