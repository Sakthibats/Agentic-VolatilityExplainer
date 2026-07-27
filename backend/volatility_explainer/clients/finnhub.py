from functools import lru_cache

import httpx

from volatility_explainer.config import Settings

FINNHUB_API_URL = "https://finnhub.io/api/v1"


@lru_cache(maxsize=4)
def _shared_client(timeout: float) -> httpx.Client:
    """One persistent client per timeout — connection pooling/keep-alive across calls
    instead of a fresh TCP+TLS handshake per request. Never closed; lives for the process.
    """
    return httpx.Client(timeout=timeout)


class FinnhubClient:
    """HTTP client for Finnhub news and market data."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._api_key = settings.finnhub_api_key.get_secret_value()
        self._client = client

    def get_quote(self, symbol: str) -> dict:
        """Current quote: current price (c), previous close (pc), open (o), high (h), low (l)."""
        url = f"{FINNHUB_API_URL}/quote"
        params = {"symbol": symbol.upper(), "token": self._api_key}
        client = self._client or _shared_client(15.0)
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_company_news(self, symbol: str, *, from_date: str, to_date: str) -> list[dict]:
        url = f"{FINNHUB_API_URL}/company-news"
        params = {
            "symbol": symbol.upper(),
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }
        client = self._client or _shared_client(30.0)
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
