"""Chart history: real prices or nothing, never stand-in data."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient
from volatility_explainer.api.app import app
from volatility_explainer.marketdata.snapshots import fetch_price_history


def _yf_ticker(history: pd.DataFrame | Exception) -> MagicMock:
    mock = MagicMock()
    if isinstance(history, Exception):
        mock.history.side_effect = history
    else:
        mock.history.return_value = history
    return mock


def test_history_returns_real_closes():
    hist = pd.DataFrame(
        {"Close": [10.0, 11.0]},
        index=pd.DatetimeIndex(["2026-11-09", "2026-11-10"], name="Date"),
    )
    with patch("yfinance.Ticker", return_value=_yf_ticker(hist)):
        df = fetch_price_history("aapl", "1M")
    assert list(df["close"]) == [10.0, 11.0]


def test_history_failure_returns_no_points_not_synthetic_prices():
    with patch("yfinance.Ticker", return_value=_yf_ticker(RuntimeError("rate limited"))):
        df = fetch_price_history("AAPL")
    assert df.empty
    assert list(df.columns) == ["date", "close"]


def test_history_route_serves_an_empty_list_when_the_source_fails():
    with patch("yfinance.Ticker", return_value=_yf_ticker(pd.DataFrame())):
        res = TestClient(app).get("/v1/tickers/AAPL/history?period=6M")
    assert res.status_code == 200
    assert res.json() == {"ticker": "AAPL", "period": "6M", "points": []}
