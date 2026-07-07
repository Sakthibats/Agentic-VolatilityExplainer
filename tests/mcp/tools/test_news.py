from unittest.mock import MagicMock, patch

from volatility_explainer.mcp.tools import news


def _fake_settings(finnhub_key: str = ""):
    settings = MagicMock()
    settings.finnhub_api_key.get_secret_value.return_value = finnhub_key
    return settings


def test_truncate_leaves_short_summary_untouched():
    assert news._truncate("short summary") == "short summary"


def test_truncate_cuts_at_word_boundary_and_appends_ellipsis():
    long_summary = "word " * 60  # well over 200 chars
    result = news._truncate(long_summary)

    assert len(result) <= len(long_summary)
    assert result.endswith("...")
    assert not result[:-3].endswith(" ")  # trimmed at the boundary, not mid-word


def test_finnhub_used_when_key_configured_and_capped_at_five():
    raw_items = [
        {"headline": f"H{i}", "summary": "s", "datetime": i, "source": "Reuters", "url": f"u{i}"}
        for i in range(8)
    ]
    finnhub_client = MagicMock()
    finnhub_client.get_company_news.return_value = raw_items

    with patch("volatility_explainer.mcp.tools.news.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.finnhub.FinnhubClient", return_value=finnhub_client):
        result = news.fetch_news("test")

    assert result["ticker"] == "TEST"
    assert len(result["headlines"]) == 5
    assert result["headlines"][0]["headline"] == "H0"


def test_falls_back_to_yfinance_when_no_finnhub_key():
    yf_news = [
        {
            "content": {
                "title": "AAPL surges",
                "summary": "short",
                "pubDate": "2026-01-01",
                "provider": {"displayName": "Bloomberg"},
                "canonicalUrl": {"url": "https://example.com/canonical"},
                "clickThroughUrl": {"url": "https://example.com/clickthrough"},
            }
        }
    ]

    with patch("volatility_explainer.mcp.tools.news.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", return_value=MagicMock(news=yf_news)):
        result = news.fetch_news("TEST")

    headline = result["headlines"][0]
    assert headline["headline"] == "AAPL surges"
    assert headline["source"] == "Bloomberg"
    # canonicalUrl preferred over clickThroughUrl when both are present.
    assert headline["url"] == "https://example.com/canonical"


def test_yfinance_url_falls_back_to_clickthrough_when_no_canonical():
    yf_news = [
        {
            "content": {
                "title": "AAPL surges",
                "summary": "short",
                "pubDate": "2026-01-01",
                "provider": {"displayName": "Bloomberg"},
                "canonicalUrl": {},
                "clickThroughUrl": {"url": "https://example.com/clickthrough"},
            }
        }
    ]

    with patch("volatility_explainer.mcp.tools.news.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", return_value=MagicMock(news=yf_news)):
        result = news.fetch_news("TEST")

    assert result["headlines"][0]["url"] == "https://example.com/clickthrough"


def test_finnhub_exception_falls_back_to_yfinance():
    yf_news = [{"content": {"title": "T", "summary": "s", "pubDate": "d", "provider": {"displayName": "R"}}}]

    with patch("volatility_explainer.mcp.tools.news.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.finnhub.FinnhubClient", side_effect=RuntimeError("boom")), \
         patch("yfinance.Ticker", return_value=MagicMock(news=yf_news)):
        result = news.fetch_news("TEST")

    assert result["headlines"][0]["headline"] == "T"


def test_yfinance_failure_returns_error_with_empty_headlines_not_exception():
    with patch("volatility_explainer.mcp.tools.news.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
        result = news.fetch_news("TEST")

    assert result["headlines"] == []
    assert result["error"] == "boom"
