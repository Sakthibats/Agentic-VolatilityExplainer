"""API keys must never reach a URL or an error message: callers print those to the logs.

Regression: a Finnhub 429 printed "...quote?symbol=NFLX&token=<key>" via the price tool's
failure line, locally and in Cloud Run logs.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from volatility_explainer.clients import finnhub
from volatility_explainer.clients.fred import FredClient

KEY = "sekr1t-key-123"


def _settings() -> SimpleNamespace:
    secret = SimpleNamespace(get_secret_value=lambda: KEY)
    return SimpleNamespace(finnhub_api_key=secret, fred_api_key=secret)


def _client(status: int, seen: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"c": 100.0, "pc": 99.0})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_finnhub_sends_the_key_as_a_header_not_in_the_url():
    seen: list[httpx.Request] = []
    finnhub.FinnhubClient(_settings(), client=_client(200, seen)).get_quote("nflx")

    assert seen[0].headers["X-Finnhub-Token"] == KEY
    assert KEY not in str(seen[0].url)


def test_finnhub_rate_limit_error_does_not_contain_the_key(monkeypatch):
    monkeypatch.setattr(finnhub.time, "sleep", lambda s: None)  # skip the retry backoff
    seen: list[httpx.Request] = []

    with pytest.raises(httpx.HTTPStatusError) as exc:
        finnhub.FinnhubClient(_settings(), client=_client(429, seen)).get_quote("NFLX")

    assert len(seen) == finnhub._RETRY_ATTEMPTS
    assert "429" in str(exc.value)
    assert KEY not in str(exc.value)


def test_fred_error_message_has_the_key_redacted():
    seen: list[httpx.Request] = []

    with pytest.raises(httpx.HTTPStatusError) as exc:
        FredClient(_settings(), client=_client(500, seen)).get_series_observations("VIXCLS")

    assert KEY in str(seen[0].url)  # FRED only takes it as a query parameter...
    assert KEY not in str(exc.value)  # ...so the message must be scrubbed
    assert "api_key=REDACTED" in str(exc.value)
    assert exc.value.response.status_code == 500
