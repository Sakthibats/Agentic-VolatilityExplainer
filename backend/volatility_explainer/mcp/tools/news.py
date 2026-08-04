from datetime import date, timedelta

from volatility_explainer.config import get_settings

# Only the first 3 headlines with a url ever surface as citations (see
# _attach_news_citations in the orchestrator), and the synthesis step only needs enough
# text to name a catalyst — so keep this payload small rather than fetching everything.
_MAX_HEADLINES = 5
_MAX_SUMMARY_CHARS = 200


def _truncate(summary: str) -> str:
    summary = summary or ""
    if len(summary) <= _MAX_SUMMARY_CHARS:
        return summary
    return summary[:_MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "..."


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
            raw = FinnhubClient(settings).get_company_news(
                ticker,
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
            )
            headlines = [
                {
                    "headline": item.get("headline", ""),
                    "summary": _truncate(item.get("summary", "")),
                    "datetime": item.get("datetime", ""),
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                }
                for item in raw[:_MAX_HEADLINES]
            ]
            return {"ticker": ticker, "headlines": headlines}
    except Exception as exc:
        print(f"[news:{ticker}]   finnhub   FAILED — {exc}")

    # Fallback: yfinance news
    try:
        import yfinance as yf

        raw = yf.Ticker(ticker).news or []
        headlines = [
            {
                "headline": item.get("content", {}).get("title", ""),
                "summary": _truncate(item.get("content", {}).get("summary", "")),
                "datetime": item.get("content", {}).get("pubDate", ""),
                "source": item.get("content", {}).get("provider", {}).get("displayName", ""),
                "url": (
                    item.get("content", {}).get("canonicalUrl", {}).get("url")
                    or item.get("content", {}).get("clickThroughUrl", {}).get("url", "")
                ),
            }
            for item in raw[:_MAX_HEADLINES]
        ]
        return {"ticker": ticker, "headlines": headlines}
    except Exception as exc:
        print(f"[news:{ticker}]   yfinance  FAILED — {exc}")
        return {"ticker": ticker, "headlines": [], "error": str(exc)}
