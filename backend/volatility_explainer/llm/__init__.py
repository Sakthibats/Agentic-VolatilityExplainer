"""LLM providers behind one interface. Production picks one with LLM_PROVIDER; the eval
harness builds them directly to compare models on the same recorded data."""

from __future__ import annotations

from typing import Any

from volatility_explainer.llm.base import LLMProvider

PROVIDERS = ("anthropic", "openai")


def build_provider(
    name: str, model: str, api_key: str | None, *, reasoning_effort: str | None = None
) -> LLMProvider:
    """reasoning_effort applies to OpenAI reasoning models only ("none", "low", "medium", ...)."""
    if name == "anthropic":
        from volatility_explainer.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model)
    if name == "openai":
        from volatility_explainer.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model, reasoning_effort=reasoning_effort or "low")
    raise ValueError(f"Unknown LLM provider {name!r}; expected one of {PROVIDERS}")


def get_provider(settings: Any) -> LLMProvider:
    """The provider and model that production is configured to use."""
    name = getattr(settings, "llm_provider", "anthropic") or "anthropic"
    if name == "openai":
        return build_provider(
            name, settings.openai_model, settings.openai_api_key.get_secret_value() or None,
            reasoning_effort=settings.openai_reasoning_effort,
        )
    return build_provider(
        name, settings.anthropic_model, settings.anthropic_api_key.get_secret_value() or None
    )
