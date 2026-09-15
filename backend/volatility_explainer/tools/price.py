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


_HORIZON_PHRASE: dict[str, str] = {
    "1d": "today",
    "1w": "this week",
    "2w": "the past 2 weeks",
    "1mo": "the past month",
    "1y": "the past year",
}

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


# Bands on |change| / expected move, where the expected move is one standard deviation for
# that span. A move past 1x happens about one day in three, past 1.5x about one day in
# seven, past 2.5x about one day in eighty — so "typical" has to reach well beyond 1x, or an
# ordinary day gets called "larger than usual".
_RELATIVE_BANDS = (1.5, 2.5)


def _level_from_ratio(ratio: float) -> str:
    elevated, unusual = _RELATIVE_BANDS
    return "typical" if ratio < elevated else "elevated" if ratio < unusual else "unusual"


def _level_from_abs(change_pct: float, thresholds: tuple[float, float]) -> str:
    elevated_pct, unusual_pct = thresholds
    magnitude = abs(change_pct)
    return "typical" if magnitude < elevated_pct else "elevated" if magnitude < unusual_pct else "unusual"


def _flag_text(
    label: str, change_pct: float, expected_move: float, ratio: float,
    relative_level: str, absolute_level: str, level: str,
) -> str:
    """One deterministic plain-English sentence per non-typical horizon — written here, in
    code, so the LLM never has to compute or notice significance itself. When relative_level
    and absolute_level disagree (e.g. a move that's normal for this specific stock's own
    volatility but large in plain terms), both framings are spelled out explicitly rather than
    leaving that nuance for the model to catch on its own.
    """
    phrase = _HORIZON_PHRASE[label]
    if relative_level == absolute_level:
        return (
            f"{phrase}: {change_pct}% — {level} for this stock "
            f"(about {ratio}x its normal move for that span, expected ~{expected_move:.2f}%)"
        )
    return (
        f"{phrase}: {change_pct}% — {relative_level} relative to this stock's own typical "
        f"volatility (expected ~{expected_move:.2f}%, {ratio}x), but {absolute_level} in plain "
        f"magnitude terms regardless of whose stock it is (overall: {level})"
    )


def _horizon_levels(changes: dict, rv: float | None) -> dict[str, tuple]:
    """Per-horizon significance: label -> (level, relative_level, absolute_level, change_pct,
    expected_move, ratio). Shared by _assess_moves (what the model reads) and describe_move
    (what the reader reads first), so the two can never disagree about a verdict.
    """
    if not rv:
        return {}
    per_horizon: dict[str, tuple] = {}
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
        per_horizon[label] = (level, relative_level, absolute_level, change_pct, expected_move, ratio)
    return per_horizon


def _assess_moves(changes: dict, rv: float | None) -> dict:
    """Determine significance deterministically, in code, on two axes — never left for the LLM
    to eyeball from raw numbers or trust a user's alarmed wording ("crashed", "tanked"):

    - relative_level: |change| vs. this stock's OWN normal move for that horizon (ratio =
      |change| / expected move, where expected move scales with sqrt(time) off annualized rv).
    - absolute_level: |change| vs. a fixed, stock-agnostic magnitude floor (_ABS_THRESHOLDS_PCT)
      — so a chronically volatile stock can't get an 18% drop rubber-stamped "typical" just
      because that's normal for IT specifically.

    Returns "overall" (the most severe level across all horizons) plus "flags" — one sentence
    per horizon that isn't typical on both axes. A horizon absent from "flags" is unremarkable.
    """
    per_horizon = _horizon_levels(changes, rv)
    if not per_horizon:
        return {}

    overall = max((v[0] for v in per_horizon.values()), key=_SEVERITY.get)
    flags = [
        _flag_text(label, change_pct, expected_move, ratio, relative_level, absolute_level, level)
        for label, (level, relative_level, absolute_level, change_pct, expected_move, ratio) in per_horizon.items()
        if level != "typical"
    ]
    return {"overall": overall, "flags": flags}


_LEVEL_WORDS = {"elevated": "larger than usual", "unusual": "unusually large"}
# The stock-agnostic floor, worded as a comparison with other stocks rather than this one.
_PLAIN_WORDS = {"elevated": "large", "unusual": "very large"}


def _verdict(ticker: str, relative_level: str, absolute_level: str) -> str:
    """The size verdict a reader sees for one horizon, e.g. "normal for DDOG, but large by
    most stocks' standards".

    Judged against this stock's own normal range first. The stock-agnostic floor is added
    only when it is more severe than that, and is always named as a comparison with other
    stocks — so the two framings read as two facts rather than a contradiction.
    """
    name = ticker or "this stock"
    verdict = (
        f"normal for {name}" if relative_level == "typical"
        else f"{_LEVEL_WORDS[relative_level]} for {name}"
    )
    if _SEVERITY[absolute_level] > _SEVERITY[relative_level]:
        joiner = "but" if relative_level == "typical" else "and"
        verdict += f", {joiner} {_PLAIN_WORDS[absolute_level]} by most stocks' standards"
    return verdict


def _signed_move(change_pct: float) -> str:
    if change_pct == 0:
        return "flat"
    return f"{'up' if change_pct > 0 else 'down'} {abs(change_pct):.1f}%"


def describe_move(price_data: dict) -> str:
    """The factual "what happened" paragraph a reader sees before any LLM output.

    Built only from get_price_data's result, so it is ready the moment the deterministic
    pre-fetch lands — seconds before the model has decided anything — and it can only state
    numbers and verdicts that code computed. The model's explanation of WHY is written later
    and shown beneath it. Works on a cached result dict just as well as a fresh one.

    Returns "" when there is no usable price, so the caller simply shows nothing.
    """
    ticker = price_data.get("ticker") or ""
    price = price_data.get("price")
    if price_data.get("error") or not price:
        return ""

    changes = price_data.get("changes_pct") or {}
    today = price_data.get("change_pct")
    lead = f"{ticker} is at ${price:,.2f}"
    sentences = [f"{lead}, {_signed_move(today)} today." if today is not None else f"{lead}."]

    per_horizon = _horizon_levels(changes, price_data.get("realized_vol_annualized_pct"))
    if not per_horizon:
        return " ".join(sentences)  # too little history to judge significance — say only what's known

    day = per_horizon.get("1d")
    if day is not None and today is not None:
        _, relative_level, absolute_level, _, expected_move, _ = day
        # A range a reader can picture ("up to about 3.7% a day") rather than a multiple of
        # one ("1.08x its typical daily move"). The expected move is one standard deviation,
        # which about two days in three stay within.
        sentences.append(
            f"It usually moves up to about {expected_move:.1f}% a day, so today's move is "
            f"{_verdict(ticker, relative_level, absolute_level)}."
        )

    def span(label: str) -> str:  # "this week" reads alone; "the past month" needs "over"
        phrase = _HORIZON_PHRASE[label]
        return phrase if phrase.startswith("this") else f"over {phrase}"

    # A longer horizon earns a mention when it is out of the ordinary for THIS stock, or very
    # large by any standard. One that is normal for the stock and merely "large" against the
    # stock-agnostic floor (a volatile name up 8% in a week) stays in the model's flags only.
    longer = [
        f"{_signed_move(change_pct)} {span(label)} ({_verdict(ticker, relative_level, absolute_level)})"
        for label, (_, relative_level, absolute_level, change_pct, _, _) in per_horizon.items()
        if label != "1d" and (relative_level != "typical" or absolute_level == "unusual")
    ]
    if longer:
        sentences.append(f"Zooming out, it is {' and '.join(longer[:2])}.")
    elif all(v[0] == "typical" for v in per_horizon.values()):
        sentences.append("Every timeframe from today to the past year is within its normal range.")

    return " ".join(sentences)


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
                quote = {"price": price, "prev_close": data.get("pc")}
    except Exception as exc:
        print(f"[price:{ticker}]  finnhub   FAILED — {exc}")

    import yfinance as yf

    hist = None
    try:
        hist = yf.Ticker(ticker).history(period="2y")
    except Exception as exc:
        print(f"[price:{ticker}]  yfinance history FAILED — {exc}")

    changes = _compute_horizon_changes(hist) if hist is not None and not hist.empty else {}
    rv = _compute_realized_vol(hist) if hist is not None and not hist.empty else None
    move_assessment = _assess_moves(changes, rv)

    if quote is not None:
        price = quote["price"]
        prev_close = quote["prev_close"]
        chg_pct = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None
        return {
            "ticker": ticker,
            "price": round(price, 2),
            "prev_close": round(prev_close, 2) if prev_close else None,
            "change_pct": chg_pct if chg_pct is not None else changes.get("1d"),
            "realized_vol_annualized_pct": rv,
            "changes_pct": changes,
            "move_assessment": move_assessment,
        }

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
