"""get_price_data: quote, daily history, extended-hours trade, and the significance verdicts
built on them (computed in significance.py; this module only fetches and assembles)."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from volatility_explainer.config import get_settings
from volatility_explainer.significance import assess_moves, horizon_changes, realized_vol

_MARKET_TZ = ZoneInfo("America/New_York")
_REGULAR_OPEN, _REGULAR_CLOSE = time(9, 30), time(16, 0)

# How far yfinance's regular close may sit from the price this run reports for an extended-
# hours trade to be measured from it. A larger gap means the two describe different sessions.
_SAME_CLOSE_TOLERANCE = 0.01

# How far yfinance's last close may sit from the quote's previous close for the quote to be
# taken as the very next session. Wider than rounding because yfinance closes are
# dividend-adjusted; narrow enough that a history missing several days is not bridged.
_PREV_CLOSE_TOLERANCE = 0.02


def _with_todays_close(hist, quote: dict, ticker: str = ""):
    """yfinance's daily history with the live quote added as today's close, if it is missing.

    After the close, yfinance's history can still end at the PREVIOUS session while the quote
    already shows today's: every horizon change (and the significance verdict built on them)
    would then describe yesterday's move under today's headline number. On the first 168
    eval fixtures, recorded at 16:30 ET, 136 disagreed by more than half a point.

    The quote is added only when it is from a later trading day than the last bar (by the
    quote's own timestamp in New York time, so weekends, holidays and pre-market quotes,
    which still carry the last session's trade, add nothing) and its previous close matches
    that last bar. Otherwise the history is returned unchanged.
    """
    traded_at, price, prev_close = quote.get("t"), quote.get("price"), quote.get("prev_close")
    if hist is None or hist.empty or not traded_at or not price or not prev_close:
        return hist
    closes = hist["Close"].dropna()
    if closes.empty:
        return hist
    last_bar = closes.index[-1]
    quote_day = datetime.fromtimestamp(traded_at, tz=_MARKET_TZ).date()
    if quote_day <= last_bar.date():
        return hist
    if abs(float(closes.iloc[-1]) - prev_close) / prev_close > _PREV_CLOSE_TOLERANCE:
        print(f"[price:{ticker}]  history ends {last_bar.date()}, quote is {quote_day}, "
              f"but closes disagree ({float(closes.iloc[-1]):.2f} vs {prev_close:.2f}); not joined")
        return hist
    import pandas as pd

    today = pd.DataFrame({"Close": [float(price)]},
                         index=pd.DatetimeIndex([pd.Timestamp(quote_day, tz=last_bar.tz)]))
    return pd.concat([hist, today])


def _regular_hours(now: datetime | None = None) -> bool:
    """True on a weekday between 9:30 and 16:00 New York time. Holidays count as open; that
    only costs an extended-hours lookup that finds nothing."""
    now = (now or datetime.now(_MARKET_TZ)).astimezone(_MARKET_TZ)
    return now.weekday() < 5 and _REGULAR_OPEN <= now.time() < _REGULAR_CLOSE


def extended_hours(info, close: float | None) -> dict | None:
    """The latest pre- or post-market trade after the last regular session, from yfinance's
    `info`, with its % change from that session's close. None when there is none.

    Only a trade timestamped after the regular session's last trade counts, so during
    market hours yesterday's after-hours print is ignored, and from 20:00 until the next
    pre-market (and over a weekend) the last after-hours print is kept. It is reported
    beside the regular close, never in place of it: extended-hours trading is thin, and the
    horizon changes, realized vol and significance verdicts are all built on regular closes.
    """
    if not isinstance(info, dict) or not close:
        return None
    regular_price, regular_time = info.get("regularMarketPrice"), info.get("regularMarketTime")
    if not regular_price or not regular_time:
        return None
    if abs(regular_price - close) / close > _SAME_CLOSE_TOLERANCE:
        return None  # yfinance's regular session isn't the one this run reports

    latest = None
    for session, price_key, time_key in (("post", "postMarketPrice", "postMarketTime"),
                                         ("pre", "preMarketPrice", "preMarketTime")):
        price, traded_at = info.get(price_key), info.get(time_key)
        if price and traded_at and traded_at > regular_time and (
            latest is None or traded_at > latest[2]
        ):
            latest = (session, price, traded_at)
    if latest is None:
        return None
    session, price, traded_at = latest
    return {
        "session": session,
        "price": round(float(price), 2),
        "change_pct": round((price - close) / close * 100, 2),
        "as_of": datetime.fromtimestamp(traded_at, tz=_MARKET_TZ).strftime("%Y-%m-%d %H:%M ET"),
    }


def _session_date(quote: dict | None, info, hist) -> date | None:
    """The New York date of the regular session the reported price comes from."""
    for traded_at in ((quote or {}).get("t"), info.get("regularMarketTime") if isinstance(info, dict) else None):
        if traded_at:
            return datetime.fromtimestamp(traded_at, tz=_MARKET_TZ).date()
    if hist is not None and not hist.empty:
        return hist.index[-1].date()
    return None


def fetch_price_data(ticker: str) -> dict:
    """Fetch latest price, recent performance, and multi-horizon % changes for a ticker.

    Finnhub's quote endpoint is a single fast, reliable REST call and is tried first
    for the live price/prev_close when a paid key is configured. yfinance's unofficial,
    scrape-based API is slower and flakier, but it's the only source for the historical
    series used to compute realized vol and the 1d/1w/2w/1mo/YTD/1y change_pct
    breakdown (Finnhub candles require a paid plan), so it's always fetched regardless
    — and doubles as the price/prev_close fallback when Finnhub is unavailable or fails.
    """
    ticker = ticker.upper()

    quote = None
    try:
        from volatility_explainer.clients.finnhub import FinnhubClient

        settings = get_settings()
        if settings.finnhub_api_key.get_secret_value():
            client = FinnhubClient(settings)
            data = client.get_quote(ticker)
            price = data.get("c")
            if price:
                quote = {"price": price, "prev_close": data.get("pc"), "t": data.get("t")}
    except Exception as exc:
        print(f"[price:{ticker}]  finnhub   FAILED — {exc}")

    import yfinance as yf

    yf_ticker = yf.Ticker(ticker)
    hist = None
    try:
        hist = yf_ticker.history(period="2y")
    except Exception as exc:
        print(f"[price:{ticker}]  yfinance history FAILED — {exc}")

    # Neither Finnhub's quote nor the daily history sees pre- or post-market trades; yfinance's
    # info does. Skipped during regular hours, when there is nothing to find.
    info = None
    if not _regular_hours():
        try:
            info = yf_ticker.info
        except Exception as exc:
            print(f"[price:{ticker}]  yfinance info FAILED — {exc}")

    # Vol is measured before the quote is joined, so a big day after the close isn't judged
    # against a "usual move" that its own size has already inflated (the eval's correction,
    # evals/replay.normalize_price, does the same). During market hours yfinance's own
    # partial bar for today is already in `hist`, so there it is included either way.
    rv = realized_vol(hist) if hist is not None and not hist.empty else None
    if quote is not None:
        hist = _with_todays_close(hist, quote, ticker)
    changes = horizon_changes(hist) if hist is not None and not hist.empty else {}
    move_assessment = assess_moves(changes, rv)

    if quote is not None:
        price = quote["price"]
        prev_close = quote["prev_close"]
    elif hist is not None and not hist.empty:
        # Fallback: derive price/prev_close from the same yfinance history already fetched
        price = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
    else:
        print(f"[price:{ticker}]  yfinance  FAILED — no price history available")
        return {"ticker": ticker, "error": "no price history available"}

    chg_pct = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None
    session = _session_date(quote, info, hist)
    result = {
        "ticker": ticker,
        "price": round(price, 2) if price else None,
        "prev_close": round(prev_close, 2) if prev_close else None,
        "change_pct": chg_pct if chg_pct is not None else changes.get("1d"),
        # The regular session that price, change_pct and every changes_pct horizon end on.
        # Not today before the open, overnight, at weekends and on holidays.
        "session_date": session.isoformat() if session else None,
        "session_is_today": session == datetime.now(_MARKET_TZ).date() if session else None,
        "realized_vol_annualized_pct": rv,
        "changes_pct": changes,
        "move_assessment": move_assessment,
    }
    extended = extended_hours(info, price)
    if extended:
        result["extended_hours"] = extended
    return result
