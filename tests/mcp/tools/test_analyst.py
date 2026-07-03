from unittest.mock import MagicMock, patch

from volatility_explainer.mcp.tools import analyst


def _mock_yf_ticker(info: dict):
    yf_ticker = MagicMock()
    yf_ticker.info = info
    return yf_ticker


def test_returns_consensus_and_targets_when_covered():
    info = {
        "recommendationKey": "buy",
        "recommendationMean": 2.1,
        "numberOfAnalystOpinions": 32,
        "targetMeanPrice": 110.0,
        "targetHighPrice": 130.0,
        "targetLowPrice": 90.0,
        "currentPrice": 100.0,
    }
    with patch("yfinance.Ticker", return_value=_mock_yf_ticker(info)):
        result = analyst.fetch_analyst_sentiment("TEST")

    assert result["recommendation_key"] == "buy"
    assert result["number_of_analysts"] == 32
    assert result["target_mean_price"] == 110.0
    assert result["upside_to_target_pct"] == 10.0
    assert "error" not in result


def test_upside_pct_is_none_when_target_or_price_missing():
    info = {
        "recommendationKey": "hold",
        "targetMeanPrice": None,
        "currentPrice": 100.0,
    }
    with patch("yfinance.Ticker", return_value=_mock_yf_ticker(info)):
        result = analyst.fetch_analyst_sentiment("TEST")

    assert result["upside_to_target_pct"] is None


def test_no_coverage_returns_error_not_exception():
    info = {"recommendationKey": None, "targetMeanPrice": None}
    with patch("yfinance.Ticker", return_value=_mock_yf_ticker(info)):
        result = analyst.fetch_analyst_sentiment("SPY")

    assert result["error"] == "No analyst coverage data available for this ticker."
    assert result["ticker"] == "SPY"


def test_exception_from_yfinance_is_caught():
    with patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
        result = analyst.fetch_analyst_sentiment("TEST")

    assert result == {"ticker": "TEST", "error": "boom"}
