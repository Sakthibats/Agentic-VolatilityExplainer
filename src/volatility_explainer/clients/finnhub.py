import httpx

from volatility_explainer.config import Settings

FINNHUB_API_URL = "https://finnhub.io/api/v1"


class FinnhubClient:
    """HTTP client for Finnhub news and market data."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._api_key = settings.finnhub_api_key.get_secret_value()
        self._client = client

    def get_quote(self, symbol: str) -> dict:
        """Current quote: current price (c), previous close (pc), open (o), high (h), low (l)."""
        url = f"{FINNHUB_API_URL}/quote"
        params = {"symbol": symbol.upper(), "token": self._api_key}
        with self._client or httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def get_candles(self, symbol: str, *, resolution: str = "D", from_ts: int, to_ts: int) -> dict:
        """OHLCV candles. resolution: 1/5/15/30/60/D/W/M. Returns lists: c/o/h/l/v/t + s status."""
        url = f"{FINNHUB_API_URL}/stock/candle"
        params = {
            "symbol": symbol.upper(),
            "resolution": resolution,
            "from": from_ts,
            "to": to_ts,
            "token": self._api_key,
        }
        with self._client or httpx.Client(timeout=15.0) as client:
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
        with self._client or httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
