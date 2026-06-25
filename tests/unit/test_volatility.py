import pytest

from volatility_explainer.domain.volatility import iv_rank


def test_iv_rank_midpoint() -> None:
    assert iv_rank(25.0, 30.0, 20.0) == 50.0


def test_iv_rank_at_high() -> None:
    assert iv_rank(30.0, 30.0, 20.0) == 100.0


def test_iv_rank_flat_range_returns_zero() -> None:
    assert iv_rank(25.0, 25.0, 25.0) == 0.0
