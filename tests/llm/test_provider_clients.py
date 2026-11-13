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


# ---------------------------------------------------------------------------
# Out of credits: each vendor's own error shape becomes llm.base.OutOfCredits
# ---------------------------------------------------------------------------

import httpx  # noqa: E402
from volatility_explainer.llm.base import OutOfCredits, UserMessage  # noqa: E402

# Wire shapes as each API sends them (checked against anthropic 0.111 / openai 3.46).
ANTHROPIC_BILLING = (402, {"type": "error", "error": {
    "type": "billing_error", "message": "Your credit balance is too low to access the Anthropic API."}})
ANTHROPIC_LEGACY = (400, {"type": "error", "error": {
    "type": "invalid_request_error",
    "message": "Your credit balance is too low to access the Anthropic API."}})
OPENAI_QUOTA = (429, {"error": {"message": "You exceeded your current quota.",
                                "type": "insufficient_quota", "param": None,
                                "code": "insufficient_quota"}})
ANTHROPIC_OTHER_400 = (400, {"type": "error", "error": {
    "type": "invalid_request_error", "message": "max_tokens: must be positive"}})
OPENAI_OTHER_400 = (400, {"error": {"message": "bad", "type": "invalid_request_error",
                                    "param": None, "code": None}})


def _answering(status: int, body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body))


def _provider(monkeypatch, vendor: str, status: int, body: dict):
    """A real provider whose SDK clients talk to a mock transport answering `status`/`body`."""
    transport = _answering(status, body)
    module = anthropic_provider.anthropic if vendor == "anthropic" else openai_provider.openai
    async_name, sync_name = ("AsyncAnthropic", "Anthropic") if vendor == "anthropic" else ("AsyncOpenAI", "OpenAI")
    real_async, real_sync = getattr(module, async_name), getattr(module, sync_name)
    monkeypatch.setattr(module, async_name, lambda **kw: real_async(
        api_key="k", max_retries=0, http_client=httpx.AsyncClient(transport=transport)))
    monkeypatch.setattr(module, sync_name, lambda **kw: real_sync(
        api_key="k", max_retries=0, http_client=httpx.Client(transport=transport)))
    cls = AnthropicProvider if vendor == "anthropic" else OpenAIProvider
    return cls(api_key="k", model="m")


async def _turn(provider):
    return await provider.run_turn(system="s", history=[UserMessage("x")], tools=[], max_tokens=5)


@pytest.mark.parametrize(("vendor", "response"), [
    ("anthropic", ANTHROPIC_BILLING),
    ("anthropic", ANTHROPIC_LEGACY),
    ("openai", OPENAI_QUOTA),
])
async def test_an_empty_account_raises_out_of_credits(monkeypatch, vendor, response):
    provider = _provider(monkeypatch, vendor, *response)

    with pytest.raises(OutOfCredits) as turn_error:
        await _turn(provider)
    with pytest.raises(OutOfCredits):
        provider.complete("which ticker?", max_tokens=30)
    assert turn_error.value.vendor == vendor


@pytest.mark.parametrize(("vendor", "response"), [
    ("anthropic", ANTHROPIC_OTHER_400),
    ("openai", OPENAI_OTHER_400),
])
async def test_other_api_errors_pass_through_unchanged(monkeypatch, vendor, response):
    provider = _provider(monkeypatch, vendor, *response)

    with pytest.raises(Exception) as error:
        await _turn(provider)
    assert not isinstance(error.value, OutOfCredits)
    assert error.value.status_code == 400
