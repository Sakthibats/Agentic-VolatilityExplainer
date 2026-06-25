import httpx

from volatility_explainer.config import Settings

FINNHUB_API_URL = "https://finnhub.io/api/v1"


class FinnhubClient:
    """HTTP client for Finnhub news and market data."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._api_key = settings.finnhub_api_key.get_secret_value()
        self._client = client

    def get_company_news(self, symbol: str, *, from_date: str, to_date: str) -> list[dict]:
        url = f"{FINNHUB_API_URL}/company-news"
        params = {
            "symbol": symbol.upper(),
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }
        with self._client or httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
