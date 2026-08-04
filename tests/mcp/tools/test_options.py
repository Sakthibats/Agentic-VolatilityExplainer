import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from volatility_explainer.mcp.tools import options
from volatility_explainer.mcp.tools._retry import with_retry


def _make_chain(call_strikes_ivs, put_strikes_ivs, call_vol=None, put_vol=None):
    calls = pd.DataFrame({
        "strike": [s for s, _ in call_strikes_ivs],
        "impliedVolatility": [iv for _, iv in call_strikes_ivs],
        "openInterest": [100] * len(call_strikes_ivs),
        "volume": call_vol or [0] * len(call_strikes_ivs),
    })
    puts = pd.DataFrame({
        "strike": [s for s, _ in put_strikes_ivs],
        "impliedVolatility": [iv for _, iv in put_strikes_ivs],
        "openInterest": [100] * len(put_strikes_ivs),
        "volume": put_vol or [0] * len(put_strikes_ivs),
    })
    return MagicMock(calls=calls, puts=puts)


@pytest.fixture(autouse=True)
def clear_cache():
    options._cache.clear()
    yield
    options._cache.clear()


def _mock_yf_ticker(expirations, spot, chain_by_exp):
    yf_ticker = MagicMock()
    yf_ticker.options = expirations
    yf_ticker.fast_info = MagicMock(last_price=spot, previous_close=spot)
    yf_ticker.option_chain.side_effect = lambda exp: chain_by_exp[exp]
    return yf_ticker


def test_atm_iv_is_true_average_of_call_and_put():
    exp = "2099-01-15"
    chain = _make_chain([(100.0, 0.40)], [(100.0, 0.20)])
    yf_ticker = _mock_yf_ticker([exp], spot=100.0, chain_by_exp={exp: chain})

    with patch("yfinance.Ticker", return_value=yf_ticker):
        result = options.fetch_options_data("TEST")

    # Correct average is (0.40 + 0.20) / 2 * 100 = 30.0.
    # The old buggy expression would have produced 20.0 (half of call IV only).
    assert result["atm_iv_pct"] == 30.0


def test_iv_rank_key_renamed():
    exp = "2099-01-15"
    chain = _make_chain([(100.0, 0.40), (110.0, 0.50)], [(100.0, 0.20), (90.0, 0.10)])
    yf_ticker = _mock_yf_ticker([exp], spot=100.0, chain_by_exp={exp: chain})

    with patch("yfinance.Ticker", return_value=yf_ticker):
        result = options.fetch_options_data("TEST")

    assert "iv_chain_percentile" in result
    assert "iv_rank" not in result

    empty = options._empty("TEST")
    assert "iv_chain_percentile" in empty
    assert "iv_rank" not in empty


def test_get_ticker_context_is_cached_across_calls():
    exp = "2099-01-15"
    chain = _make_chain([(100.0, 0.40)], [(100.0, 0.20)])
    yf_ticker = _mock_yf_ticker([exp], spot=100.0, chain_by_exp={exp: chain})

    with patch("yfinance.Ticker", return_value=yf_ticker) as ticker_ctor:
        options.fetch_options_data("TEST")
        options.fetch_options_data("TEST")
        assert ticker_ctor.call_count == 1
        # .options and .fast_info are only actually evaluated once each thanks
        # to the cache — MagicMock attribute access itself doesn't count calls,
        # so assert the underlying option_chain (a real call) wasn't repeated.
        assert yf_ticker.option_chain.call_count == 1


def test_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    assert with_retry(flaky, attempts=3, base_delay=0.001) == "ok"
    assert calls["n"] == 3


def test_with_retry_raises_after_exhausting_attempts():
    def always_fails():
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        with_retry(always_fails, attempts=3, base_delay=0.001)


def test_term_structure_ordering_stable_under_parallel_completion():
    exps = ["2099-01-16", "2099-01-21", "2099-01-26"]
    chains = {e: _make_chain([(100.0, 0.30)], [(100.0, 0.20)]) for e in exps}

    def slow_option_chain(exp):
        # Make the later expiries "finish" first to try to provoke
        # out-of-order completion if ordering weren't explicitly preserved.
        delay = {exps[0]: 0.05, exps[1]: 0.02, exps[2]: 0.0}[exp]
        time.sleep(delay)
        return chains[exp]

    yf_ticker = MagicMock()
    yf_ticker.options = exps
    yf_ticker.fast_info = MagicMock(last_price=100.0, previous_close=100.0)
    yf_ticker.option_chain.side_effect = slow_option_chain

    with (
        patch("yfinance.Ticker", return_value=yf_ticker),
        patch("volatility_explainer.mcp.tools.options.date") as mock_date,
    ):
        import datetime as _dt

        mock_date.today.return_value = _dt.date(2099, 1, 1)
        mock_date.fromisoformat.side_effect = lambda s: _dt.date.fromisoformat(s)
        result = options.fetch_options_positioning("TEST")

    returned_expiries = [t["expiry"] for t in result["term_structure"]]
    assert returned_expiries == exps
