import httpx

from volatility_explainer.config import Settings

FRED_API_URL = "https://api.stlouisfed.org/fred"


class FredClient:
    """HTTP client for FRED macro series."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._api_key = settings.fred_api_key.get_secret_value()
        self._client = client

    def get_series_observations(self, series_id: str, *, limit: int = 10) -> dict:
        url = f"{FRED_API_URL}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        with self._client or httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
