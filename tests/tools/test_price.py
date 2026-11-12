import statistics
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
from volatility_explainer.tools.price import (
    _assess_moves,
    _compute_horizon_changes,
    _compute_realized_vol,
    _flag_text,
    _level_from_ratio,
    _regular_hours,
    _with_todays_close,
    describe_move,
    extended_hours,
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


# ---------------------------------------------------------------------------
# After the close: yfinance's history can still end at the previous session
# ---------------------------------------------------------------------------


def _sessions(closes: list[float], last_day: str = "2026-11-05") -> pd.DataFrame:
    """Daily bars the way yfinance returns them: business days, New York time."""
    index = pd.bdate_range(end=last_day, periods=len(closes), tz="America/New_York")
    return pd.DataFrame({"Close": closes}, index=index)


def _et(when: str) -> int:
    return int(pd.Timestamp(when, tz="America/New_York").timestamp())


def _fetch_with_quote(hist: pd.DataFrame, quote: dict) -> dict:
    finnhub_client = MagicMock()
    finnhub_client.get_quote.return_value = quote
    with patch("volatility_explainer.tools.price.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.finnhub.FinnhubClient", return_value=finnhub_client), \
         patch("yfinance.Ticker", return_value=MagicMock(history=MagicMock(return_value=hist))):
        return fetch_price_data("TEAM")


_CALM = [100.0 + (i % 3) * 0.5 for i in range(29)] + [100.0]  # last close 100.0 on Thu 11-05


def test_after_the_close_today_comes_from_the_quote_not_yesterdays_bar():
    # Fri 11-06, 16:30 ET: the quote has today's -16%, the history still ends Thursday.
    result = _fetch_with_quote(_sessions(_CALM), {"c": 84.0, "pc": 100.0, "t": _et("2026-11-06 16:00")})

    assert result["change_pct"] == -16.0
    assert result["changes_pct"]["1d"] == -16.0  # was Thursday's move before the fix
    assert result["move_assessment"]["overall"] == "unusual"
    # Read later than that Friday, so the session is named rather than called "today".
    assert "on Friday, down 16.0% on the day" in describe_move(result)
    # The usual-move yardstick comes from the sessions before today, not from today's drop.
    assert result["realized_vol_annualized_pct"] == _compute_realized_vol(_sessions(_CALM))


def test_every_horizon_ends_today_not_only_the_one_day_change():
    closes = [90.0] + [100.0] * 29  # one week back (5 sessions before today) is 100.0
    result = _fetch_with_quote(_sessions(closes), {"c": 110.0, "pc": 100.0, "t": _et("2026-11-06 16:00")})

    assert result["changes_pct"]["1w"] == 10.0


def test_a_quote_from_the_last_bars_session_adds_nothing():
    # The history already has Friday's bar. During market hours the last trade is intraday
    # Friday; at the weekend or before Monday's open it is still Friday's close.
    hist = _sessions([*_CALM, 84.0], last_day="2026-11-06")
    for traded_at in ("2026-11-06 11:00", "2026-11-06 16:00"):
        result = _fetch_with_quote(hist, {"c": 84.0, "pc": 100.0, "t": _et(traded_at)})
        assert result["changes_pct"]["1d"] == -16.0
        assert len(_with_todays_close(hist, {"price": 84.0, "prev_close": 100.0,
                                             "t": _et(traded_at)})) == len(hist)


def test_the_trading_day_is_read_in_new_york_time():
    # 00:30 UTC on 11-06 is still 19:30 on 11-05 in New York: the same session as the last bar.
    quote = {"price": 84.0, "prev_close": 100.0,
             "t": int(pd.Timestamp("2026-11-06 00:30", tz="UTC").timestamp())}
    hist = _sessions(_CALM)

    assert _with_todays_close(hist, quote) is hist


def test_a_history_several_sessions_stale_is_not_bridged():
    # The quote's previous close (120) isn't the last bar (100): sessions are missing between.
    hist = _sessions(_CALM)
    quote = {"price": 125.0, "prev_close": 120.0, "t": _et("2026-11-10 16:00")}

    assert _with_todays_close(hist, quote) is hist


def test_a_quote_without_a_timestamp_leaves_history_alone():
    hist = _sessions(_CALM)

    assert _with_todays_close(hist, {"price": 84.0, "prev_close": 100.0}) is hist


def test_yfinance_history_failure_with_no_finnhub_returns_error_not_exception():
    with patch("volatility_explainer.tools.price.get_settings", return_value=_fake_settings("")), \
         patch("yfinance.Ticker", return_value=MagicMock(history=MagicMock(side_effect=RuntimeError("boom")))):
        result = fetch_price_data("TEST")

    assert result["ticker"] == "TEST"
    assert "error" in result


# ---------------------------------------------------------------------------
# Outside regular hours: the last session, and pre-/post-market trades
# ---------------------------------------------------------------------------


def _info(**overrides) -> dict:
    """yfinance's info at 01:35 ET Thu 11-12: Wednesday's close plus its after-hours trade."""
    return {"regularMarketPrice": 390.84, "regularMarketTime": _et("2026-11-11 16:00"),
            "postMarketPrice": 387.15, "postMarketTime": _et("2026-11-11 19:59"),
            "preMarketPrice": None, "preMarketTime": None, **overrides}


def test_an_after_hours_trade_is_measured_from_the_close():
    assert extended_hours(_info(), 390.84) == {
        "session": "post", "price": 387.15, "change_pct": -0.94, "as_of": "2026-11-11 19:59 ET",
    }


def test_the_latest_extended_trade_wins_once_pre_market_opens():
    info = _info(preMarketPrice=395.0, preMarketTime=_et("2026-11-12 08:15"))

    assert extended_hours(info, 390.84)["session"] == "pre"
    assert extended_hours(info, 390.84)["price"] == 395.0


def test_yesterdays_after_hours_trade_is_ignored_once_the_session_trades():
    # During Thursday's session the regular trade is newer than Wednesday's after-hours one.
    info = _info(regularMarketPrice=392.0, regularMarketTime=_et("2026-11-12 11:00"))

    assert extended_hours(info, 392.0) is None


def test_no_extended_trade_when_info_is_unusable_or_from_another_session():
    assert extended_hours(None, 390.84) is None
    assert extended_hours(MagicMock(), 390.84) is None  # yfinance mocked without info
    assert extended_hours(_info(), None) is None
    # The run reports a different close (e.g. a lagging source): nothing to measure from.
    assert extended_hours(_info(), 360.0) is None


def test_regular_hours_are_weekdays_from_the_open_to_the_close_in_new_york():
    def ny(when: str) -> datetime:
        return pd.Timestamp(when, tz="America/New_York").to_pydatetime()

    assert _regular_hours(ny("2026-11-12 09:30"))
    assert _regular_hours(ny("2026-11-12 15:59"))
    assert not _regular_hours(ny("2026-11-12 09:29"))
    assert not _regular_hours(ny("2026-11-12 16:00"))
    assert not _regular_hours(ny("2026-11-14 12:00"))  # Saturday


def _fetch_off_hours(info, regular_hours: bool = False) -> tuple[dict, MagicMock]:
    yf_ticker = MagicMock(history=MagicMock(return_value=_sessions(_CALM, last_day="2026-11-11")))
    yf_ticker.info = info
    finnhub_client = MagicMock()
    finnhub_client.get_quote.return_value = {"c": 100.0, "pc": 100.5, "t": _et("2026-11-11 16:00")}
    with patch("volatility_explainer.tools.price.get_settings", return_value=_fake_settings("KEY")), \
         patch("volatility_explainer.clients.finnhub.FinnhubClient", return_value=finnhub_client), \
         patch("volatility_explainer.tools.price._regular_hours", return_value=regular_hours), \
         patch("yfinance.Ticker", return_value=yf_ticker):
        return fetch_price_data("TSLA"), yf_ticker


def test_after_hours_trade_sits_beside_the_close_and_changes_no_verdict():
    info = _info(regularMarketPrice=100.0, postMarketPrice=90.0)
    with_extended, _ = _fetch_off_hours(info)
    without, _ = _fetch_off_hours({})

    assert with_extended["extended_hours"]["change_pct"] == -10.0
    assert with_extended["price"] == 100.0
    assert with_extended["session_date"] == "2026-11-11"
    for key in ("change_pct", "changes_pct", "move_assessment", "realized_vol_annualized_pct"):
        assert with_extended[key] == without[key]
    assert "extended_hours" not in without


def test_info_is_not_fetched_during_regular_hours():
    result, yf_ticker = _fetch_off_hours(_info(regularMarketPrice=100.0), regular_hours=True)

    assert "extended_hours" not in result
    assert "info" not in {name for name, *_ in yf_ticker.mock_calls}


def _calm_price_data(**extra) -> dict:
    return {"ticker": "TSLA", "price": 390.84, "change_pct": 0.3,
            "changes_pct": {"1d": 0.3, "1w": 0.5, "1mo": 1.0},
            "realized_vol_annualized_pct": 40.0, **extra}


def test_describe_move_names_the_last_session_when_it_is_not_today():
    text = describe_move(_calm_price_data(session_date="2026-11-11", session_is_today=False))

    assert text.startswith("TSLA closed at $390.84 on Wednesday, up 0.3% on the day.")
    assert "Wednesday's move is normal for TSLA" in text
    assert "today" not in text


def test_describe_move_ends_with_the_after_hours_trade():
    extended = {"session": "post", "price": 387.15, "change_pct": -0.94, "as_of": "2026-11-11 19:59 ET"}
    text = describe_move(_calm_price_data(session_date="2026-11-11", session_is_today=True,
                                          extended_hours=extended))

    assert text.startswith("TSLA closed at $390.84, up 0.3% today.")
    assert text.endswith("After hours it is at $387.15, down 0.9% from that close.")


def test_describe_move_on_an_older_result_reads_as_before():
    assert describe_move(_calm_price_data()).startswith("TSLA is at $390.84, up 0.3% today.")
