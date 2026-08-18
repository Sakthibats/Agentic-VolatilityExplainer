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

    # Pin the clock: the TTL is additionally capped at midnight, so an unpinned run
    # within 15 minutes of it would see a shorter value and fail spuriously.
    with patch.object(redis_cache, "_get_client", return_value=client), \
         patch.object(redis_cache, "_seconds_until_midnight", return_value=80_000):
        redis_cache.set_cached_final_answer("AAPL", {"summary": "hi"})

    client.setex.assert_called_once_with(
        "final_answer:AAPL", redis_cache._FINAL_ANSWER_TTL_SECONDS, json.dumps({"summary": "hi"})
    )


def test_final_answer_ttl_is_capped_at_midnight():
    """A synthesized answer quotes get_events' day counts, which expire with the date."""
    client = MagicMock()

    with patch.object(redis_cache, "_get_client", return_value=client), \
         patch.object(redis_cache, "_seconds_until_midnight", return_value=120):
        redis_cache.set_cached_final_answer("AAPL", {"summary": "hi"})

    assert client.setex.call_args.args[1] == 120


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


# ---------------------------------------------------------------------------
# effective_ttl — day-scoped tools expire at midnight
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_memo():
    redis_cache.clear_memoized_tool_data()
    yield
    redis_cache.clear_memoized_tool_data()


def test_effective_ttl_is_the_configured_value_for_a_normal_tool():
    assert redis_cache.effective_ttl("get_price_data") == redis_cache.TOOL_TTL_SECONDS["get_price_data"]


def test_effective_ttl_defaults_for_an_unknown_tool():
    assert redis_cache.effective_ttl("get_nonexistent") == 900


@pytest.mark.parametrize("tool", sorted(redis_cache._DAY_SCOPED_TOOLS))
def test_day_scoped_tools_expire_at_midnight_when_that_comes_first(tool):
    """get_events and get_analyst_sentiment embed day counts ("earnings in 8 days"). Those
    are only true on the day they were computed, so the entry must not outlive the date."""
    with patch.object(redis_cache, "_seconds_until_midnight", return_value=3600):
        assert redis_cache.effective_ttl(tool) == 3600


def test_day_scoped_tool_keeps_its_shorter_configured_ttl():
    """Midnight is a ceiling, never an extension."""
    with patch.object(redis_cache, "_seconds_until_midnight", return_value=80_000):
        assert redis_cache.effective_ttl("get_analyst_sentiment") == (
            redis_cache.TOOL_TTL_SECONDS["get_analyst_sentiment"]
        )


def test_ttl_never_collapses_below_the_floor_just_before_midnight():
    with patch.object(redis_cache, "_seconds_until_midnight", return_value=3):
        assert redis_cache.effective_ttl("get_events") == redis_cache._MIN_TTL_SECONDS


def test_seconds_until_midnight_is_within_a_day():
    assert 0 < redis_cache._seconds_until_midnight() <= 86_400


def test_set_cached_tool_data_writes_the_day_scoped_ttl():
    client = MagicMock()
    pipe = MagicMock()
    client.pipeline.return_value = pipe

    with patch.object(redis_cache, "_get_client", return_value=client), \
         patch.object(redis_cache, "_seconds_until_midnight", return_value=1800):
        redis_cache.set_cached_tool_data("AAPL", {"get_events": {"events": []}})

    assert pipe.setex.call_args.args[1] == 1800  # not the configured 24h


# ---------------------------------------------------------------------------
# In-process memo — the tier that makes a Redis-less deploy sane
# ---------------------------------------------------------------------------


def test_memo_round_trips_a_result():
    redis_cache.set_memoized_tool_data("AAPL", "get_events", {"events": [1]})

    assert redis_cache.get_memoized_tool_data("AAPL", "get_events") == {"events": [1]}


def test_memo_miss_returns_none():
    assert redis_cache.get_memoized_tool_data("AAPL", "get_events") is None


def test_memo_is_scoped_per_ticker_and_per_tool():
    redis_cache.set_memoized_tool_data("AAPL", "get_events", {"a": 1})

    assert redis_cache.get_memoized_tool_data("NVDA", "get_events") is None
    assert redis_cache.get_memoized_tool_data("AAPL", "get_news") is None


def test_memo_shares_the_market_wide_key_for_macro():
    """get_macro is identical for every ticker — it must not be memoized per ticker."""
    redis_cache.set_memoized_tool_data("AAPL", "get_macro", {"vix": 20})

    assert redis_cache.get_memoized_tool_data("NVDA", "get_macro") == {"vix": 20}


def test_memo_entry_expires_after_its_ttl():
    with patch("volatility_explainer.clients.redis_cache.time.monotonic", return_value=1000.0):
        redis_cache.set_memoized_tool_data("AAPL", "get_price_data", {"price": 100})

    ttl = redis_cache.TOOL_TTL_SECONDS["get_price_data"]
    with patch("volatility_explainer.clients.redis_cache.time.monotonic", return_value=1000.0 + ttl - 1):
        assert redis_cache.get_memoized_tool_data("AAPL", "get_price_data") == {"price": 100}
    with patch("volatility_explainer.clients.redis_cache.time.monotonic", return_value=1000.0 + ttl + 1):
        assert redis_cache.get_memoized_tool_data("AAPL", "get_price_data") is None


def test_memo_is_bounded_and_evicts():
    for i in range(redis_cache._MEMO_MAX_ENTRIES + 20):
        redis_cache.set_memoized_tool_data(f"TICK{i}", "get_price_data", {"i": i})

    assert len(redis_cache._memo) <= redis_cache._MEMO_MAX_ENTRIES


def test_clear_memo_empties_it():
    redis_cache.set_memoized_tool_data("AAPL", "get_events", {"a": 1})

    redis_cache.clear_memoized_tool_data()

    assert redis_cache.get_memoized_tool_data("AAPL", "get_events") is None


def test_memo_needs_no_redis():
    """The whole point: this tier works when REDIS_URL is unset."""
    with patch.object(redis_cache, "_get_client", return_value=None):
        redis_cache.set_memoized_tool_data("AAPL", "get_events", {"a": 1})

        assert redis_cache.get_memoized_tool_data("AAPL", "get_events") == {"a": 1}
