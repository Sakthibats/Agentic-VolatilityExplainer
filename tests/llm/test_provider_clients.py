"""How each adapter builds its SDK clients: one per provider, every network wait bounded."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from volatility_explainer.llm import anthropic_provider, openai_provider
from volatility_explainer.llm.anthropic_provider import AnthropicProvider
from volatility_explainer.llm.openai_provider import OpenAIProvider

ADAPTERS = [
    (anthropic_provider, "anthropic", "AsyncAnthropic", "Anthropic",
     lambda: AnthropicProvider(api_key="k", model="m")),
    (openai_provider, "openai", "AsyncOpenAI", "OpenAI",
     lambda: OpenAIProvider(api_key="k", model="m")),
]


@pytest.mark.parametrize(("module", "sdk", "async_cls", "_sync_cls", "build"), ADAPTERS)
def test_turns_share_one_client_with_a_timeout(monkeypatch, module, sdk, async_cls, _sync_cls, build):
    made: list[dict] = []
    monkeypatch.setattr(getattr(module, sdk), async_cls, lambda **kw: made.append(kw) or SimpleNamespace())
    provider = build()

    assert provider._client() is provider._client()
    assert len(made) == 1
    assert made[0]["timeout"] == module._TURN_TIMEOUT_SECONDS


@pytest.mark.parametrize(("module", "sdk", "_async_cls", "sync_cls", "build"), ADAPTERS)
def test_the_plain_completion_fails_fast(monkeypatch, module, sdk, _async_cls, sync_cls, build):
    # The scope gate's ticker fallback: the reader waits on it before anything is shown.
    made: list[dict] = []

    def client(**kw):
        made.append(kw)
        raise ConnectionError("stop before any request")

    monkeypatch.setattr(getattr(module, sdk), sync_cls, client)
    with pytest.raises(ConnectionError):
        build().complete("which ticker?", max_tokens=30)
    assert made[0]["timeout"] == module._COMPLETE_TIMEOUT_SECONDS
    assert made[0]["max_retries"] == 1
