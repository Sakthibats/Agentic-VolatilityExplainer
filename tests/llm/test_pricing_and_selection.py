"""Cost per run and provider selection: the two things the eval reads from every result."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from volatility_explainer.llm import build_provider, get_provider, is_configured
from volatility_explainer.llm.anthropic_provider import AnthropicProvider
from volatility_explainer.llm.base import Usage
from volatility_explainer.llm.pricing import cost_usd


def test_cost_prices_each_token_kind_at_its_own_rate():
    usage = Usage(input_tokens=1_000_000, cache_read_tokens=1_000_000,
                  cache_write_tokens=1_000_000, output_tokens=1_000_000)

    assert cost_usd("claude-haiku-5-5", usage) == pytest.approx(0.10 + 0.01 + 0.125 + 0.50)


def test_a_dated_snapshot_id_is_priced_as_its_model_family():
    usage = Usage(input_tokens=2_000, output_tokens=1_000)

    assert cost_usd("claude-haiku-4-5-20251001", usage) == pytest.approx(0.002 + 0.005)


def test_reasoning_tokens_are_not_charged_twice():
    # They are already inside output_tokens.
    with_reasoning = Usage(output_tokens=1_000, reasoning_tokens=800)

    assert cost_usd("gpt-6-luna", with_reasoning) == cost_usd("gpt-6-luna", Usage(output_tokens=1_000))


def test_an_unpriced_model_costs_none_rather_than_zero():
    assert cost_usd("some-new-model", Usage(input_tokens=10)) is None


def _settings(**overrides):
    base = {
        "llm_provider": "anthropic",
        "anthropic_api_key": SimpleNamespace(get_secret_value=lambda: "a-key"),
        "anthropic_model": "claude-haiku-4-5-20251001",
        "openai_api_key": SimpleNamespace(get_secret_value=lambda: "o-key"),
        "openai_model": "gpt-6-luna",
        "openai_reasoning_effort": "low",
    }
    return SimpleNamespace(**{**base, **overrides})


def test_production_defaults_to_claude():
    provider = get_provider(_settings())

    assert isinstance(provider, AnthropicProvider)
    assert (provider.name, provider.model) == ("anthropic", "claude-haiku-4-5-20251001")


def test_settings_without_a_provider_field_still_get_claude():
    settings = _settings()
    del settings.llm_provider

    assert get_provider(settings).name == "anthropic"


def test_an_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_provider("mystery", "m", None)


def test_a_requested_vendor_overrides_the_default():
    provider = get_provider(_settings(), "openai")

    assert (provider.name, provider.model) == ("openai", "gpt-6-luna")


def test_a_vendor_counts_as_configured_only_with_a_key():
    no_openai_key = _settings(openai_api_key=SimpleNamespace(get_secret_value=lambda: ""))

    assert is_configured(no_openai_key, "anthropic")
    assert not is_configured(no_openai_key, "openai")
    assert not is_configured(_settings(), "mystery")
