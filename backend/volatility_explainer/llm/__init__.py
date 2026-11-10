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


def _api_key(settings: Any, name: str) -> str | None:
    return getattr(settings, f"{name}_api_key").get_secret_value() or None


def is_configured(settings: Any, name: str) -> bool:
    """Whether the server holds an API key for this vendor."""
    return name in PROVIDERS and _api_key(settings, name) is not None


def get_provider(settings: Any, name: str | None = None) -> LLMProvider:
    """A provider for `name`, or for the server default (LLM_PROVIDER) when it's None.

    The caller picks only the vendor; which model each vendor runs stays server config, so
    a client can choose between the two configured models but never name its own.
    """
    name = name or getattr(settings, "llm_provider", "anthropic") or "anthropic"
    if name == "openai":
        return build_provider(
            name, settings.openai_model, _api_key(settings, name),
            reasoning_effort=settings.openai_reasoning_effort,
        )
    return build_provider(name, settings.anthropic_model, _api_key(settings, "anthropic"))
