"""HTTP client for Massive (Polygon-compatible) market data API."""

from __future__ import annotations

import httpx

from volatility_explainer.config import Settings

MASSIVE_API_URL = "https://api.massive.com"


class MassiveClient:
    """Polygon-compatible REST client for Massive market data."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._api_key = settings.massive_api_key.get_secret_value()
        self._client = client

    def _params(self, extra: dict | None = None) -> dict:
        return {"apiKey": self._api_key, **(extra or {})}

    def get_aggs(
        self,
        symbol: str,
        *,
        multiplier: int = 1,
        timespan: str = "day",
        from_date: str,
        to_date: str,
        adjusted: bool = True,
        sort: str = "asc",
        limit: int = 120,
    ) -> dict:
        """Aggregate OHLCV bars. from_date/to_date as 'YYYY-MM-DD'."""
        url = (
            f"{MASSIVE_API_URL}/v2/aggs/ticker/{symbol.upper()}"
            f"/range/{multiplier}/{timespan}/{from_date}/{to_date}"
        )
        params = self._params({
            "adjusted": "true" if adjusted else "false",
            "sort": sort,
            "limit": limit,
        })
        with self._client or httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
