from unittest.mock import MagicMock, patch

import pandas as pd
from volatility_explainer.mcp.tools import sector


def _make_hist(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(end=pd.Timestamp.today(), periods=len(closes), freq="D")
    return pd.DataFrame({"Close": closes}, index=index)


def _mock_yf_ticker(info: dict, hist: pd.DataFrame):
    yf_ticker = MagicMock()
    yf_ticker.info = info
    yf_ticker.history.return_value = hist
    return yf_ticker


def test_maps_sector_to_correct_etf_and_computes_relative_move():
    stock_hist = _make_hist([100.0, 110.0])  # +10% on 1d
    etf_hist = _make_hist([50.0, 52.0])  # +4% on 1d

    stock_ticker = _mock_yf_ticker({"sector": "Technology"}, stock_hist)
    etf_ticker = MagicMock()
    etf_ticker.history.return_value = etf_hist

    def side_effect(symbol):
        return etf_ticker if symbol == "XLK" else stock_ticker

    with patch("yfinance.Ticker", side_effect=side_effect):
        result = sector.fetch_sector_comparison("TEST")

    assert result["sector"] == "Technology"
    assert result["sector_etf"] == "XLK"
    assert result["comparison"]["1d"]["stock_change_pct"] == 10.0
    assert result["comparison"]["1d"]["sector_etf_change_pct"] == 4.0
    assert result["comparison"]["1d"]["relative_to_sector_pct"] == 6.0


def test_unknown_sector_returns_error_not_exception():
    stock_ticker = _mock_yf_ticker({"sector": "Not A Real Sector"}, _make_hist([100.0, 101.0]))

    with patch("yfinance.Ticker", return_value=stock_ticker):
        result = sector.fetch_sector_comparison("TEST")

    assert "error" in result
    assert "sector_etf" not in result


def test_missing_horizon_data_is_none_not_missing_key():
    stock_hist = _make_hist([100.0, 110.0])
    etf_hist = _make_hist([50.0, 52.0])

    stock_ticker = _mock_yf_ticker({"sector": "Technology"}, stock_hist)
    etf_ticker = MagicMock()
    etf_ticker.history.return_value = etf_hist

    def side_effect(symbol):
        return etf_ticker if symbol == "XLK" else stock_ticker

    with patch("yfinance.Ticker", side_effect=side_effect):
        result = sector.fetch_sector_comparison("TEST")

    # Only 2 days of history — 1y (needs 253 points) can't be computed, but the
    # horizon key must still be present with None values rather than dropped.
    assert result["comparison"]["1y"]["stock_change_pct"] is None
    assert result["comparison"]["1y"]["relative_to_sector_pct"] is None


def test_exception_from_yfinance_is_caught():
    with patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
        result = sector.fetch_sector_comparison("TEST")

    assert result == {"ticker": "TEST", "error": "boom"}
