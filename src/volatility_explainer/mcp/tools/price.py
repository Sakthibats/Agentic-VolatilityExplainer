from volatility_explainer.config import get_settings

# Trading-day lookbacks for each horizon (approx — markets are closed weekends/holidays)
_HORIZON_TRADING_DAYS: dict[str, int] = {
    "1d": 1,
    "1w": 5,
    "2w": 10,
    "1mo": 21,
    "1y": 252,
}


def _pct_change(closes, back: int) -> float | None:
    if len(closes) <= back:
        return None
    start = closes[-1 - back]
    if not start:
        return None
    return round((closes[-1] - start) / start * 100, 2)


def _compute_horizon_changes(hist) -> dict:
    """% change from the latest close for each horizon, plus year-to-date."""
    closes = hist["Close"].dropna()
    if closes.empty:
        return {}

    values = closes.values
    changes = {label: _pct_change(values, days) for label, days in _HORIZON_TRADING_DAYS.items()}

    current_year = closes.index[-1].year
    ytd_closes = closes[closes.index.year == current_year]
    if len(ytd_closes) >= 2:
        start_price = float(ytd_closes.iloc[0])
        latest_price = float(closes.iloc[-1])
        changes["ytd"] = round((latest_price - start_price) / start_price * 100, 2) if start_price else None
    else:
        changes["ytd"] = None

    return changes


def _compute_realized_vol(hist) -> float | None:
    """Annualized realized vol from the trailing ~20 trading days."""
    closes = hist["Close"].dropna().tail(21)
    if len(closes) < 5:
        return None

    returns = closes.pct_change().dropna()
    return round(float(returns.std() * (252 ** 0.5) * 100), 1)


_SEVERITY = {"typical": 0, "elevated": 1, "unusual": 2}

# Absolute-magnitude floor per horizon: (elevated_pct, unusual_pct). A chronically volatile
# stock (e.g. 100%+ realized vol) can make almost any move look "typical" when judged only
# relative to its own history — an 18% monthly drop is still a genuinely large move to a
# normal reader even if it's unremarkable for that one ticker. These are plain-English
# "does this matter regardless of whose stock it is" thresholds.
_ABS_THRESHOLDS_PCT: dict[str, tuple[float, float]] = {
    "1d": (3, 7),
    "1w": (6, 12),
    "2w": (9, 16),
    "1mo": (12, 22),
    "1y": (30, 60),
}


def _level_from_ratio(ratio: float) -> str:
    return "typical" if ratio <= 1 else "elevated" if ratio <= 2 else "unusual"


def _level_from_abs(change_pct: float, thresholds: tuple[float, float]) -> str:
    elevated_pct, unusual_pct = thresholds
    magnitude = abs(change_pct)
    return "typical" if magnitude < elevated_pct else "elevated" if magnitude < unusual_pct else "unusual"


def _assess_moves(changes: dict, rv: float | None) -> dict:
    """Label each horizon's move so neither the LLM nor a user's alarmed wording ("crashed",
    "tanked") has to eyeball significance — the numbers decide it, on two axes:

    - relative_level: |change| vs. this stock's OWN normal move for that horizon
      (ratio_to_normal = |change| / expected move, which scales with sqrt(time) off the
      annualized realized vol).
    - absolute_level: |change| vs. a fixed, stock-agnostic magnitude floor (_ABS_THRESHOLDS_PCT)
      — so a chronically volatile stock can't get an 18% drop rubber-stamped "typical" purely
      because that's normal for IT specifically.

    level (the one to act on) is the MORE severe of the two — typical only if both agree
    it's typical; elevated or unusual if either axis says so.
    """
    if not rv:
        return {}
    assessment = {}
    for label, days in _HORIZON_TRADING_DAYS.items():
        change_pct = changes.get(label)
        if change_pct is None:
            continue
        expected_move = rv / (252 ** 0.5) * (days ** 0.5)
        if expected_move <= 0:
            continue
        ratio = round(abs(change_pct) / expected_move, 2)
        relative_level = _level_from_ratio(ratio)
        absolute_level = _level_from_abs(change_pct, _ABS_THRESHOLDS_PCT[label])
        level = max([relative_level, absolute_level], key=_SEVERITY.get)
        assessment[label] = {
            "change_pct": change_pct,
            "expected_move_pct": round(expected_move, 2),
            "ratio_to_normal": ratio,
            "relative_level": relative_level,
            "absolute_level": absolute_level,
            "level": level,
        }
    return assessment


def fetch_price_data(ticker: str) -> dict:
    """Fetch latest price, recent performance, and multi-horizon % changes for a ticker.

    Finnhub gives the live quote (current price / prev close) when a paid key is
    configured; yfinance always supplies the historical series used to compute
    realized vol and the 1d/1w/2w/1mo/YTD/1y change_pct breakdown, since Finnhub
    candles require a paid plan.
    """
    ticker = ticker.upper()

    import yfinance as yf

    hist = None
    try:
        hist = yf.Ticker(ticker).history(period="2y")
    except Exception as exc:
        print(f"[price:{ticker}]  yfinance history FAILED — {exc}")

    changes = _compute_horizon_changes(hist) if hist is not None and not hist.empty else {}
    rv = _compute_realized_vol(hist) if hist is not None and not hist.empty else None
    move_assessment = _assess_moves(changes, rv)

    # Try Finnhub first for the live quote — Finnhub candles require a paid plan, so
    # realized vol / horizon changes always come from the yfinance history above.
    try:
        from volatility_explainer.clients.finnhub import FinnhubClient

        settings = get_settings()
        if settings.finnhub_api_key.get_secret_value():
            client = FinnhubClient(settings)
            quote = client.get_quote(ticker)
            price = quote.get("c")
            prev_close = quote.get("pc")
            chg_pct = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None

            if price:
                return {
                    "ticker": ticker,
                    "price": round(price, 2),
                    "prev_close": round(prev_close, 2) if prev_close else None,
                    "change_pct": chg_pct if chg_pct is not None else changes.get("1d"),
                    "realized_vol_annualized_pct": rv,
                    "changes_pct": changes,
                    "move_assessment": move_assessment,
                }
    except Exception as exc:
        print(f"[price:{ticker}]  finnhub   FAILED — {exc}")

    # Fallback: derive price/prev_close from the same yfinance history already fetched
    try:
        if hist is None or hist.empty:
            raise ValueError("no price history available")

        price = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
        chg_pct = round((price - prev) / prev * 100, 2) if price and prev else None

        return {
            "ticker": ticker,
            "price": round(price, 2) if price else None,
            "prev_close": round(prev, 2) if prev else None,
            "change_pct": chg_pct if chg_pct is not None else changes.get("1d"),
            "realized_vol_annualized_pct": rv,
            "changes_pct": changes,
            "move_assessment": move_assessment,
        }
    except Exception as exc:
        print(f"[price:{ticker}]  yfinance  FAILED — {exc}")
        return {"ticker": ticker, "error": str(exc)}
