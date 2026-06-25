"""Data pipeline — real market data and orchestrator calls."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator

import pandas as pd


@dataclass(frozen=True)
class AgentTile:
    agent: str
    title: str
    summary: str
    source: str


@dataclass(frozen=True)
class QuickStat:
    label: str
    value: str
    delta: str | None = None


@dataclass(frozen=True)
class AnalysisResult:
    ticker: str
    query: str
    tiles: list[AgentTile]
    final_output: str


# ---------------------------------------------------------------------------
# Input parsing — handles tickers, company names, and natural language
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    "why", "did", "does", "is", "are", "was", "were", "the", "a", "an",
    "how", "what", "when", "where", "who", "which", "that", "this", "these",
    "those", "can", "could", "has", "have", "had", "will", "would", "should",
    "dip", "drop", "fall", "fell", "rise", "rose", "up", "down", "spike",
    "crash", "surge", "move", "moved", "going", "go", "gone", "happened",
    "happen", "stock", "share", "price", "market", "ticker", "company",
    "so", "it", "do", "of", "in", "on", "at", "to", "for", "by", "with",
    "my", "me", "you", "we", "he", "she", "they", "his", "her", "their",
    "and", "or", "but", "not", "no", "yes", "iv", "vol", "be", "been",
    "today", "yesterday", "week", "month", "year", "recently", "just", "now",
    "huge", "big", "bad", "good", "much", "lot", "any", "all", "some",
    "get", "got", "buy", "sell", "hold", "long", "short", "put", "call",
})

_ticker_cache: dict[str, str | None] = {}


def _resolve_ticker(term: str) -> str | None:
    """Resolve a word to a valid US equity ticker via yfinance search."""
    key = term.upper()
    if key in _ticker_cache:
        return _ticker_cache[key]
    result = None
    try:
        import yfinance as yf
        hits = yf.Search(term, max_results=5).quotes
        for h in hits:
            sym = h.get("symbol", "")
            if re.match(r"^[A-Z]{1,5}$", sym):
                result = sym
                break
    except Exception:
        pass
    _ticker_cache[key] = result
    return result


def parse_search_input(raw: str) -> tuple[str | None, str]:
    """Extract a ticker from free-form input.

    Handles plain tickers ("TSLA", "tsla"), company names ("tesla"),
    and natural language ("why did rklb dip?").
    """
    text = raw.strip()
    if not text:
        return None, ""

    tokens = re.findall(r"\b[a-zA-Z]{1,6}\b", text)
    candidates = [t for t in tokens if t.lower() not in _STOP_WORDS]

    for candidate in candidates:
        ticker = _resolve_ticker(candidate)
        if ticker:
            return ticker, text

    return None, text


# ---------------------------------------------------------------------------
# Price history — real data with yfinance fallback
# ---------------------------------------------------------------------------


def fetch_price_history(ticker: str) -> pd.DataFrame:
    """Return 6-month daily close prices. Uses yfinance (no API key needed)."""
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker.upper()).history(period="6mo")
        if hist.empty:
            raise ValueError("Empty history")
        df = hist.reset_index()[["Date", "Close"]].rename(columns={"Date": "date", "Close": "close"})
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        return df[["date", "close"]].dropna()
    except Exception:
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
# Quick stats — real fundamentals via yfinance
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
        if pe:
            stats.append(QuickStat("P/E Ratio", f"{pe:.1f}x"))

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
            stats.append(QuickStat("52W Range", f"${lo:.0f} – ${hi:.0f}"))

        avg_vol = info.get("averageVolume")
        if avg_vol:
            if avg_vol >= 1e6:
                vol_str = f"{avg_vol/1e6:.1f}M"
            else:
                vol_str = f"{avg_vol/1e3:.0f}K"
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
# Full analysis pipeline — real orchestrator
# ---------------------------------------------------------------------------


def run_analysis(ticker: str, query: str) -> AnalysisResult:
    """Run the full agentic pipeline and return structured results."""
    try:
        # Add src/ to path so orchestrator can be imported from apps/
        import os

        src_path = os.path.join(os.path.dirname(__file__), "..", "..", "src")
        src_path = os.path.abspath(src_path)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from volatility_explainer.agent.orchestrator import run_explainer

        result = run_explainer(ticker)

        tiles = [
            AgentTile(
                agent=t["agent"],
                title=t["title"],
                summary=t["summary"],
                source=t["source"],
            )
            for t in result.get("tiles", [])
        ]

        # Build a readable markdown summary with ranked hypotheses
        summary_text = result.get("summary", "")
        hypotheses = result.get("hypotheses", [])
        if hypotheses:
            summary_text += "\n\n**Ranked hypotheses:**\n"
            for h in hypotheses:
                conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(
                    h.get("confidence", "medium"), "🟡"
                )
                summary_text += (
                    f"\n{h['rank']}. **{h['hypothesis']}** {conf_icon}  \n"
                    f"   _{h.get('evidence', '')}_\n"
                )

        if not tiles:
            tiles = _stub_tiles(ticker)
        if not summary_text:
            summary_text = _stub_summary(ticker)

        return AnalysisResult(
            ticker=ticker,
            query=query,
            tiles=tiles,
            final_output=f"**{ticker} Volatility Analysis**\n\n{summary_text}",
        )

    except Exception as exc:
        # Graceful fallback so the UI never crashes
        tiles = _stub_tiles(ticker)
        return AnalysisResult(
            ticker=ticker,
            query=query,
            tiles=tiles,
            final_output=_stub_summary(ticker) + f"\n\n_Note: live data unavailable ({exc})_",
        )


def stream_agent_tiles(ticker: str, query: str) -> Iterator[AgentTile]:
    """Yield pre-computed tiles (computed inside run_analysis)."""
    result = run_analysis(ticker, query)
    yield from result.tiles


# ---------------------------------------------------------------------------
# Stub fallbacks (shown if API keys missing or network error)
# ---------------------------------------------------------------------------


def _stub_tiles(ticker: str) -> list[AgentTile]:
    return [
        AgentTile("price", "Price & Realized Volatility", f"{ticker} data unavailable — check API keys.", "Alpaca"),
        AgentTile("options", "Options Skew", "Options data unavailable.", "Options chain"),
        AgentTile("news", "News Sentiment", "News data unavailable.", "Finnhub"),
        AgentTile("macro", "Macro Backdrop", "Macro data unavailable.", "FRED"),
        AgentTile("events", "Upcoming Events", "Events data unavailable.", "Events calendar"),
    ]


def _stub_summary(ticker: str) -> str:
    return (
        f"**{ticker} implied volatility analysis** could not be completed — "
        "verify that ALPACA, FINNHUB, FRED, and ANTHROPIC API keys are set in your `.env` file."
    )
