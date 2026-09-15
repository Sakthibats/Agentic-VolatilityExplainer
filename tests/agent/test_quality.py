"""Quality checks on the model's explanation (agent/quality.py).

The DDOG case is a real production write-up (2026-09) and the reason these checks exist.
When another bad write-up turns up, add it here the same way — ideally lifted from a
VOLX_SAVE_RUNS file via scripts/quality_report.py --show — so every fix is pinned.
"""

from __future__ import annotations

from volatility_explainer.agent import quality
from volatility_explainer.tools.price import describe_move

DDOG_PRICE = {
    "ticker": "DDOG", "price": 230.05, "change_pct": 4.0, "realized_vol_annualized_pct": 58.7,
    "changes_pct": {"1d": 4.0, "1w": 8.0, "1y": 65.3},
}
NEWS = {"headlines": [
    {"ref": 1, "source": "Reuters", "url": "https://reut.example/1", "headline": "Datadog on AI demand"},
]}
NEWS_TILE = [{"agent": "news", "title": "News", "summary": "CEO upbeat.", "reasoning": "Catalyst."}]

DDOG_EXPLANATION = (
    "DDOG's 4% gain today (up 8% this week and 65% over the past year) reflects accelerating "
    "bullish momentum driven by Datadog's recent conference commentary on AI adoption and "
    "enterprise growth expansion. The company is investing in AI-powered monitoring "
    "capabilities, and CEO Olivier Pomel highlighted accelerating demand across both "
    "AI-focused and broader enterprise customers — a narrative that resonates with analyst "
    "consensus, which is 89% Buy or Strong Buy with 24% average upside potential. While the "
    "move is unusual relative to DDOG's typical daily volatility, it sits within the stock's "
    "established uptrend and is supported by sustained institutional conviction, not "
    "isolated speculation."
)


def _check(explanation: str, *, price: dict = DDOG_PRICE, query: str = "",
           tiles: list = NEWS_TILE, removed: int = 0) -> list[str]:
    return quality.check_explanation(
        explanation, ticker=price["ticker"], query=query, overview=describe_move(price),
        tool_data={"get_price_data": price, "get_news": NEWS}, tiles=tiles,
        removed_citations=removed,
    )


# ── Regression cases ─────────────────────────────────────────────────────────


def test_ddog_write_up_trips_every_failure_it_showed():
    assert _check(DDOG_EXPLANATION) == [
        quality.TOO_LONG,
        quality.REPEATS_OVERVIEW,
        quality.OVERSTATES_SIZE,
        quality.CONSENSUS_AS_CAUSE,
        quality.UNMEASURED_CLAIM,
        quality.UNCITED_CATALYST,
    ]


def test_the_intended_shape_is_clean():
    text = (
        "A move this size is ordinary for DDOG, so it needs no special explanation — the "
        "likeliest nudge was upbeat AI-demand comments from Datadog's CEO on Sep 10 [1], "
        "with medium confidence. Software stocks rose about 2% the same day, so part of it "
        "was sector-wide."
    )
    assert _check(text) == []


def test_empty_explanation_has_no_flags():
    assert _check("") == []


# ── Individual checks ────────────────────────────────────────────────────────


def test_length_is_flagged_only_past_the_limit():
    assert quality.TOO_LONG not in _check(" ".join(["word"] * quality.MAX_WORDS), tiles=[])
    assert quality.TOO_LONG in _check(" ".join(["word"] * (quality.MAX_WORDS + 1)), tiles=[])


def test_one_repeated_figure_is_coincidence_two_are_a_restatement():
    one = "Software stocks also rose 4% the same day, so this looks sector-wide."
    two = "Up 4% today and 65% this year, the stock is simply extending its run."
    assert quality.REPEATS_OVERVIEW not in _check(one, tiles=[])
    assert quality.REPEATS_OVERVIEW in _check(two, tiles=[])


def test_negated_or_non_size_unusual_is_not_a_size_claim():
    text = "No unusual driver turned up, and there was no unusual options activity either."
    assert quality.OVERSTATES_SIZE not in _check(text, tiles=[])


def test_strong_size_word_is_fine_when_the_code_agrees():
    text = "This was an unusually large drop for DDOG's normally volatile shares."
    big_day = {**DDOG_PRICE, "change_pct": -12.0, "changes_pct": {"1d": -12.0}}  # ~3.2x
    assert quality.OVERSTATES_SIZE in _check(text, tiles=[])
    assert quality.OVERSTATES_SIZE not in _check(text, price=big_day, tiles=[])


def test_consensus_is_the_answer_to_a_valuation_question():
    text = "Wall Street leans bullish, with an average price target about 24% above today's price."
    assert quality.CONSENSUS_AS_CAUSE in _check(text, tiles=[])
    assert quality.CONSENSUS_AS_CAUSE not in _check(text, query="is DDOG overvalued?", tiles=[])


def test_a_dated_rating_change_is_a_legitimate_cause():
    text = "Jefferies upgraded DDOG to Buy on Sep 10 and raised its price target to $270 [1]."
    assert quality.CONSENSUS_AS_CAUSE not in _check(text)


def test_unmeasured_forces_are_flagged():
    assert quality.UNMEASURED_CLAIM in _check("Momentum traders piled in.", tiles=[])


def test_uncited_catalyst_only_when_news_was_put_in_front_of_the_reader():
    text = "The rise was driven by upbeat comments from Datadog's CEO at a conference."
    assert quality.UNCITED_CATALYST in _check(text)
    assert quality.UNCITED_CATALYST not in _check(text, tiles=[])
    assert quality.UNCITED_CATALYST not in _check(text.replace("conference.", "conference [1]."))


def test_invalid_citation_is_reported():
    assert quality.INVALID_CITATION in _check("A short, fine sentence.", tiles=[], removed=1)
