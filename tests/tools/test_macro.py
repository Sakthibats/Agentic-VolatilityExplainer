from unittest.mock import MagicMock, patch

import pandas as pd
from volatility_explainer.mcp.tools import macro


def _fake_settings(fred_key: str = ""):
    settings = MagicMock()
    settings.fred_api_key.get_secret_value.return_value = fred_key
    return settings


def _hist(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(end=pd.Timestamp.today(), periods=len(closes), freq="D")
    return pd.DataFrame({"Close": closes}, index=index)


def test_uses_fred_when_key_configured():
    fred_client = MagicMock()
    fred_client.get_series_observations.return_value = {"observations": [{"value": "18.5"}]}

    with patch("volatility_explainer.mcp.tools.macro.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.fred.FredClient", return_value=fred_client):
        result = macro.fetch_macro()

    assert result["source"] == "fred"
    assert result["series_id"] == macro.VIX_SERIES_ID
    fred_client.get_series_observations.assert_called_once_with(macro.VIX_SERIES_ID, limit=5)


def test_falls_back_to_yfinance_when_no_fred_key():
    def ticker_side_effect(symbol):
        if symbol == "^VIX":
            return MagicMock(history=MagicMock(return_value=_hist([20.0, 22.0])))
        return MagicMock(history=MagicMock(return_value=_hist([4000.0, 3960.0])))

    with patch("volatility_explainer.mcp.tools.macro.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", side_effect=ticker_side_effect):
        result = macro.fetch_macro()

    assert result["source"] == "yfinance"
    assert result["vix_current"] == 22.0
    assert result["vix_prev_close"] == 20.0
    assert result["vix_change"] == 2.0
    assert result["sp500_change_pct"] == round((3960.0 - 4000.0) / 4000.0 * 100, 2)


def test_fred_exception_falls_back_to_yfinance():
    def ticker_side_effect(symbol):
        if symbol == "^VIX":
            return MagicMock(history=MagicMock(return_value=_hist([20.0, 22.0])))
        return MagicMock(history=MagicMock(return_value=_hist([4000.0, 4040.0])))

    with patch("volatility_explainer.mcp.tools.macro.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.fred.FredClient", side_effect=RuntimeError("boom")), \
         patch("yfinance.Ticker", side_effect=ticker_side_effect):
        result = macro.fetch_macro()

    assert result["source"] == "yfinance"
    assert result["vix_current"] == 22.0


def test_yfinance_failure_returns_error_dict_not_exception():
    with patch("volatility_explainer.mcp.tools.macro.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
        result = macro.fetch_macro()

    assert result == {"error": "boom"}


def test_single_day_history_yields_none_deltas_not_crash():
    with patch("volatility_explainer.mcp.tools.macro.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", return_value=MagicMock(history=MagicMock(return_value=_hist([20.0])))):
        result = macro.fetch_macro()

    assert result["vix_current"] == 20.0
    assert result["vix_prev_close"] is None
    assert result["vix_change"] is None
    assert result["sp500_change_pct"] is None
