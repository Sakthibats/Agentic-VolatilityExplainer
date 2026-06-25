"""Upcoming market events — earnings via yfinance, FOMC hardcoded."""

from __future__ import annotations

from datetime import date

# FOMC meeting dates for 2025 and 2026
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


def fetch_events(ticker: str) -> dict:
    """Return upcoming earnings and FOMC dates for context."""
    today = date.today()
    events: list[dict] = []

    # Earnings via yfinance
    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(ticker.upper())
        cal = yf_ticker.calendar
        if cal is not None and not cal.empty:
            # calendar is a DataFrame with columns as dates, index as metrics
            earnings_dates = []
            for col in cal.columns:
                try:
                    d = date.fromisoformat(str(col)[:10])
                    if d >= today:
                        earnings_dates.append(d)
                except ValueError:
                    pass
            if earnings_dates:
                next_earnings = min(earnings_dates)
                events.append({
                    "type": "earnings",
                    "date": next_earnings.isoformat(),
                    "days_until": (next_earnings - today).days,
                    "description": f"{ticker.upper()} quarterly earnings",
                })
    except Exception:
        # yfinance may fail for some tickers; continue without earnings
        pass

    # Also try earnings_dates attribute as fallback
    if not any(e["type"] == "earnings" for e in events):
        try:
            import yfinance as yf

            yf_ticker = yf.Ticker(ticker.upper())
            ed = yf_ticker.earnings_dates
            if ed is not None and not ed.empty:
                future_dates = [d.date() for d in ed.index if d.date() >= today]
                if future_dates:
                    next_earnings = min(future_dates)
                    events.append({
                        "type": "earnings",
                        "date": next_earnings.isoformat(),
                        "days_until": (next_earnings - today).days,
                        "description": f"{ticker.upper()} quarterly earnings",
                    })
        except Exception:
            pass

    # FOMC dates
    for fomc_str in _FOMC_DATES:
        fomc_date = date.fromisoformat(fomc_str)
        if fomc_date >= today:
            events.append({
                "type": "fomc",
                "date": fomc_str,
                "days_until": (fomc_date - today).days,
                "description": "FOMC interest rate decision",
            })
            break  # only include the next FOMC meeting

    events.sort(key=lambda e: e["days_until"])

    return {
        "ticker": ticker.upper(),
        "as_of": today.isoformat(),
        "events": events,
    }
