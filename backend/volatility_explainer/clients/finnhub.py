import logging
import time
from functools import lru_cache

import httpx

from volatility_explainer.config import Settings

FINNHUB_API_URL = "https://finnhub.io/api/v1"

_logger = logging.getLogger(__name__)

# Finnhub sits behind Cloudflare and intermittently answers with an HTML 503 page that
# never reached their API — observed across every endpoint, minutes apart, independent of
# key or client IP. Retrying absorbs the blip; without it a single 503 degrades events and
# news for a real user request on the first try. 4xx is never retried: a 401/403/404 is an
# answer, and repeating it just burns the rate limit.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.4


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

    def _get(self, path: str, params: dict, *, timeout: float):
        """GET with exponential backoff over transient upstream failures.

        Re-raises the final response's HTTPStatusError (or the last transport exception)
        once the attempts are spent, so callers keep their existing degrade-gracefully
        behaviour — this only widens the window in which a blip can self-correct.
        """
        client = self._client or _shared_client(timeout)
        url = f"{FINNHUB_API_URL}/{path}"
        request_params = {**params, "token": self._api_key}

        for attempt in range(_RETRY_ATTEMPTS):
            last_attempt = attempt == _RETRY_ATTEMPTS - 1
            try:
                response = client.get(url, params=request_params)
            except (httpx.TimeoutException, httpx.TransportError):
                if last_attempt:
                    raise
                _logger.debug("[finnhub:%s] transport error, retrying", path, exc_info=True)
            else:
                if response.status_code not in _RETRY_STATUSES or last_attempt:
                    response.raise_for_status()
                    return response.json()
                _logger.debug("[finnhub:%s] HTTP %s, retrying", path, response.status_code)

            time.sleep(_RETRY_BASE_DELAY * (2**attempt))

        raise AssertionError("unreachable")  # pragma: no cover — loop always returns or raises

    def get_quote(self, symbol: str) -> dict:
        """Current quote: current price (c), previous close (pc), open (o), high (h), low (l)."""
        return self._get("quote", {"symbol": symbol.upper()}, timeout=15.0)

    def get_company_news(self, symbol: str, *, from_date: str, to_date: str) -> list[dict]:
        return self._get(
            "company-news",
            {"symbol": symbol.upper(), "from": from_date, "to": to_date},
            timeout=30.0,
        )

    def get_earnings_calendar(self, symbol: str, *, from_date: str, to_date: str) -> list[dict]:
        """Earnings within a date window — each entry has `hour` (bmo/amc/dmh) and `quarter`.

        Forward-looking only in practice: the free tier answers 200 with an empty list for
        any window that has already passed, so `epsActual` never arrives here. Reported
        quarters (and therefore the beat/miss verdict) come from yfinance instead — see
        `tools/events.py::_reported_earnings_from_yf`.

        Symbols with no earnings (ETFs, funds) return an empty list, not an error.
        """
        payload = self._get(
            "calendar/earnings",
            {"symbol": symbol.upper(), "from": from_date, "to": to_date},
            timeout=10.0,
        )
        return payload.get("earningsCalendar") or []
