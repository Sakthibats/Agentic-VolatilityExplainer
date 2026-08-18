import datetime as real_datetime
from unittest.mock import patch

import pandas as pd
import pytest
from volatility_explainer.mcp.tools import analyst


def _recommendations(**periods) -> pd.DataFrame:
    """Build the DataFrame yfinance's Ticker.recommendations returns.

    Call as _recommendations(**{"0m": (6, 21, 14, 3, 2), "-3m": (7, 23, 15, 1, 2)}) —
    each tuple is (strongBuy, buy, hold, sell, strongSell).
    """
    rows = [
        {
            "period": period,
            "strongBuy": counts[0],
            "buy": counts[1],
            "hold": counts[2],
            "sell": counts[3],
            "strongSell": counts[4],
        }
        for period, counts in periods.items()
    ]
    return pd.DataFrame(rows)


def _upgrades(rows: list[dict]) -> pd.DataFrame:
    """Build the DataFrame yfinance's Ticker.upgrades_downgrades returns — indexed by
    GradeDate, with the Firm/ToGrade/FromGrade/Action/price-target columns."""
    if not rows:
        return pd.DataFrame()
    index = pd.DatetimeIndex([r.pop("date") for r in rows], name="GradeDate")
    return pd.DataFrame(rows, index=index)


def _run(today: str, *, targets=None, recommendations=None, upgrades=None, ticker="TEST"):
    """Run fetch_analyst_sentiment with the clock frozen and all three yfinance surfaces
    stubbed. Any of the three may be an Exception to simulate that surface failing."""

    def stub(value):
        def _inner(_yf_ticker):
            if isinstance(value, Exception):
                raise value
            return value

        return _inner

    with (
        patch("yfinance.Ticker"),
        patch.object(analyst, "_today", return_value=real_datetime.date.fromisoformat(today)),
        patch.object(analyst, "_fetch_price_targets", side_effect=stub(targets)),
        patch.object(analyst, "_fetch_recommendations", side_effect=stub(recommendations)),
        patch.object(analyst, "_fetch_upgrades", side_effect=stub(upgrades)),
    ):
        return analyst.fetch_analyst_sentiment(ticker)


# ── Consensus scoring ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("counts", "score", "rating", "verdict"),
    [
        ((10, 0, 0, 0, 0), 1.0, "strong_buy", "strongly bullish"),
        ((6, 21, 14, 3, 2), 2.43, "buy", "leaning bullish"),
        ((0, 10, 0, 0, 0), 2.0, "buy", "leaning bullish"),
        ((0, 0, 10, 0, 0), 3.0, "hold", "neutral"),
        ((0, 0, 0, 10, 0), 4.0, "sell", "leaning bearish"),
        ((0, 0, 0, 0, 10), 5.0, "strong_sell", "strongly bearish"),
    ],
)
def test_consensus_score_and_verdict_are_deterministic(counts, score, rating, verdict):
    result = _run("2026-07-01", recommendations=_recommendations(**{"0m": counts}))

    consensus = result["consensus"]
    assert consensus["score"] == score
    assert consensus["rating"] == rating
    assert consensus["verdict"] == verdict
    assert consensus["analysts"] == sum(counts)


def test_consensus_trend_flags_deterioration():
    """A rating can decay inside a still-bullish headline — that drift is the finding."""
    result = _run(
        "2026-07-01",
        recommendations=_recommendations(
            **{"0m": (6, 21, 14, 3, 2), "-1m": (6, 22, 14, 2, 2), "-3m": (7, 23, 15, 1, 2)}
        ),
    )

    consensus = result["consensus"]
    assert consensus["trend"] == "deteriorating"
    assert "bearish ratings 3 to 5" in consensus["trend_detail"]
    assert "3 months" in consensus["trend_detail"]


def test_consensus_trend_flags_improvement():
    result = _run(
        "2026-07-01",
        recommendations=_recommendations(**{"0m": (10, 5, 1, 0, 0), "-3m": (2, 5, 8, 1, 0)}),
    )

    assert result["consensus"]["trend"] == "improving"


def test_consensus_trend_is_stable_within_the_noise_band():
    result = _run(
        "2026-07-01",
        recommendations=_recommendations(**{"0m": (5, 10, 5, 0, 0), "-3m": (5, 10, 5, 0, 0)}),
    )

    assert result["consensus"]["trend"] == "stable"


def test_trend_uses_the_oldest_period_actually_present():
    """Yahoo does not always return four months — the trend must still work with two."""
    result = _run(
        "2026-07-01",
        recommendations=_recommendations(**{"0m": (0, 0, 0, 10, 0), "-1m": (10, 0, 0, 0, 0)}),
    )

    assert result["consensus"]["trend"] == "deteriorating"
    assert "1 months" in result["consensus"]["trend_detail"]


def test_trend_is_absent_when_only_the_current_period_exists():
    result = _run("2026-07-01", recommendations=_recommendations(**{"0m": (5, 5, 5, 0, 0)}))

    assert "trend" not in result["consensus"]


def test_period_counts_are_matched_by_label_not_row_order():
    frame = _recommendations(**{"-3m": (10, 0, 0, 0, 0), "0m": (0, 0, 0, 0, 10)})
    result = _run("2026-07-01", recommendations=frame)

    assert result["consensus"]["score"] == 5.0  # read 0m, not the first row


# ── Price targets ─────────────────────────────────────────────────────────────────


def test_price_target_reports_median_and_dispersion():
    result = _run(
        "2026-07-01",
        targets={"current": 100.0, "mean": 120.0, "median": 130.0, "high": 200.0, "low": 80.0},
    )

    target = result["price_target"]
    assert target["median"] == 130.0
    assert target["dispersion_pct"] == 100.0  # (200-80)/120
    assert target["upside_vs_mean_pct"] == 20.0
    assert target["upside_vs_median_pct"] == 30.0


def test_zero_and_nan_targets_are_treated_as_absent():
    """yfinance uses a literal 0.0 for 'no price target' — it must not become a real number."""
    result = _run(
        "2026-07-01",
        targets={"current": 100.0, "mean": 120.0, "median": None, "high": 0.0, "low": float("nan")},
    )

    target = result["price_target"]
    assert target["high"] is None
    assert target["low"] is None
    assert "dispersion_pct" not in target
    assert target["upside_vs_mean_pct"] == 20.0


def test_upside_is_omitted_when_current_price_missing():
    result = _run("2026-07-01", targets={"mean": 120.0, "median": 130.0})

    assert "upside_vs_mean_pct" not in result["price_target"]


# ── Recent rating actions ─────────────────────────────────────────────────────────


def test_recent_downgrade_with_target_cut_is_described():
    result = _run(
        "2026-07-01",
        targets={"current": 100.0, "mean": 120.0},
        upgrades=_upgrades([
            {
                "date": "2026-06-28",
                "Firm": "Jefferies",
                "ToGrade": "Underperform",
                "FromGrade": "Hold",
                "Action": "down",
                "priceTargetAction": "Lowers",
                "currentPriceTarget": 263.66,
                "priorPriceTarget": 285.56,
            }
        ]),
    )

    action = result["recent_actions"][0]
    assert action["days_ago"] == 3
    assert action["action"] == "downgrade"
    assert action["is_rating_change"] is True
    assert action["description"] == (
        "Jefferies downgraded TEST from Hold to Underperform and cut its price target "
        "from $285.56 to $263.66"
    )


def test_upgrade_with_raised_target_is_described():
    result = _run(
        "2026-07-01",
        upgrades=_upgrades([
            {
                "date": "2026-06-30",
                "Firm": "TD Cowen",
                "ToGrade": "Buy",
                "FromGrade": "Hold",
                "Action": "up",
                "priceTargetAction": "Raises",
                "currentPriceTarget": 400.0,
                "priorPriceTarget": 350.0,
            }
        ]),
    )

    assert "upgraded TEST from Hold to Buy and raised its price target" in (
        result["recent_actions"][0]["description"]
    )


def test_maintained_rating_is_not_a_rating_change():
    result = _run(
        "2026-07-01",
        upgrades=_upgrades([
            {
                "date": "2026-06-30",
                "Firm": "Needham",
                "ToGrade": "Hold",
                "FromGrade": "Hold",
                "Action": "main",
                "priceTargetAction": "Maintains",
                "currentPriceTarget": 0.0,
                "priorPriceTarget": 0.0,
            }
        ]),
    )

    action = result["recent_actions"][0]
    assert action["is_rating_change"] is False
    assert action["action"] == "maintained"
    assert "price target" not in action["description"]  # the 0.0 placeholder is not a target


def test_actions_outside_the_lookback_window_are_dropped():
    result = _run(
        "2026-07-01",
        upgrades=_upgrades([
            {"date": "2026-06-28", "Firm": "Recent", "ToGrade": "Buy", "FromGrade": "Hold",
             "Action": "up", "currentPriceTarget": 100.0, "priorPriceTarget": 90.0},
            {"date": "2026-01-05", "Firm": "Stale", "ToGrade": "Buy", "FromGrade": "Hold",
             "Action": "up", "currentPriceTarget": 100.0, "priorPriceTarget": 90.0},
        ]),
    )

    assert [a["firm"] for a in result["recent_actions"]] == ["Recent"]


def test_actions_are_capped_and_sorted_most_recent_first():
    rows = [
        {"date": f"2026-06-{day:02d}", "Firm": f"Firm{day}", "ToGrade": "Buy",
         "FromGrade": "Hold", "Action": "up", "currentPriceTarget": 100.0,
         "priorPriceTarget": 90.0}
        for day in range(20, 30)
    ]
    result = _run("2026-07-01", upgrades=_upgrades(rows))

    actions = result["recent_actions"]
    assert len(actions) == analyst._MAX_ACTIONS
    assert [a["days_ago"] for a in actions] == sorted(a["days_ago"] for a in actions)
    assert actions[0]["firm"] == "Firm29"  # most recent


def test_no_recent_actions_says_the_consensus_is_not_a_catalyst():
    result = _run(
        "2026-07-01",
        recommendations=_recommendations(**{"0m": (5, 10, 5, 0, 0)}),
        upgrades=_upgrades([]),
    )

    assert result["recent_actions"] == []
    assert "not a recent catalyst" in result["notes"][0]


# ── Coverage status and degradation ───────────────────────────────────────────────


def test_no_coverage_is_reported_as_none_not_an_error():
    """An ETF legitimately has no analysts. That must be distinguishable from a failure."""
    result = _run("2026-07-01", targets={}, recommendations=pd.DataFrame(), upgrades=pd.DataFrame())

    assert result["analyst_coverage"] == "none"
    assert "ETF or fund" in result["notes"][0]
    assert "error" not in result


def test_all_surfaces_failing_is_reported_as_unavailable():
    boom = RuntimeError("boom")
    result = _run("2026-07-01", targets=boom, recommendations=boom, upgrades=boom)

    assert result["analyst_coverage"] == "unavailable"
    assert "could not be retrieved" in result["notes"][0]


def test_one_failing_surface_does_not_suppress_the_others():
    """The three sources are wrapped separately — the old single Ticker.info call meant any
    failure took out everything."""
    result = _run(
        "2026-07-01",
        targets=RuntimeError("targets down"),
        recommendations=_recommendations(**{"0m": (5, 10, 5, 0, 0)}),
        upgrades=_upgrades([
            {"date": "2026-06-30", "Firm": "TD Cowen", "ToGrade": "Buy", "FromGrade": "Hold",
             "Action": "up", "currentPriceTarget": 400.0, "priorPriceTarget": 350.0},
        ]),
    )

    assert result["analyst_coverage"] == "covered"
    assert result["consensus"]["rating"] == "buy"
    assert result["recent_actions"][0]["firm"] == "TD Cowen"
    assert "price_target" not in result


def test_targets_alone_still_count_as_coverage():
    result = _run("2026-07-01", targets={"current": 100.0, "mean": 120.0}, recommendations=pd.DataFrame())

    assert result["analyst_coverage"] == "covered"
    assert "consensus" not in result
    assert result["price_target"]["mean"] == 120.0


def test_yfinance_import_failure_is_caught():
    with patch("yfinance.Ticker", side_effect=RuntimeError("boom")):
        result = analyst.fetch_analyst_sentiment("TEST")

    assert result["ticker"] == "TEST"
    assert result["analyst_coverage"] == "unavailable"


# ── Re-anchoring upside to the run's own price ────────────────────────────────────


def test_apply_reference_price_recomputes_upside():
    result = _run("2026-07-01", targets={"current": 80.0, "mean": 120.0, "median": 130.0})
    assert result["price_target"]["upside_vs_mean_pct"] == 50.0  # against yfinance's 80

    analyst.apply_reference_price(result, 100.0)

    target = result["price_target"]
    assert target["current_price"] == 100.0
    assert target["upside_vs_mean_pct"] == 20.0
    assert target["upside_vs_median_pct"] == 30.0


def test_apply_reference_price_drops_upside_for_a_missing_target():
    result = _run("2026-07-01", targets={"current": 80.0, "mean": 120.0, "median": None})

    analyst.apply_reference_price(result, 100.0)

    assert "upside_vs_median_pct" not in result["price_target"]
    assert result["price_target"]["upside_vs_mean_pct"] == 20.0


@pytest.mark.parametrize("price", [None, 0, 0.0, float("nan"), "not a number"])
def test_apply_reference_price_is_a_no_op_without_a_usable_price(price):
    result = _run("2026-07-01", targets={"current": 80.0, "mean": 120.0})

    analyst.apply_reference_price(result, price)

    assert result["price_target"]["current_price"] == 80.0
    assert result["price_target"]["upside_vs_mean_pct"] == 50.0


def test_apply_reference_price_is_a_no_op_without_price_targets():
    """An ETF result has no price_target section at all — must not raise."""
    result = _run("2026-07-01", targets={}, recommendations=pd.DataFrame(), upgrades=pd.DataFrame())

    assert analyst.apply_reference_price(result, 100.0) is result


def test_ticker_is_upper_cased():
    result = _run("2026-07-01", targets={"current": 100.0, "mean": 120.0}, ticker="aapl")

    assert result["ticker"] == "AAPL"
    assert result["as_of"] == "2026-07-01"
