"""List prices per million tokens, used to put a dollar figure on every run.

Standard (non-batch) rates from each vendor's pricing page, checked 2026-11-09. Haiku 5.5 is
tiered: these are its rates for prompts up to 100K tokens, which every investigation stays
well under. cache_write is Anthropic's 5-minute cache write; OpenAI caches automatically and
charges nothing to write. Prices change: update this table and its date together.
"""

from __future__ import annotations

from volatility_explainer.llm.base import Usage

# model id prefix → $ per 1M tokens
PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "cache_read": 0.10, "cache_write": 1.25, "output": 5.00},
    "claude-haiku-5-5": {"input": 0.10, "cache_read": 0.01, "cache_write": 0.125, "output": 0.50},
    "gpt-6-luna":       {"input": 0.10, "cache_read": 0.01, "cache_write": 0.0, "output": 0.50},
}


def _rates(model: str) -> dict[str, float] | None:
    # Longest prefix wins, so a dated snapshot id ("claude-haiku-4-5-20251001") finds its family.
    matches = [prefix for prefix in PRICES if model.startswith(prefix)]
    return PRICES[max(matches, key=len)] if matches else None


def cost_usd(model: str, usage: Usage) -> float | None:
    """Dollar cost of the given usage, or None for a model missing from the table."""
    rates = _rates(model)
    if rates is None:
        return None
    total = (
        usage.input_tokens * rates["input"]
        + usage.cache_read_tokens * rates["cache_read"]
        + usage.cache_write_tokens * rates["cache_write"]
        + usage.output_tokens * rates["output"]
    )
    return round(total / 1_000_000, 6)
