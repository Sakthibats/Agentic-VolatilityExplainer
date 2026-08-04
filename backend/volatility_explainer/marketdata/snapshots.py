"""Ticker snapshot data for the UI sidebar: price history, quick stats, analyst targets.

Rescued from the retired Streamlit app (apps/ui/placeholders.py). All yfinance-backed
with graceful fallbacks — these feed GET /v1/tickers/{ticker}/... endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True)
class QuickStat:
    label: str
    value: str
    delta: str | None = None


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------

_YF_PERIOD_MAP: dict[str, str] = {
    "1W": "5d",
    "1M": "1mo",
    "6M": "6mo",
    "YTD": "ytd",
    "1Y": "1y",
}


def fetch_price_history(ticker: str, period: str = "6M") -> pd.DataFrame:
    """Return close prices for the given period, via yfinance."""
    ticker = ticker.upper()

    try:
        import yfinance as yf

        yf_period = _YF_PERIOD_MAP.get(period, "6mo")
        yf_interval = "1h" if period == "1W" else "1d"
        hist = yf.Ticker(ticker).history(period=yf_period, interval=yf_interval)
        if hist.empty:
            raise ValueError("empty response")
        hist = hist.reset_index()
        date_col = "Datetime" if "Datetime" in hist.columns else "Date"
        df = hist[[date_col, "Close"]].rename(columns={date_col: "date", "Close": "close"})
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df[["date", "close"]].dropna()
    except Exception as exc:
        print(f"[chart:{ticker}]  yfinance  FAILED — {exc}")
        return _synthetic_price_history()


def _synthetic_price_history() -> pd.DataFrame:
    import numpy as np

    end = date.today()
    start = end - timedelta(days=182)
    dates = pd.date_range(start=start, end=end, freq="B")
    rng = np.random.default_rng(42)
    prices = 180 + np.cumsum(rng.normal(0.1, 1.5, len(dates)))
    return pd.DataFrame({"date": dates, "close": prices.round(2)})


# ---------------------------------------------------------------------------
# Quick stats
# ---------------------------------------------------------------------------


def fetch_quick_stats(ticker: str) -> list[QuickStat]:
    """Return headline fundamentals from yfinance."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker.upper()).info
        stats: list[QuickStat] = []

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose")
        if price:
            delta = None
            if prev_close and prev_close > 0:
                chg = (price - prev_close) / prev_close * 100
                sign = "+" if chg >= 0 else ""
                delta = f"{sign}{chg:.1f}%"
            stats.append(QuickStat("Last Price", f"${price:,.2f}", delta))

        pe = info.get("trailingPE")
        stats.append(QuickStat("P/E Ratio", f"{pe:.1f}×" if pe else "N/A"))  # noqa: RUF001

        mkt_cap = info.get("marketCap")
        if mkt_cap:
            if mkt_cap >= 1e12:
                cap_str = f"${mkt_cap/1e12:.2f}T"
            elif mkt_cap >= 1e9:
                cap_str = f"${mkt_cap/1e9:.1f}B"
            else:
                cap_str = f"${mkt_cap/1e6:.0f}M"
            stats.append(QuickStat("Market Cap", cap_str))

        lo = info.get("fiftyTwoWeekLow")
        hi = info.get("fiftyTwoWeekHigh")
        if lo and hi:
            stats.append(QuickStat("52W Range", f"${lo:.0f} – ${hi:.0f}"))  # noqa: RUF001

        avg_vol = info.get("averageVolume")
        if avg_vol:
            vol_str = f"{avg_vol/1e6:.1f}M" if avg_vol >= 1e6 else f"{avg_vol/1e3:.0f}K"
            stats.append(QuickStat("Avg Volume", vol_str))

        beta = info.get("beta")
        if beta:
            stats.append(QuickStat("Beta", f"{beta:.2f}"))

        return stats or _fallback_stats()
    except Exception:
        return _fallback_stats()


def _fallback_stats() -> list[QuickStat]:
    return [QuickStat("Data", "Unavailable", None)]


# ---------------------------------------------------------------------------
# Analyst targets
# ---------------------------------------------------------------------------


def fetch_analyst_stats(ticker: str) -> list[QuickStat]:
    """Return analyst 1-year price targets from yfinance."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker.upper()).info

        target_low = info.get("targetLowPrice")
        target_high = info.get("targetHighPrice")
        target_mean = info.get("targetMeanPrice")
        num_analysts = info.get("numberOfAnalystOpinions")

        stats: list[QuickStat] = []
        if target_low and target_high:
            stats.append(QuickStat("1Y Low Target", f"${target_low:.2f}"))
            stats.append(QuickStat("1Y High Target", f"${target_high:.2f}"))
        if target_mean:
            stats.append(QuickStat("Mean Target", f"${target_mean:.2f}"))
        if num_analysts:
            stats.append(QuickStat("# Analysts", str(num_analysts)))

        return stats or _fallback_stats()
    except Exception:
        return _fallback_stats()
