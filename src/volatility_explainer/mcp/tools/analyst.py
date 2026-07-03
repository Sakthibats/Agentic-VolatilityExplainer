"""Analyst sentiment and price targets via yfinance Ticker.info."""

from __future__ import annotations


def fetch_analyst_sentiment(ticker: str) -> dict:
    """Fetch Wall Street analyst consensus: rating, price targets, and coverage breadth.

    Single yfinance call (Ticker.info) — no separate HTTP round trip beyond what
    yfinance already does internally. No paid API required.
    """
    ticker = ticker.upper()
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info

        recommendation_key = info.get("recommendationKey")  # e.g. "buy", "hold", "underperform"
        recommendation_mean = info.get("recommendationMean")  # 1.0 (strong buy) - 5.0 (strong sell)
        num_analysts = info.get("numberOfAnalystOpinions")
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")

        upside_pct = None
        if target_mean and current_price:
            upside_pct = round((target_mean - current_price) / current_price * 100, 1)

        if recommendation_key is None and target_mean is None:
            return {
                "ticker": ticker,
                "error": "No analyst coverage data available for this ticker.",
            }

        return {
            "ticker": ticker,
            "recommendation_key": recommendation_key,
            "recommendation_mean": recommendation_mean,
            "number_of_analysts": num_analysts,
            "current_price": current_price,
            "target_mean_price": target_mean,
            "target_high_price": target_high,
            "target_low_price": target_low,
            "upside_to_target_pct": upside_pct,
        }
    except Exception as exc:
        return {"ticker": ticker.upper(), "error": str(exc)}
