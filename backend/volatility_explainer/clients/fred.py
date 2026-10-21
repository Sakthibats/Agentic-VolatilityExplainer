import re

import httpx

from volatility_explainer.clients.finnhub import _shared_client
from volatility_explainer.config import Settings

FRED_API_URL = "https://api.stlouisfed.org/fred"

_API_KEY_PARAM = re.compile(r"(api_key=)[^&\s'\"]+")


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
        client = self._client or _shared_client(30.0)
        response = client.get(url, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # FRED accepts the key only as a query parameter, and httpx puts the full URL in
            # the error message that callers print, so strip the key out of the message.
            message = _API_KEY_PARAM.sub(r"\1REDACTED", str(exc))
            raise httpx.HTTPStatusError(
                message, request=exc.request, response=exc.response
            ) from None
        return response.json()
