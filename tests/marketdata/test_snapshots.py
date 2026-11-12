"""Chart history: real prices or nothing, never stand-in data."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient
from volatility_explainer.api.app import app
from volatility_explainer.marketdata.snapshots import (
    fetch_analyst_stats,
    fetch_price_history,
    fetch_quick_stats,
)


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


def test_stats_show_the_after_hours_price_beside_the_close():
    info = {"currentPrice": 390.84, "previousClose": 379.78,
            "regularMarketPrice": 390.84, "regularMarketTime": 1_794_430_801,
            "postMarketPrice": 387.15, "postMarketTime": 1_794_445_188}
    with patch("yfinance.Ticker", return_value=MagicMock(info=info)):
        stats = fetch_quick_stats("TSLA")
    assert [(s.label, s.value, s.delta) for s in stats[:2]] == [
        ("Last Price", "$390.84", "+2.9%"),
        ("After Hours", "$387.15", "-0.9%"),
    ]


def test_history_is_served_from_the_memo_within_its_ttl():
    hist = pd.DataFrame(
        {"Close": [10.0, 11.0]},
        index=pd.DatetimeIndex(["2026-11-09", "2026-11-10"], name="Date"),
    )
    with patch("yfinance.Ticker", return_value=_yf_ticker(hist)) as ticker:
        first = fetch_price_history("AAPL", "1M")
        first.loc[0, "close"] = -1.0  # a caller's edit must not reach the cached frame
        second = fetch_price_history("aapl", "1M")
    assert ticker.call_count == 1
    assert list(second["close"]) == [10.0, 11.0]


def test_a_failed_history_fetch_is_not_cached():
    hist = pd.DataFrame({"Close": [10.0]}, index=pd.DatetimeIndex(["2026-11-10"], name="Date"))
    with patch("yfinance.Ticker", return_value=_yf_ticker(RuntimeError("rate limited"))):
        assert fetch_price_history("AAPL", "1M").empty
    with patch("yfinance.Ticker", return_value=_yf_ticker(hist)):
        assert list(fetch_price_history("AAPL", "1M")["close"]) == [10.0]


def test_both_stat_panels_share_one_info_scrape():
    info = {"currentPrice": 100.0, "previousClose": 99.0, "targetMeanPrice": 120.0}
    with patch("yfinance.Ticker", return_value=MagicMock(info=info)) as ticker:
        fetch_quick_stats("TSLA")
        stats = fetch_analyst_stats("TSLA")
    assert ticker.call_count == 1
    assert ("Mean Target", "$120.00") in [(s.label, s.value) for s in stats]


def test_a_failed_info_scrape_is_not_cached():
    broken = MagicMock()
    type(broken).info = property(lambda _self: (_ for _ in ()).throw(RuntimeError("429")))
    with patch("yfinance.Ticker", return_value=broken):
        assert [s.label for s in fetch_quick_stats("TSLA")] == ["Data"]
    with patch("yfinance.Ticker", return_value=MagicMock(info={"currentPrice": 5.0})):
        assert fetch_quick_stats("TSLA")[0].label == "Last Price"
