"""Recent and upcoming market events — earnings via Finnhub (yfinance fallback),
ex-dividend via yfinance, FOMC from a maintained local calendar.

Two independent HTTP sources, fetched in parallel so the tool costs max(), not sum():

- Finnhub /calendar/earnings — the primary earnings source. Covers a window that starts
  in the PAST, because "it reported two days ago" answers "why did it move" far more
  often than "it reports next month" does. Past entries carry epsActual, so the
  beat/miss verdict is computed here, in code, before the model ever sees it.
- yfinance Ticker.calendar — the ex-dividend date (a mechanical gap-down that is not a
  news catalyst and must not be mistaken for one), and the earnings fallback when
  Finnhub is unconfigured or fails.

Each source is wrapped separately: one failing degrades that field alone and is logged,
never silently swallowing the other's result too.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from volatility_explainer.config import get_settings

_logger = logging.getLogger(__name__)

# FOMC meeting dates, from the Fed's published calendar. When this list runs low,
# tests/mcp/tools/test_events.py::test_fomc_calendar_has_runway fails on purpose —
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
]

# How far back to look for an already-reported quarter, and how far forward for the next
# one. 45 days back covers a full reporting cycle's aftermath without dragging in the
# prior quarter; 90 forward reaches the next scheduled report for any ticker.
_EARNINGS_LOOKBACK_DAYS = 45
_EARNINGS_LOOKAHEAD_DAYS = 90

# EPS surprises inside this band are rounding, not a beat or a miss.
_IN_LINE_PCT = 1.0

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

    # Two independent HTTP sources — overlap them so the tool costs the slower one, not both.
    with ThreadPoolExecutor(max_workers=2) as pool:
        finnhub_fut = pool.submit(_fetch_earnings_finnhub, ticker, today)
        yf_fut = pool.submit(_fetch_yf_calendar, ticker)

        try:
            finnhub_raw = finnhub_fut.result()
        except Exception:
            _logger.warning("[events:%s] finnhub earnings calendar failed", ticker, exc_info=True)
            finnhub_raw = None

        try:
            yf_calendar = yf_fut.result()
        except Exception:
            # Expected for ETFs/funds (Yahoo has no fundamentals for them); logged at
            # debug so a genuinely broken Yahoo doesn't drown in ETF noise.
            _logger.debug("[events:%s] yfinance calendar unavailable", ticker, exc_info=True)
            yf_calendar = {}

    earnings_events: list[dict] = []
    earnings_source: str | None = None

    if finnhub_raw is not None:
        normalized = (_earnings_event(ticker, entry, today, "finnhub") for entry in finnhub_raw)
        earnings_events = [e for e in normalized if e is not None]
        earnings_source = "finnhub"
    else:
        fallback = _earnings_from_yf_calendar(ticker, yf_calendar, today)
        if fallback is not None:
            earnings_events = [fallback]
            earnings_source = "yfinance"

    if earnings_source is None:
        # Neither source produced anything AND Finnhub never answered — we genuinely
        # don't know, which is different from knowing there are no earnings.
        earnings_status = "unavailable"
    elif not earnings_events:
        earnings_status = "none"
    elif any("days_ago" in e for e in earnings_events):
        earnings_status = "reported"
    else:
        earnings_status = "scheduled"

    ex_dividend = _ex_dividend_event(ticker, yf_calendar, today)
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
