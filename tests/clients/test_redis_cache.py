import json
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import RedisError
from volatility_explainer.clients import redis_cache


def _fake_settings(redis_url: str = ""):
    settings = MagicMock()
    settings.redis_url.get_secret_value.return_value = redis_url
    settings.redis_cache_ttl_seconds = 900
    return settings


@pytest.fixture(autouse=True)
def reset_client_singleton():
    redis_cache._client = None
    redis_cache._client_checked = False
    yield
    redis_cache._client = None
    redis_cache._client_checked = False


# ---------------------------------------------------------------------------
# _get_client — lazy, memoized, silent no-op when unconfigured
# ---------------------------------------------------------------------------


def test_get_client_is_none_when_redis_url_not_configured():
    with patch("volatility_explainer.clients.redis_cache.get_settings", return_value=_fake_settings("")):
        assert redis_cache._get_client() is None


def test_get_client_constructed_once_and_memoized():
    fake_client = MagicMock()
    with patch("volatility_explainer.clients.redis_cache.get_settings", return_value=_fake_settings("redis://x")), \
         patch("redis.Redis.from_url", return_value=fake_client) as from_url:
        first = redis_cache._get_client()
        second = redis_cache._get_client()

    assert first is fake_client
    assert second is fake_client
    from_url.assert_called_once()


# ---------------------------------------------------------------------------
# Key construction — get_macro is market-wide (shared across tickers)
# ---------------------------------------------------------------------------


def test_tool_key_is_market_wide_for_macro_but_per_ticker_for_others():
    assert redis_cache._tool_key("aapl", "get_macro") == "MARKET_get_macro"
    assert redis_cache._tool_key("aapl", "get_price_data") == "AAPL_get_price_data"


def test_final_answer_key_is_ticker_scoped():
    assert redis_cache._final_answer_key("aapl") == "final_answer:AAPL"


# ---------------------------------------------------------------------------
# get_cached_tool_data / set_cached_tool_data
# ---------------------------------------------------------------------------


def test_get_cached_tool_data_returns_empty_dict_when_no_client():
    with patch("volatility_explainer.clients.redis_cache.get_settings", return_value=_fake_settings("")):
        assert redis_cache.get_cached_tool_data("AAPL", ["get_price_data"]) == {}


def test_get_cached_tool_data_decodes_hits_and_skips_misses():
    client = MagicMock()
    client.mget.return_value = [json.dumps({"price": 100}), None]

    with patch.object(redis_cache, "_get_client", return_value=client):
        result = redis_cache.get_cached_tool_data("AAPL", ["get_price_data", "get_news"])

    assert result == {"get_price_data": {"price": 100}}
    client.mget.assert_called_once_with(["AAPL_get_price_data", "AAPL_get_news"])


def test_get_cached_tool_data_skips_undecodable_entry_without_raising():
    client = MagicMock()
    client.mget.return_value = ["not valid json", json.dumps({"ok": True})]

    with patch.object(redis_cache, "_get_client", return_value=client):
        result = redis_cache.get_cached_tool_data("AAPL", ["get_price_data", "get_news"])

    assert result == {"get_news": {"ok": True}}


def test_get_cached_tool_data_returns_empty_on_mget_exception():
    client = MagicMock()
    client.mget.side_effect = RedisError("boom")

    with patch.object(redis_cache, "_get_client", return_value=client):
        result = redis_cache.get_cached_tool_data("AAPL", ["get_price_data"])

    assert result == {}


def test_set_cached_tool_data_uses_per_tool_ttl_and_correct_keys():
    client = MagicMock()
    pipe = MagicMock()
    client.pipeline.return_value = pipe

    with patch.object(redis_cache, "_get_client", return_value=client):
        redis_cache.set_cached_tool_data("AAPL", {
            "get_price_data": {"price": 100},
            "get_macro": {"vix": 20},
        })

    calls = {c.args[0]: c.args for c in pipe.setex.call_args_list}
    assert calls["AAPL_get_price_data"] == ("AAPL_get_price_data", redis_cache.TOOL_TTL_SECONDS["get_price_data"], json.dumps({"price": 100}))
    assert calls["MARKET_get_macro"] == ("MARKET_get_macro", redis_cache.TOOL_TTL_SECONDS["get_macro"], json.dumps({"vix": 20}))
    pipe.execute.assert_called_once()


def test_set_cached_tool_data_noop_when_no_client_and_no_tool_data():
    with patch("volatility_explainer.clients.redis_cache.get_settings", return_value=_fake_settings("")):
        redis_cache.set_cached_tool_data("AAPL", {"get_price_data": {}})  # must not raise

    client = MagicMock()
    with patch.object(redis_cache, "_get_client", return_value=client):
        redis_cache.set_cached_tool_data("AAPL", {})
    client.pipeline.assert_not_called()


def test_set_cached_tool_data_swallows_pipeline_exception():
    client = MagicMock()
    client.pipeline.side_effect = RedisError("boom")

    with patch.object(redis_cache, "_get_client", return_value=client):
        redis_cache.set_cached_tool_data("AAPL", {"get_price_data": {}})  # must not raise


# ---------------------------------------------------------------------------
# get_cached_final_answer / set_cached_final_answer
# ---------------------------------------------------------------------------


def test_final_answer_roundtrip_uses_ticker_key_and_ttl():
    client = MagicMock()

    with patch.object(redis_cache, "_get_client", return_value=client):
        redis_cache.set_cached_final_answer("AAPL", {"summary": "hi"})

    client.setex.assert_called_once_with(
        "final_answer:AAPL", redis_cache._FINAL_ANSWER_TTL_SECONDS, json.dumps({"summary": "hi"})
    )


def test_final_answer_get_returns_none_on_miss():
    client = MagicMock()
    client.get.return_value = None

    with patch.object(redis_cache, "_get_client", return_value=client):
        assert redis_cache.get_cached_final_answer("AAPL") is None


def test_final_answer_get_returns_none_when_no_client():
    with patch.object(redis_cache, "_get_client", return_value=None):
        assert redis_cache.get_cached_final_answer("AAPL") is None


def test_final_answer_get_decodes_hit():
    client = MagicMock()
    client.get.return_value = json.dumps({"summary": "hi"})

    with patch.object(redis_cache, "_get_client", return_value=client):
        assert redis_cache.get_cached_final_answer("AAPL") == {"summary": "hi"}
