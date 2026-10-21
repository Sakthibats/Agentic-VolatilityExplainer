"""Fixture capture — selection rules and the recorded shape. No network: tools are stubbed."""

from __future__ import annotations

import json
from datetime import date

from evals import capture

DAY = date(2026, 10, 21)


def price(today_pct: float, month_pct: float = 0.0) -> dict:
    # rv 32% → expected 1d move ~2.0%: 5% today is elevated, 6% unusual, under 1% typical.
    changes = {"1d": today_pct, "1w": 0.0, "2w": 0.0, "1mo": month_pct, "1y": 0.0}
    overall = capture._today_level({"changes_pct": changes, "realized_vol_annualized_pct": 32.0})
    if month_pct:
        overall = "unusual"
    return {"changes_pct": changes, "realized_vol_annualized_pct": 32.0,
            "move_assessment": {"overall": overall}}


def mover(symbol: str, pct: float, cap: float = 50e9) -> dict:
    return {"symbol": symbol, "regularMarketChangePercent": pct, "marketCap": cap}


def test_a_move_is_judged_on_today_not_the_worst_horizon():
    # QUIET had a big month but a calm day: not a catalyst candidate, and not a clean
    # control either, since the recent shock could leak into it.
    prices = {"BIG": price(5.0), "QUIET": price(0.3, month_pct=25.0), "CALM": price(0.4)}

    picked = capture.select(prices, [], [], DAY)

    assert picked["BIG"] == "move"
    assert "QUIET" not in picked
    assert picked["CALM"] == "control"


def test_each_bucket_has_its_own_cap_so_movers_are_never_crowded_out():
    prices = {f"M{i}": price(6.0) for i in range(10)} | {f"C{i}": price(0.2) for i in range(5)}
    gainers = [mover(f"G{i}", 10 - i) for i in range(5)]
    losers = [mover(f"L{i}", -10 + i) for i in range(5)]

    picked = capture.select(prices, gainers, losers, DAY)
    reasons = list(picked.values())

    assert reasons.count("move") == capture.MOVES_PER_DAY
    assert reasons.count("control") == capture.CONTROLS_PER_DAY
    assert reasons.count("top_mover") == 2 * capture.MOVERS_PER_SIDE


def test_screener_movers_skip_small_caps_and_tickers_already_picked():
    prices = {"BIG": price(5.0)}
    gainers = [mover("TINY", 40.0, cap=1e9), mover("BIG", 9.0), mover("NEXT", 8.0)]

    picked = capture.select(prices, gainers, [], DAY)

    assert "TINY" not in picked
    assert picked["BIG"] == "move"
    assert picked["NEXT"] == "top_mover"


def test_controls_are_stable_for_a_given_day():
    prices = {f"C{i}": price(0.2) for i in range(10)}
    assert capture.select(prices, [], [], DAY) == capture.select(prices, [], [], DAY)


def test_errored_prices_are_never_picked():
    picked = capture.select({"BAD": {"error": "boom"}, "BIG": price(5.0)}, [], [], DAY)
    assert list(picked) == ["BIG"]


def test_fixture_records_every_tool_raw_including_failures(monkeypatch, tmp_path):
    def boom(inp):
        raise RuntimeError("upstream down")

    dispatch = {name: (lambda inp, n=name: {"tool": n}) for name in capture._TOOL_DISPATCH}
    dispatch["get_options_data"] = boom
    monkeypatch.setattr(capture, "_TOOL_DISPATCH", dispatch)

    tools = capture.fetch_all_tools("NFLX")
    path = capture.write_fixture(capture.build_fixture("NFLX", DAY, "move", tools), tmp_path)

    saved = json.loads(path.read_text())
    assert path == tmp_path / "2026-10-21" / "NFLX.json"
    assert set(saved["tools"]) == set(dispatch)  # every tool, not just the model's picks
    assert saved["tools"]["get_options_data"] == {"error": "upstream down"}
    assert saved["selected_as"] == "move"
    assert saved["schema"] == capture.SCHEMA_VERSION
