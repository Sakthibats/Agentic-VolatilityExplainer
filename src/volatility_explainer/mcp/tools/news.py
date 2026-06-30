from datetime import date, timedelta

from volatility_explainer.config import get_settings


def fetch_news(ticker: str, *, lookback_days: int = 7) -> dict:
    """Fetch recent news headlines. Finnhub first, yfinance fallback."""
    ticker = ticker.upper()

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
            return {"ticker": ticker, "headlines": headlines[:10]}
    except Exception as exc:
        print(f"[news:{ticker}]   finnhub   FAILED — {exc}")

    # Fallback: yfinance news
    try:
        import yfinance as yf

        raw = yf.Ticker(ticker).news or []
        headlines = [
            {
                "headline": item.get("content", {}).get("title", ""),
                "summary": item.get("content", {}).get("summary", ""),
                "datetime": item.get("content", {}).get("pubDate", ""),
            }
            for item in raw[:10]
        ]
        return {"ticker": ticker, "headlines": headlines}
    except Exception as exc:
        print(f"[news:{ticker}]   yfinance  FAILED — {exc}")
        return {"ticker": ticker, "headlines": [], "error": str(exc)}
