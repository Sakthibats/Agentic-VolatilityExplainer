"""Sector/peer comparison — compares a stock's move against its sector ETF's move
over the same horizons, using yfinance Ticker.info for sector classification and
history() + the existing horizon-change helper for the comparison itself."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from volatility_explainer.mcp.tools.price import _compute_horizon_changes

_SECTOR_ETF_MAP: dict[str, str] = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
    "Energy": "XLE",
}


def fetch_sector_comparison(ticker: str) -> dict:
    """Compare this stock's multi-horizon % moves against its sector ETF's moves over
    the same horizons — a more precise "is this stock-specific or industry-wide" signal
    than get_macro's broad S&P 500 / VIX check.
    """
    ticker = ticker.upper()
    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info
        sector = info.get("sector")
        etf_symbol = _SECTOR_ETF_MAP.get(sector) if sector else None

        if not etf_symbol:
            return {
                "ticker": ticker,
                "sector": sector,
                "error": f"No sector ETF mapping available for sector '{sector}'."
                if sector else "No sector classification available for this ticker.",
            }

        # Two independent HTTP calls — fetch in parallel rather than back-to-back.
        with ThreadPoolExecutor(max_workers=2) as pool:
            stock_fut = pool.submit(yf_ticker.history, period="2y")
            etf_fut = pool.submit(yf.Ticker(etf_symbol).history, period="2y")
            stock_hist = stock_fut.result()
            etf_hist = etf_fut.result()

        stock_changes = _compute_horizon_changes(stock_hist) if not stock_hist.empty else {}
        etf_changes = _compute_horizon_changes(etf_hist) if not etf_hist.empty else {}

        comparison: dict[str, dict] = {}
        for horizon in set(stock_changes) | set(etf_changes):
            stock_pct = stock_changes.get(horizon)
            etf_pct = etf_changes.get(horizon)
            relative_pct = (
                round(stock_pct - etf_pct, 2) if stock_pct is not None and etf_pct is not None else None
            )
            comparison[horizon] = {
                "stock_change_pct": stock_pct,
                "sector_etf_change_pct": etf_pct,
                "relative_to_sector_pct": relative_pct,
            }

        return {
            "ticker": ticker,
            "sector": sector,
            "sector_etf": etf_symbol,
            "comparison": comparison,
        }
    except Exception as exc:
        return {"ticker": ticker.upper(), "error": str(exc)}
