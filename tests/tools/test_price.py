from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
from volatility_explainer.significance import describe_move, realized_vol
from volatility_explainer.tools.price import (
    _regular_hours,
    _with_todays_close,
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
    assert result["realized_vol_annualized_pct"] == realized_vol(_sessions(_CALM))


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
