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
# Input parsing — handles tickers, company names, natural language, concepts
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    "why", "did", "does", "is", "are", "was", "were", "the", "a", "an",
    "how", "what", "when", "where", "who", "which", "that", "this", "these",
    "those", "can", "could", "has", "have", "had", "will", "would", "should",
    "dip", "drop", "fall", "fell", "rise", "rose", "up", "down", "spike",
    "crash", "surge", "move", "moved", "going", "go", "gone", "happened",
    "happening", "happen", "stock", "share", "price", "market", "ticker",
    "company", "so", "it", "do", "of", "in", "on", "at", "to", "for", "by",
    "with", "my", "me", "you", "we", "he", "she", "they", "his", "her",
    "their", "and", "or", "but", "not", "no", "yes", "iv", "vol", "be",
    "been", "today", "yesterday", "week", "month", "year", "recently",
    "just", "now", "huge", "big", "bad", "good", "much", "lot", "any",
    "all", "some", "get", "got", "buy", "sell", "hold", "long", "short",
    "put", "call", "explain", "tell", "show", "showing", "trading", "trade",
    "perform", "performing", "doing", "look", "looking", "think", "about",
    "around", "over", "under", "since", "after", "before", "during",
    "between", "into", "through", "across", "against", "because", "from",
    "there", "here", "where", "then", "than", "like", "if", "too",
    "please", "help", "me", "know", "think", "feel", "way", "time",
    "day", "last", "next", "recent", "past", "future", "current", "latest",
})

# Financial concepts mapped to yfinance-friendly fund name search queries.
# We use specific fund names (not tickers) so yfinance resolves the most
# liquid representative ETF — no hardcoded ticker mappings here.
_CONCEPT_HINTS: list[tuple[str, str]] = [
    (r"\bgold\b",                                "iShares gold trust"),
    (r"\bsilver\b",                              "iShares silver trust"),
    (r"\bcopper\b",                              "United States copper"),
    (r"\boil\b|\bcrude\b|\bpetroleum\b",         "United States Oil Fund"),
    (r"\bnatural\s+gas\b",                       "United States natural gas"),
    (r"\bbitcoin\b|\bbtc\b|\bcrypto\b",          "iShares bitcoin trust"),
    (r"\bethereum\b|\beth\b",                    "iShares ethereum trust"),
    (r"\bs[&\s]?p\s*500\b|\bsp500\b|\bsnp\b",   "SPDR S&P 500"),
    (r"\bnasdaq\b|\bqq\b",                       "Invesco QQQ trust"),
    (r"\bdow\s+jones\b|\bdjia\b|\bdow\b",        "SPDR dow jones"),
    (r"\btotal\s+market\b|\bstock\s+market\b|\bmarkets?\b", "Vanguard total stock"),
    (r"\brussell\b|\bsmall[\s-]?cap\b",          "iShares russell 2000"),
    (r"\bbond\b|\btreasury\b|\bfixed\s+income\b","iShares 20 year treasury"),
    (r"\bemerging\s+market\b|\bem\s+market\b",   "iShares MSCI emerging markets"),
    (r"\breal\s+estate\b|\breit\b",              "Vanguard real estate"),
    (r"\benergy\s+sector\b|\benergy\s+stock\b",  "XLE energy"),
    (r"\btech\s+sector\b|\btechnology\s+sector\b","XLK technology"),
    (r"\bfinancial\s+sector\b|\bbank\s+sector\b","XLF financial"),
    (r"\bhealthcare\s+sector\b|\bpharma\s+sector\b","XLV healthcare"),
]

_FINANCIAL_KEYWORDS: frozenset[str] = frozenset({
    "stock", "stocks", "share", "shares", "equity", "equities",
    "price", "prices", "etf", "fund", "index", "indices",
    "crypto", "bitcoin", "ethereum", "coin", "token",
    "gold", "oil", "silver", "copper", "commodity", "commodities",
    "earnings", "revenue", "profit", "loss", "dividend", "buyback",
    "analyst", "rating", "upgrade", "downgrade", "target", "forecast",
    "ipo", "spac", "merger", "acquisition", "deal", "spinoff",
    "fed", "fomc", "rate", "inflation", "cpi", "gdp", "recession",
    "vix", "volatility", "options", "calls", "puts",
    "nasdaq", "nyse", "dow", "russell",
    "bond", "bonds", "treasury", "yield", "sector",
    "bull", "bear", "rally", "correction", "crash", "dip", "surge",
    "invest", "investing", "portfolio", "position", "hedge",
    "quarter", "guidance", "outlook", "report", "market", "ticker",
    "short", "squeeze", "momentum", "breakout",
})

# Price/movement intent words — used to detect financial inquiry even when
# explicit financial nouns are absent (e.g. "why did apple dip?")
_FINANCIAL_INTENT_WORDS: frozenset[str] = frozenset({
    "dip", "drop", "fall", "fell", "rise", "rose", "spike", "crash",
    "surge", "jump", "tumble", "rally", "plunge", "soar", "tank",
    "gain", "decline", "climb", "slide", "bounce", "pump", "dump",
    "happened", "happen", "moved", "move", "performing", "explain",
    "investigate", "analyze", "volatile", "lower", "higher",
})

_ticker_cache: dict[str, str | None] = {}


def _resolve_ticker(term: str, search_query: str | None = None) -> str | None:
    """Resolve a word/phrase to a valid US equity ticker via yfinance search.
    If search_query is given it overrides the search text (but term is still the cache key).
    """
    cache_key = (search_query or term).upper()
    if cache_key in _ticker_cache:
        return _ticker_cache[cache_key]
    result = None
    try:
        import yfinance as yf
        query = search_query or term
        hits = yf.Search(query, max_results=10).quotes
        for h in hits:
            sym = h.get("symbol", "")
            # Accept only clean 1-5 letter tickers (no dots, hyphens — those are usually foreign or preferred)
            if re.match(r"^[A-Z]{1,5}$", sym):
                result = sym
                break
    except Exception:
        pass
    _ticker_cache[cache_key] = result
    return result


def validate_financial_query(raw: str, ticker: str | None) -> tuple[bool, str]:
    """Return (is_valid, error_message). Valid means the query is about financial price movements.

    Layers:
    1. Concept hint match (gold, nasdaq, s&p 500, market…) → valid
    2. Financial noun keywords → valid
    3. User explicitly wrote an ALL-CAPS ticker symbol → valid
    4. Price/movement intent word + resolved ticker → valid
    Otherwise → blocked (guardrail)
    """
    text_lower = raw.lower()
    words = set(re.findall(r"\b\w+\b", text_lower))

    # 1. Concept phrases
    for pattern, _ in _CONCEPT_HINTS:
        if re.search(pattern, text_lower):
            return True, ""

    # 2. Financial nouns present in raw text
    if words & _FINANCIAL_KEYWORDS:
        return True, ""

    # 3. Single-word query — almost always a direct ticker lookup (e.g. "rklb", "aapl")
    if ticker and len(raw.strip().split()) == 1:
        return True, ""

    # 4. User explicitly wrote an uppercase ticker/symbol (≥2 caps chars)
    uppercase_tokens = set(re.findall(r"\b[A-Z]{2,5}\b", raw))
    if ticker and ticker in uppercase_tokens:
        return True, ""

    # 4. Financial intent word (dip, drop, crash…) alongside a resolved ticker
    if ticker and (words & _FINANCIAL_INTENT_WORDS):
        return True, ""

    return False, (
        "This tool investigates **stock and ETF price movements** only. "
        "Ask about a company (*why did Apple dip?*), a ticker (*TSLA*), "
        "or a market/asset (*what happened to gold?*, *why is the market down?*)."
    )


def parse_search_input(raw: str) -> tuple[str | None, str]:
    """Extract a ticker from free-form input.

    Priority order:
    1. Concept phrases (gold → GLD/IAU, market → VTI, S&P 500 → VOO)
    2. Uppercase tokens that look like tickers (TSLA, AAPL)
    3. Other words tried as company name searches (tesla → TSLA)
    """
    text = raw.strip()
    if not text:
        return None, ""

    text_lower = text.lower()

    # 1. Concept phrases first — catches "gold price", "market", "s&p 500", etc.
    for pattern, search_query in _CONCEPT_HINTS:
        if re.search(pattern, text_lower):
            ticker = _resolve_ticker(search_query, search_query)
            if ticker:
                return ticker, text

    tokens = re.findall(r"\b[a-zA-Z]{1,6}\b", text)

    # 2. Uppercase tokens ≥2 chars — likely ticker symbols; single letters are usually pronouns
    upper_candidates = [t for t in tokens if re.match(r"^[A-Z]{2,5}$", t) and t not in _STOP_WORDS]
    # 3. Other candidates — company names etc.
    other_candidates = [t for t in tokens if t.lower() not in _STOP_WORDS and not re.match(r"^[A-Z]{1,5}$", t)]

    for candidate in upper_candidates + other_candidates:
        ticker = _resolve_ticker(candidate)
        if ticker:
            return ticker, text

    return None, text


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------

_PERIOD_MAP: dict[str, str] = {
    "1D": "1d",
    "1M": "1mo",
    "6M": "6mo",
    "YTD": "ytd",
    "1Y": "1y",
}


def fetch_price_history(ticker: str, period: str = "6M") -> pd.DataFrame:
    """Return daily close prices for the given period. Uses yfinance."""
    yf_period = _PERIOD_MAP.get(period, "6mo")
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker.upper()).history(period=yf_period)
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
        stats.append(QuickStat("P/E Ratio", f"{pe:.1f}×" if pe else "N/A"))

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
# Full analysis pipeline
# ---------------------------------------------------------------------------


def run_analysis(ticker: str, query: str) -> AnalysisResult:
    """Run the full agentic pipeline and return structured results."""
    try:
        import os

        src_path = os.path.join(os.path.dirname(__file__), "..", "..", "src")
        src_path = os.path.abspath(src_path)
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from volatility_explainer.agent.orchestrator import run_explainer

        result = run_explainer(ticker, query)

        tiles = [
            AgentTile(
                agent=t["agent"],
                title=t["title"],
                summary=t["summary"],
                source=t["source"],
            )
            for t in result.get("tiles", [])
        ]

        summary_text = result.get("summary", "")
        hypotheses = result.get("hypotheses", [])
        if hypotheses:
            summary_text += "\n\n**Most likely causes:**\n"
            for h in hypotheses:
                conf = h.get("confidence", "medium")
                conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "🟡")
                conf_label = {"high": "High confidence", "medium": "Medium confidence", "low": "Low confidence / speculative"}.get(conf, "")
                caveat = h.get("caveat", "")
                caveat_text = f"   _Caveat: {caveat}_\n" if caveat and caveat != "N/A" else ""
                summary_text += (
                    f"\n{h['rank']}. **{h['hypothesis']}** {conf_icon} _{conf_label}_  \n"
                    f"   _{h.get('evidence', '')}_\n"
                    f"{caveat_text}"
                )

        if not tiles:
            tiles = _stub_tiles(ticker)
        if not summary_text:
            summary_text = _stub_summary(ticker)

        return AnalysisResult(
            ticker=ticker,
            query=query,
            tiles=tiles,
            final_output=f"**{ticker} — Price Movement Analysis**\n\n{summary_text}",
        )

    except Exception as exc:
        tiles = _stub_tiles(ticker)
        return AnalysisResult(
            ticker=ticker,
            query=query,
            tiles=tiles,
            final_output=_stub_summary(ticker) + f"\n\n_Note: live data unavailable ({exc})_",
        )


def stream_agent_tiles(ticker: str, query: str) -> Iterator[AgentTile]:
    result = run_analysis(ticker, query)
    yield from result.tiles


# ---------------------------------------------------------------------------
# Stub fallbacks
# ---------------------------------------------------------------------------


def _stub_tiles(ticker: str) -> list[AgentTile]:
    return [
        AgentTile("price", "Price Action", f"{ticker} data unavailable — check API keys.", "Alpaca"),
        AgentTile("options", "Options Activity", "Options data unavailable.", "Options chain"),
        AgentTile("news", "News & Catalysts", "News data unavailable.", "Finnhub"),
        AgentTile("macro", "Market Context", "Macro data unavailable.", "FRED"),
        AgentTile("events", "Events & Triggers", "Events data unavailable.", "Events calendar"),
    ]


def _stub_summary(ticker: str) -> str:
    return (
        f"**{ticker} analysis** could not be completed — "
        "verify that ALPACA, FINNHUB, FRED, and ANTHROPIC API keys are set in your `.env` file."
    )
