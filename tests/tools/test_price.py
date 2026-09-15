import statistics
from unittest.mock import MagicMock, patch

import pandas as pd
from volatility_explainer.tools.price import (
    _assess_moves,
    _compute_horizon_changes,
    _compute_realized_vol,
    _flag_text,
    _level_from_ratio,
    describe_move,
    fetch_price_data,
)


def _make_hist(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(end=pd.Timestamp.today(), periods=len(closes), freq="D")
    return pd.DataFrame({"Close": closes}, index=index)


def _fake_settings(finnhub_key: str = ""):
    settings = MagicMock()
    settings.finnhub_api_key.get_secret_value.return_value = finnhub_key
    return settings


# ---------------------------------------------------------------------------
# _compute_horizon_changes — % change per horizon
# ---------------------------------------------------------------------------


def test_horizon_changes_computed_from_correct_lookback_offsets():
    closes = [100.0] * 300
    starts = {"1d": (1, 100.0), "1w": (5, 105.0), "2w": (10, 102.0), "1mo": (21, 108.0), "1y": (252, 90.0)}
    for back, start_price in starts.values():
        closes[-1 - back] = start_price
    closes[-1] = 110.0

    result = _compute_horizon_changes(_make_hist(closes))

    for label, (_back, start_price) in starts.items():
        expected = round((110.0 - start_price) / start_price * 100, 2)
        assert result[label] == expected


def test_horizon_change_is_none_when_not_enough_history():
    # Only 30 closes available — 1y (needs 253) can't be computed.
    result = _compute_horizon_changes(_make_hist([100.0 + i for i in range(30)]))
    assert result["1y"] is None
    assert result["1d"] is not None


def test_ytd_uses_only_current_year_closes():
    today = pd.Timestamp.today()
    index = pd.DatetimeIndex(
        [pd.Timestamp(today.year - 1, 6, 1), pd.Timestamp(today.year, 1, 2), today.normalize()]
    )
    hist = pd.DataFrame({"Close": [50.0, 100.0, 120.0]}, index=index)

    result = _compute_horizon_changes(hist)

    # YTD must compare against the first close IN the current year (100.0), not
    # last year's close (50.0).
    assert result["ytd"] == round((120.0 - 100.0) / 100.0 * 100, 2)


def test_empty_closes_returns_empty_dict():
    hist = pd.DataFrame({"Close": []})
    assert _compute_horizon_changes(hist) == {}


# ---------------------------------------------------------------------------
# _compute_realized_vol — annualized realized vol from trailing ~20 days
# ---------------------------------------------------------------------------


def test_realized_vol_matches_manual_annualized_stdev():
    # Alternating +2% / -2% daily returns for 20 days (21 closes) so the
    # sample mean is exactly zero and stdev is easy to verify independently.
    closes = [100.0]
    for i in range(20):
        closes.append(closes[-1] * (1.02 if i % 2 == 0 else 0.98))

    returns = [(closes[i + 1] - closes[i]) / closes[i] for i in range(len(closes) - 1)]
    expected = round(statistics.stdev(returns) * (252 ** 0.5) * 100, 1)

    assert _compute_realized_vol(_make_hist(closes)) == expected


def test_realized_vol_none_when_fewer_than_five_closes():
    assert _compute_realized_vol(_make_hist([100.0, 101.0, 99.0])) is None


def test_realized_vol_uses_only_trailing_21_closes():
    # A wild early move outside the trailing-21 window must not affect vol.
    wild = [100.0, 200.0, 50.0, 300.0, 10.0]
    calm_tail = [100.0 + (i % 2) * 0.1 for i in range(25)]
    closes = wild + calm_tail

    calm_only = _compute_realized_vol(_make_hist(calm_tail))
    combined = _compute_realized_vol(_make_hist(closes))

    assert combined == calm_only


# ---------------------------------------------------------------------------
# _assess_moves — deterministic significance verdict (the core business logic)
# ---------------------------------------------------------------------------


def test_no_rv_returns_empty_assessment():
    assert _assess_moves({"1d": 5.0}, None) == {}
    assert _assess_moves({"1d": 5.0}, 0) == {}


def test_typical_move_produces_no_flags():
    # rv=16% annualized -> expected 1d move ~1.0%; a 0.5% move is well within it,
    # and 0.5% is also below the absolute "elevated" floor (3%) for 1d.
    result = _assess_moves({"1d": 0.5}, rv=16.0)
    assert result == {"overall": "typical", "flags": []}


def test_move_over_2x_normal_and_over_absolute_floor_is_unusual():
    # rv=20% -> expected 1mo move ~5.78%; -30% is >5x that (relative "unusual")
    # and -30% is also past the absolute "unusual" floor for 1mo (22%).
    result = _assess_moves({"1mo": -30.0}, rv=20.0)

    assert result["overall"] == "unusual"
    assert len(result["flags"]) == 1
    assert "the past month" in result["flags"][0]
    assert "-30.0%" in result["flags"][0]


def test_chronically_volatile_stock_still_flagged_by_absolute_floor():
    # A stock with 150% annualized vol makes an 18% monthly drop look "typical"
    # relative to itself (expected ~43.3%), but 18% still breaches the
    # stock-agnostic "elevated" floor (12-22%) for a 1mo move — this must not
    # be silently rubber-stamped "typical" just because it's normal for THIS stock.
    result = _assess_moves({"1mo": -18.0}, rv=150.0)

    assert result["overall"] == "elevated"
    assert len(result["flags"]) == 1
    flag = result["flags"][0]
    assert "typical relative to this stock's own typical volatility" in flag
    assert "elevated in plain magnitude terms" in flag


def test_horizon_absent_from_changes_is_skipped_not_crashed():
    result = _assess_moves({"1d": None}, rv=16.0)
    assert result == {}


def test_relative_bands_leave_an_ordinary_day_typical():
    # A 1x move (one standard deviation) happens about one day in three — not "larger than
    # usual". The case that prompted this: DDOG up 4.0% on a ~3.7% expected day, 1.08x.
    assert _level_from_ratio(1.08) == "typical"
    assert _level_from_ratio(1.49) == "typical"
    assert _level_from_ratio(1.5) == "elevated"
    assert _level_from_ratio(2.49) == "elevated"
    assert _level_from_ratio(2.5) == "unusual"


# ---------------------------------------------------------------------------
# _flag_text — exact sentence formatting
# ---------------------------------------------------------------------------


def test_flag_text_same_level_single_framing():
    text = _flag_text("1d", 5.0, expected_move=2.0, ratio=2.5, relative_level="unusual", absolute_level="unusual", level="unusual")
    assert text == "today: 5.0% — unusual for this stock (about 2.5x its normal move for that span, expected ~2.00%)"


def test_flag_text_disagreeing_levels_states_both_framings():
    text = _flag_text("1mo", -18.0, expected_move=43.3, ratio=0.42, relative_level="typical", absolute_level="elevated", level="elevated")
    assert "typical relative to this stock's own typical volatility" in text
    assert "elevated in plain magnitude terms" in text
    assert "(overall: elevated)" in text


# ---------------------------------------------------------------------------
# describe_move — the "what happened" paragraph the reader sees before any LLM output
# ---------------------------------------------------------------------------


def _price(change_pct=-4.1, changes=None, rv=20.0, **overrides) -> dict:
    return {
        "ticker": "AAPL", "price": 100.0, "change_pct": change_pct,
        "realized_vol_annualized_pct": rv, "changes_pct": changes or {}, **overrides,
    }


def test_describe_move_is_empty_without_a_usable_price():
    assert describe_move({"ticker": "AAPL", "error": "no price history available"}) == ""
    assert describe_move(_price(price=None)) == ""


def test_describe_move_states_only_the_move_when_significance_cannot_be_judged():
    assert describe_move(_price(changes={"1d": -4.1}, rv=None)) == "AAPL is at $100.00, down 4.1% today."


def test_describe_move_unusual_day_gives_the_usual_range_not_a_multiple():
    # rv=20% -> expected 1d move ~1.26%; -4.1% is ~3.25x that.
    assert describe_move(_price(changes={"1d": -4.1})) == (
        "AAPL is at $100.00, down 4.1% today. "
        "It usually moves up to about 1.3% a day, so today's move is unusually large for AAPL."
    )


def test_describe_move_calm_everywhere_says_so():
    text = describe_move(_price(change_pct=0.5, changes={"1d": 0.5, "1w": 1.0, "1mo": -2.0}))
    assert "up 0.5% today" in text
    assert "so today's move is normal for AAPL." in text
    assert "Every timeframe from today to the past year is within its normal range." in text


def test_describe_move_volatile_stock_big_day_names_both_comparisons():
    # rv=150% -> expected 1d move ~9.4%, so -8% is ordinary for THIS stock — but it still
    # clears the stock-agnostic "unusual" floor (7%) for a single day.
    text = describe_move(_price(change_pct=-8.0, changes={"1d": -8.0}, rv=150.0))
    assert "so today's move is normal for AAPL, but very large by most stocks' standards." in text


def test_describe_move_ordinary_day_for_a_volatile_stock_is_not_called_larger_than_usual():
    """The DDOG write-up that prompted the re-banding: up 4.0% against a ~3.7% usual day
    (1.08x) read "larger than usual", and an 8% week that is normal for DDOG was flagged too."""
    ddog = {
        "ticker": "DDOG", "price": 230.05, "change_pct": 4.0, "realized_vol_annualized_pct": 58.7,
        "changes_pct": {"1d": 4.0, "1w": 8.0, "1y": 65.3},
    }
    text = describe_move(ddog)
    assert text.startswith("DDOG is at $230.05, up 4.0% today. ")
    assert (
        "It usually moves up to about 3.7% a day, so today's move is normal for DDOG, "
        "but large by most stocks' standards." in text
    )
    assert "larger than usual" not in text and "x its" not in text
    assert "this week" not in text  # normal for DDOG, only "large" against the floor
    assert (
        "up 65.3% over the past year (normal for DDOG, but very large by most stocks' standards)"
        in text
    )


def test_describe_move_calm_day_still_surfaces_a_flagged_longer_horizon():
    # rv=20% -> expected 1mo move ~5.8%; -15% is ~2.6x that.
    text = describe_move(_price(change_pct=0.3, changes={"1d": 0.3, "1mo": -15.0}))
    assert "so today's move is normal for AAPL." in text
    assert "Zooming out, it is down 15.0% over the past month (unusually large for AAPL)." in text
    assert "Every timeframe" not in text


# ---------------------------------------------------------------------------
# fetch_price_data — data-source selection and fallback behavior
# ---------------------------------------------------------------------------


def _calm_hist(n: int = 30) -> pd.DataFrame:
    return _make_hist([100.0 + (i % 3) * 0.5 for i in range(n)])


def test_uses_finnhub_quote_when_key_configured():
    finnhub_client = MagicMock()
    finnhub_client.get_quote.return_value = {"c": 105.0, "pc": 100.0}

    with patch("volatility_explainer.tools.price.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.finnhub.FinnhubClient", return_value=finnhub_client), \
         patch("yfinance.Ticker", return_value=MagicMock(history=MagicMock(return_value=_calm_hist()))):
        result = fetch_price_data("test")

    assert result["price"] == 105.0
    assert result["prev_close"] == 100.0
    assert result["change_pct"] == 5.0
    assert result["realized_vol_annualized_pct"] is not None
    assert result["ticker"] == "TEST"


def test_falls_back_to_yfinance_when_no_finnhub_key():
    closes = [100.0 + (i % 3) * 0.5 for i in range(28)] + [100.0, 105.0]

    with patch("volatility_explainer.tools.price.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", return_value=MagicMock(history=MagicMock(return_value=_make_hist(closes)))):
        result = fetch_price_data("TEST")

    assert result["price"] == 105.0
    assert result["prev_close"] == 100.0
    assert result["change_pct"] == 5.0


def test_finnhub_exception_falls_back_to_yfinance():
    closes = [100.0 + (i % 3) * 0.5 for i in range(28)] + [100.0, 105.0]

    with patch("volatility_explainer.tools.price.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.finnhub.FinnhubClient", side_effect=RuntimeError("boom")), \
         patch("yfinance.Ticker", return_value=MagicMock(history=MagicMock(return_value=_make_hist(closes)))):
        result = fetch_price_data("TEST")

    assert result["price"] == 105.0
    assert result["change_pct"] == 5.0


def test_yfinance_history_failure_with_no_finnhub_returns_error_not_exception():
    with patch("volatility_explainer.tools.price.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", return_value=MagicMock(history=MagicMock(side_effect=RuntimeError("boom")))):
        result = fetch_price_data("TEST")

    assert result["ticker"] == "TEST"
    assert "error" in result
