from datetime import date, timedelta

from volatility_explainer.config import get_settings


def fetch_news(ticker: str, *, lookback_days: int = 7) -> dict:
    """Fetch recent news headlines. Finnhub first, yfinance fallback."""
    # Try Finnhub
    try:
        from volatility_explainer.clients.finnhub import FinnhubClient
        settings = get_settings()
        if settings.finnhub_api_key.get_secret_value():
            to_date = date.today()
            from_date = to_date - timedelta(days=lookback_days)
            headlines = FinnhubClient(settings).get_company_news(
                ticker,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            )
            return {"ticker": ticker.upper(), "headlines": headlines[:10], "source": "finnhub"}
    except Exception:
        pass

    # Fallback: yfinance news
    try:
        import yfinance as yf

        raw = yf.Ticker(ticker.upper()).news or []
        headlines = [
            {
                "headline": item.get("content", {}).get("title", ""),
                "summary": item.get("content", {}).get("summary", ""),
                "datetime": item.get("content", {}).get("pubDate", ""),
                "source": item.get("content", {}).get("provider", {}).get("displayName", ""),
            }
            for item in raw[:10]
        ]
        return {"ticker": ticker.upper(), "headlines": headlines, "source": "yfinance"}
    except Exception as exc:
        return {"ticker": ticker.upper(), "headlines": [], "error": str(exc)}
