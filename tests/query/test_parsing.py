from unittest.mock import MagicMock, patch

import pytest
from volatility_explainer.query import parsing as p


@pytest.fixture(autouse=True)
def clear_ticker_caches():
    p._ticker_cache.clear()
    p._llm_ticker_cache.clear()
    yield
    p._ticker_cache.clear()
    p._llm_ticker_cache.clear()


def _mock_search(quotes: list[dict]):
    return MagicMock(quotes=quotes)


# ---------------------------------------------------------------------------
# parse_search_input — priority order: concept -> ticker symbol -> company
# name -> LLM fallback
# ---------------------------------------------------------------------------


def test_concept_phrase_resolves_to_mapped_etf():
    with patch("yfinance.Search", return_value=_mock_search([{"symbol": "GLD"}])):
        ticker, query, source = p.parse_search_input("what happened to gold today")

    assert ticker == "GLD"
    assert source == "concept"
    assert query == "what happened to gold today"


def test_uppercase_token_resolves_as_ticker_symbol():
    with patch("yfinance.Search", return_value=_mock_search([{"symbol": "TSLA"}])):
        ticker, _query, source = p.parse_search_input("why did TSLA drop")

    assert ticker == "TSLA"
    assert source == "ticker_symbol"


def test_company_name_resolves_when_name_starts_with_query():
    with patch("yfinance.Search", return_value=_mock_search([{"symbol": "TSLA", "shortname": "Tesla, Inc."}])):
        ticker, _query, source = p.parse_search_input("tesla")

    assert ticker == "TSLA"
    assert source == "company_name"


def test_company_name_rejects_incidental_substring_match():
    # "cake" must not resolve to CAKE via a name that merely *contains* the
    # word ("Cheesecake Factory") — only a name that *starts with* it counts.
    with patch("yfinance.Search", return_value=_mock_search(
        [{"symbol": "CAKE", "shortname": "Cheesecake Factory Incorporated"}]
    )), patch.object(p, "_resolve_ticker_llm", return_value=None):
        ticker, _query, source = p.parse_search_input("cake")

    assert ticker is None
    assert source is None


def test_falls_back_to_llm_when_no_earlier_stage_resolves():
    with patch.object(p, "_resolve_ticker", return_value=None), \
         patch.object(p, "_resolve_ticker_llm", return_value="AAPL"):
        ticker, _query, source = p.parse_search_input("how is my favorite gadget maker doing")

    assert ticker == "AAPL"
    assert source == "llm"


def test_no_match_anywhere_returns_none_ticker_and_none_source():
    with patch.object(p, "_resolve_ticker", return_value=None), \
         patch.object(p, "_resolve_ticker_llm", return_value=None):
        ticker, query, source = p.parse_search_input("please help me bake a cake")

    assert ticker is None
    assert source is None
    assert query == "please help me bake a cake"


def test_empty_input_short_circuits_without_any_lookup():
    with patch("yfinance.Search") as mock_search:
        ticker, query, source = p.parse_search_input("   ")

    assert (ticker, query, source) == (None, "", None)
    mock_search.assert_not_called()


# ---------------------------------------------------------------------------
# validate_financial_query — the out-of-scope guardrail
# ---------------------------------------------------------------------------


def test_concept_or_ticker_symbol_source_always_trusted():
    assert p.validate_financial_query("gold", "GLD", "concept") == (True, "")
    assert p.validate_financial_query("TSLA", "TSLA", "ticker_symbol") == (True, "")


def test_short_query_with_weak_source_is_trusted():
    # <=4 words is treated as a direct name/ticker lookup even for the weaker
    # company_name/llm sources.
    is_valid, _ = p.validate_financial_query("tesla", "TSLA", "company_name")
    assert is_valid is True


def test_long_sentence_with_weak_source_and_no_financial_words_is_rejected():
    # Regression case: "bake a cake" resolving to CAKE via a weak source must
    # NOT be waved through just because a ticker happened to resolve — the
    # sentence itself carries no financial intent.
    is_valid, message = p.validate_financial_query(
        "I would like to bake a cake today please", "CAKE", "company_name"
    )
    assert is_valid is False
    assert "stock and ETF price movements" in message


def test_long_sentence_with_financial_keyword_is_valid():
    is_valid, _ = p.validate_financial_query(
        "why did the stock price fall so much this quarter", "AAPL", "company_name"
    )
    assert is_valid is True


def test_concept_pattern_inside_long_sentence_is_valid_even_without_ticker():
    is_valid, _ = p.validate_financial_query(
        "I wonder what happened to the price of gold this week", None, None
    )
    assert is_valid is True


def test_unrelated_long_sentence_without_ticker_is_rejected():
    is_valid, message = p.validate_financial_query("how do I learn to bake a cake", None, None)
    assert is_valid is False
    assert "stock and ETF price movements" in message


# ---------------------------------------------------------------------------
# evaluate_query — the scope gate that runs before any network lookup
# ---------------------------------------------------------------------------


def test_out_of_scope_sentence_is_rejected_with_zero_network_calls():
    # Regression: "I want to buy a car" used to resolve "car" -> Carnival (CCL)
    # via yfinance BEFORE the guardrail fired, then chart/stats were fetched
    # for that leaked ticker. The gate must reject without any lookup.
    with patch("yfinance.Search") as mock_search, \
         patch.object(p, "_resolve_ticker_llm") as mock_llm:
        decision = p.evaluate_query("I want to buy a car")

    assert decision.in_scope is False
    assert decision.ticker is None
    assert "stock and ETF price movements" in decision.message
    mock_search.assert_not_called()
    mock_llm.assert_not_called()


def test_short_company_name_lookup_still_resolves_and_passes():
    with patch("yfinance.Search", return_value=_mock_search(
        [{"symbol": "TSLA", "shortname": "Tesla, Inc."}]
    )):
        decision = p.evaluate_query("tesla")

    assert decision.in_scope is True
    assert decision.ticker == "TSLA"
    assert decision.source == "company_name"


def test_short_unrelated_query_that_resolves_nothing_is_rejected_without_ticker():
    with patch.object(p, "_resolve_ticker", return_value=None), \
         patch.object(p, "_resolve_ticker_llm", return_value=None):
        decision = p.evaluate_query("bake a cake")

    assert decision.in_scope is False
    assert decision.ticker is None


def test_financial_sentence_passes_gate_and_reaches_resolution():
    with patch("yfinance.Search", return_value=_mock_search([{"symbol": "TSLA"}])):
        decision = p.evaluate_query("why did TSLA drop today")

    assert decision.in_scope is True
    assert decision.ticker == "TSLA"


def test_empty_query_is_out_of_scope_without_lookup():
    with patch("yfinance.Search") as mock_search:
        decision = p.evaluate_query("   ")

    assert decision.in_scope is False
    assert decision.ticker is None
    mock_search.assert_not_called()
