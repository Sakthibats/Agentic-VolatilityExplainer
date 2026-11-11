"""The eval harness: replay isolation, the fixture fix-up, case sampling and the scorers.

A fake provider at the seam (llm.base.LLMProvider) drives the real loop, so nothing here
calls a model or the network.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from volatility_explainer.agent import orchestrator
from volatility_explainer.llm.base import AssistantTurn, ToolCall, Usage

from evals import replay as replay_mod
from evals.cases import bucket_holds, build_cases
from evals.report import markdown, summarise
from evals.scorers import _claimed_numbers, rank1_agreement, schema_problems, score

SUBMIT = {
    "tiles": [{"agent": "price", "title": "Price", "summary": "Down 16.2%.", "reasoning": "Move."}],
    "hypotheses": [
        {"rank": 1, "hypothesis": "Guidance cut", "evidence": "Report", "confidence": "high", "caveat": "N/A"},
        {"rank": 2, "hypothesis": "Sector selloff", "evidence": "Limited", "confidence": "low", "caveat": "N/A"},
    ],
    "explanation": "A guidance cut is the most likely cause; shares fell 16.15% while peers fell 2%.",
}


def fixture(ticker="TEAM", one_day=-3.47, quote=-16.15, bucket="move") -> dict:
    return {
        "ticker": ticker, "trading_day": "2026-11-06", "selected_as": bucket, "change_pct": quote,
        "tools": {
            "get_price_data": {
                "ticker": ticker, "price": 153.68, "prev_close": 183.29, "change_pct": quote,
                "realized_vol_annualized_pct": 52.1,
                "changes_pct": {"1d": one_day, "1w": -10.2, "2w": -17.87, "1mo": -6.38},
                "move_assessment": {"overall": "elevated", "flags": []},
            },
            "get_events": {"ticker": ticker, "events": []},
            "get_news": {"ticker": ticker, "headlines": [
                {"source": "Reuters", "url": "https://r.example/1", "headline": "Peers fell 2%"}]},
            "get_sector_comparison": {"ticker": ticker, "sector_change_pct": -2.0},
        },
    }


class ScriptedProvider:
    """Calls get_news, then submits; records which data each turn was shown."""

    name, model = "fake", "fake-model"

    def __init__(self, submit=SUBMIT):
        self.submit = submit
        self.seen: list[str] = []

    async def run_turn(self, *, system, history, tools, max_tokens, stream_tool=None, on_tool_input=None):
        self.seen.append(json.dumps([vars(h) for h in history], default=str))
        await asyncio.sleep(0)  # let concurrent replays interleave
        if len(self.seen) == 1:
            return AssistantTurn(tool_calls=[ToolCall("c1", "get_news", {"ticker": "X"})], usage=Usage())
        return AssistantTurn(tool_calls=[ToolCall("c2", "submit_analysis", self.submit)], usage=Usage())

    def complete(self, prompt, *, max_tokens):
        return ""


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """install() rewires orchestrator globals for the process; undo it after each test."""
    monkeypatch.setattr(replay_mod, "_installed", False)
    monkeypatch.setattr(orchestrator, "_TOOL_DISPATCH", dict(orchestrator._TOOL_DISPATCH))
    for name in ("get_memoized_tool_data", "set_memoized_tool_data",
                 "get_cached_tool_data", "set_cached_tool_data"):
        monkeypatch.setattr(orchestrator, name, getattr(orchestrator, name))
    for name in ("fetch_price_data", "fetch_news", "fetch_events"):
        monkeypatch.setattr(orchestrator, name, lambda *a, **k: pytest.fail("real fetcher called"))


async def test_a_replay_serves_only_the_fixture_and_completes():
    provider = ScriptedProvider()

    result = await replay_mod.replay(fixture(), "why is TEAM down?", provider)

    assert result["status"] == "complete"
    assert result["data"]["get_news"]["headlines"][0]["headline"] == "Peers fell 2%"
    assert result["usage"]["tool_rounds"] == [["get_news"]]


async def test_a_tool_missing_from_the_fixture_is_an_error_not_a_fetch():
    provider = ScriptedProvider()
    data = fixture()
    del data["tools"]["get_news"]

    result = await replay_mod.replay(data, "", provider)

    assert "not recorded" in result["data"]["get_news"]["error"]


async def test_concurrent_replays_do_not_see_each_others_data():
    a, b = ScriptedProvider(), ScriptedProvider()

    await asyncio.gather(
        replay_mod.replay(fixture(ticker="AAA"), "", a),
        replay_mod.replay(fixture(ticker="BBB"), "", b),
    )

    assert "AAA" in a.seen[0] and "BBB" not in a.seen[0]
    assert "BBB" in b.seen[0] and "AAA" not in b.seen[0]


async def test_a_provider_error_is_recorded_not_raised():
    class Broken(ScriptedProvider):
        async def run_turn(self, **kwargs):
            raise RuntimeError("rate limited")

    result = await replay_mod.replay(fixture(), "", Broken())

    assert result["status"] == "error"
    assert "rate limited" in result["error_message"]


def test_stale_one_day_change_is_replaced_by_the_quote_and_reassessed():
    price = fixture()["tools"]["get_price_data"]

    fixed = replay_mod.normalize_price(price)

    assert fixed["changes_pct"]["1d"] == -16.15
    assert fixed["move_assessment"]["overall"] == "unusual"  # -16% on a 52%-vol stock
    assert price["changes_pct"]["1d"] == -3.47  # the fixture itself is untouched


def test_a_consistent_fixture_is_left_alone():
    price = fixture(one_day=-16.15)["tools"]["get_price_data"]

    assert replay_mod.normalize_price(price) is price


def test_cases_are_deterministic_and_mix_every_bucket():
    first, second = build_cases(20, seed=1), build_cases(20, seed=1)

    assert [c.id for c in first] == [c.id for c in second]
    assert {c.bucket for c in first} == {"move", "top_mover", "control"}
    assert any(c.query == "" for c in first) and any(c.query for c in first)


def test_a_move_that_was_yesterdays_is_left_out():
    # Recorded history said -3.47% (the previous day); the quote says today was calm.
    assert not bucket_holds(fixture(one_day=-3.47, quote=-0.4, bucket="move"))
    assert bucket_holds(fixture(one_day=-3.47, quote=-16.15, bucket="move"))


def test_a_control_that_actually_moved_today_is_left_out():
    assert not bucket_holds(fixture(one_day=0.3, quote=-16.15, bucket="control"))
    assert bucket_holds(fixture(one_day=0.3, quote=0.3, bucket="control"))


def test_top_movers_and_manual_captures_are_always_kept():
    for bucket in ("top_mover", "manual"):
        assert bucket_holds(fixture(one_day=-3.47, quote=-0.4, bucket=bucket))


def _record(model: str, repairs: list[str] | None) -> dict:
    record = {"case_id": "2026-11-06/TEAM", "model": model, "status": "complete",
              "summary": "Down.", "tiles": [], "hypotheses": SUBMIT["hypotheses"],
              "usage": {}, "quality_flags": []}
    if repairs is not None:
        record["answer_repairs"] = repairs
    return {**record, "scores": score(record, fixture())}


def test_report_shows_what_the_model_got_wrong_before_the_repairs():
    records = [_record("m", ["ranks_rewritten"]), _record("m", [])]

    row = summarise(records)["m"]

    assert row["schema_valid"] == "100%"  # the reader always got a valid answer
    assert row["model_schema_valid"] == "50%"
    assert "ranks_rewritten (1)" in markdown(summarise(records), "x.jsonl")


def test_results_recorded_before_repairs_existed_report_n_a():
    assert summarise([_record("m", None)])["m"]["model_schema_valid"] == "n/a"


def test_numbers_are_grounded_at_the_precision_written():
    record = {"status": "complete", "summary": SUBMIT["explanation"], "tiles": SUBMIT["tiles"],
              "hypotheses": SUBMIT["hypotheses"], "usage": {}, "quality_flags": []}

    scores = score(record, fixture())

    # 16.15% (quote), 2% (sector), 16.2% (tile, rounds from 16.15): all in the data.
    assert scores["numbers_claimed"] == 3
    assert scores["numbers_grounded"] == 3


def test_an_invented_number_is_not_grounded():
    record = {"status": "complete", "summary": "Shares fell 23.4% on the news.", "tiles": [],
              "hypotheses": SUBMIT["hypotheses"], "usage": {}, "quality_flags": []}

    scores = score(record, fixture())

    assert scores["numbers_grounded"] == 0
    assert scores["ungrounded_examples"] == [23.4]


def test_scale_words_and_signs_are_handled():
    assert _claimed_numbers("down \u22124.1% and a $4.5 trillion scandal, target $315") == [(4.1, 1), (315.0, 0)]


def test_source_tags_other_than_numbered_citations_are_counted():
    record = {"status": "complete", "summary": "A target cut [analyst data] and a report [2].",
              "tiles": [], "hypotheses": SUBMIT["hypotheses"], "usage": {}, "quality_flags": []}

    assert score(record, fixture())["bad_citation_tags"] == 1


def test_schema_problems_catch_what_the_haiku_5_5_pilot_produced():
    record = {
        "tiles": [{"agent": a} for a in ("price", "events", "news", "sector", "analyst")],
        "hypotheses": [{"rank": 1, "confidence": "high"}, {"confidence": "low"}],
    }

    assert schema_problems(record) == ["too_many_tiles", "ranks_not_1_to_n"]


def test_rank1_agreement():
    assert rank1_agreement(["Guidance cut", "guidance cut"]) == 1.0
    assert rank1_agreement(["Guidance cut", "Sector selloff"]) == 0.0
    assert rank1_agreement(["only one"]) is None
