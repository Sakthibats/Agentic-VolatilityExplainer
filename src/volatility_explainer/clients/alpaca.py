import httpx

from volatility_explainer.config import Settings

ALPACA_DATA_URL = "https://data.alpaca.markets"


class AlpacaClient:
    """HTTP client for Alpaca market data."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._api_key = settings.alpaca_api_key.get_secret_value()
        self._api_secret = settings.alpaca_api_secret.get_secret_value()
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
        }

    def get_latest_trade(self, symbol: str) -> dict:
        url = f"{ALPACA_DATA_URL}/v2/stocks/{symbol.upper()}/trades/latest"
        with self._client or httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start: str | None = None,
        end: str | None = None,
        limit: int = 130,
    ) -> dict:
        """Fetch OHLCV bars for a symbol.

        Args:
            symbol: Stock ticker symbol.
            timeframe: Bar size, e.g. "1Day", "1Hour".
            start: ISO-8601 date string for range start (e.g. "2024-01-01").
            end: ISO-8601 date string for range end.
            limit: Max number of bars to return.
        """
        url = f"{ALPACA_DATA_URL}/v2/stocks/{symbol.upper()}/bars"
        params: dict = {"timeframe": timeframe, "limit": limit, "adjustment": "split"}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        with self._client or httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            return response.json()
