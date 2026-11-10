"""The live contract suite's outage guard, tested offline.

The live tests skip when an upstream is down and fail only on a real shape change. That rule
lives in `_upstream_available`; if it ever swallowed real failures, the canary would go
silent, so it is pinned here without touching the network.
"""

from __future__ import annotations

import pytest
from _pytest.outcomes import Skipped
from yfinance.exceptions import YFDataException, YFRateLimitError

from tests.tools.test_live_contracts import _upstream_available, _yahoo_outage_skips


def test_a_yahoo_outage_page_is_a_skip():
    with pytest.raises(Skipped, match="yfinance is down"), _upstream_available("yfinance"):
        raise YFDataException("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***")


def test_a_yahoo_rate_limit_is_a_skip():
    with pytest.raises(Skipped, match="rate-limited"), _upstream_available("yfinance"):
        raise YFRateLimitError()


def test_any_other_yfinance_data_error_still_fails():
    with pytest.raises(YFDataException, match="unexpected column"), _upstream_available("yfinance"):
        raise YFDataException("unexpected column 'Close'")


def test_a_shape_assertion_inside_a_wrapped_test_still_fails():
    @_yahoo_outage_skips
    def shape_check():
        assert isinstance([], dict), "calendar is no longer a dict"

    with pytest.raises(AssertionError, match="no longer a dict"):
        shape_check()
