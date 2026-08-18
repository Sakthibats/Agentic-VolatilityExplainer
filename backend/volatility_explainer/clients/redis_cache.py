"""Redis cache for investigation results — per-tool TTLs, best-effort.

If REDIS_URL is missing or unreachable, every call is a silent no-op — the app
must work uncached.

Two independent caches:
- per-tool: each tool's raw result (price, news, options, ...), cached individually
  under its own TTL (see TOOL_TTL_SECONDS and effective_ttl) — reflects how fast that
  specific data actually goes stale, rather than one flat TTL for everything. A hit
  here still lets the orchestrator run a fresh LLM synthesis against the user's
  specific query — this cache never skips the LLM call. get_macro is market-wide, not
  ticker-specific (VIX/SPX are the same for every ticker), so it's cached under one
  shared key instead of being duplicated per ticker. An in-process memo (see
  get_memoized_tool_data) sits in front of this tier under the same TTLs, so a
  deployment without Redis still avoids re-fetching every tool on every request.
- final_answer: the fully synthesized response (summary/tiles/hypotheses), keyed by
  ticker only. Only safe to use for the no-query "explain the recent price action"
  default — that path is already generic by construction, so a cache hit there can
  skip the LLM call entirely without silently ignoring a user's actual question.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from redis.exceptions import RedisError

from volatility_explainer.config import get_settings

_logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client: Any = None
_client_checked = False

_FINAL_ANSWER_PREFIX = "final_answer"
_FINAL_ANSWER_TTL_SECONDS = 900  # matches get_price_data — the freshest input it embeds

# Per-tool cache lifetime, tuned to how fast each tool's underlying data actually
# changes. Keep in sync with the tool names in orchestrator.py's _TOOL_DISPATCH.
TOOL_TTL_SECONDS: dict[str, int] = {
    "get_price_data": 900,             # 15 min  - price/realized vol moves all day
    "get_macro": 900,                  # 15 min  - VIX/SPX moves all day; shared across tickers
    "get_options_data": 1800,          # 30 min  - IV/put-call/skew snapshot drifts through the day
    "get_sector_comparison": 1800,     # 30 min  - tracks price-cadence moves vs. sector ETF
    "get_options_positioning": 3600,   # 1 hour  - max pain/OI walls settle slower than price
    "get_analyst_sentiment": 12 * 3600,  # 12 hours - ratings/price targets rarely move intraday
    "get_news": 4 * 3600,              # 4 hours - headlines don't repeat within a trading day
    "get_events": 24 * 3600,           # 24 hours - earnings/FOMC dates are static day-to-day
}

_MARKET_WIDE_TOOLS = {"get_macro"}

# Tools whose payload contains DAY COUNTS measured from the day it was fetched
# ("earnings in 8 days", "reported 3 days ago", "as_of"). Those numbers are only correct
# on the date they were computed: a get_events entry cached at 23:00 with a 24h TTL would
# still be served at 01:00 the next day, insisting earnings are 8 days out when they are
# now 7. The underlying dates really are static day-to-day — the arithmetic around them
# is not — so these entries additionally expire at midnight.
_DAY_SCOPED_TOOLS = {"get_events", "get_analyst_sentiment"}

# Never write an entry shorter than this; just before midnight a day-scoped TTL would
# otherwise collapse to a couple of seconds and every request would re-fetch.
_MIN_TTL_SECONDS = 60

# Bound on the in-process memo (see get_memoized_tool_data). Comfortably more than the
# tools x tickers a single process sees inside one TTL window.
_MEMO_MAX_ENTRIES = 512

_memo_lock = threading.Lock()
_memo: dict[str, tuple[float, Any]] = {}


def _seconds_until_midnight() -> int:
    """Seconds until the next local midnight — the same clock the tools call date.today()
    on, so the boundary matches the day counts they embedded."""
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return int((midnight - now).total_seconds())


def effective_ttl(tool_name: str) -> int:
    """The TTL actually written for a tool: its configured lifetime, additionally capped at
    the end of the day for tools that embed day counts."""
    ttl = TOOL_TTL_SECONDS.get(tool_name, 900)
    if tool_name in _DAY_SCOPED_TOOLS:
        ttl = min(ttl, _seconds_until_midnight())
    return max(ttl, _MIN_TTL_SECONDS)


def _get_client() -> Any:
    global _client, _client_checked
    if _client_checked:
        return _client
    with _client_lock:
        if _client_checked:
            return _client
        _client_checked = True
        url = get_settings().redis_url.get_secret_value()
        if url:
            import redis

            _client = redis.Redis.from_url(url, decode_responses=True)
        return _client


def _final_answer_key(ticker: str) -> str:
    return f"{_FINAL_ANSWER_PREFIX}:{ticker.upper()}"


def _tool_key(ticker: str, tool_name: str) -> str:
    if tool_name in _MARKET_WIDE_TOOLS:
        return f"MARKET_{tool_name}"
    return f"{ticker.upper()}_{tool_name}"


def get_cached_tool_data(ticker: str, tool_names: list[str]) -> dict:
    """Return a dict of {tool_name: result} for every tool_name that has a live cache entry.

    One MGET round trip for all tool_names, instead of one GET per tool.
    """
    client = _get_client()
    if client is None:
        return {}
    try:
        raw_values = client.mget([_tool_key(ticker, name) for name in tool_names])
    except (RedisError, OSError):
        _logger.exception("[redis_cache] batch read failed for %s", ticker)
        return {}
    out: dict = {}
    for name, raw in zip(tool_names, raw_values, strict=False):
        if raw is not None:
            try:
                out[name] = json.loads(raw)
            except (TypeError, ValueError):
                _logger.exception("[redis_cache] decode failed for %s/%s", ticker, name)
    return out


def set_cached_tool_data(ticker: str, tool_data: dict) -> None:
    """Store each tool's result individually, each with its own TTL.

    One pipelined round trip for all tool_data entries, instead of one SETEX per tool.
    """
    client = _get_client()
    if client is None or not tool_data:
        return
    try:
        pipe = client.pipeline(transaction=False)
        for name, result in tool_data.items():
            pipe.setex(_tool_key(ticker, name), effective_ttl(name), json.dumps(result, default=str))
        pipe.execute()
    except (RedisError, OSError, TypeError, ValueError):
        _logger.exception("[redis_cache] batch write failed for %s", ticker)


def get_memoized_tool_data(ticker: str, tool_name: str) -> dict | None:
    """In-process tier in front of Redis, under the same per-tool TTLs.

    Redis is optional by design (the app must run end-to-end with only ANTHROPIC_API_KEY),
    and without it every request re-fetched every tool from the upstream API. This makes a
    Redis-less deployment behave sanely, and when Redis IS configured it also spares the
    round trip for a ticker this process just looked at.

    Deliberately not a substitute for Redis: it is per-process, so it does not survive a
    restart or help a second instance.
    """
    with _memo_lock:
        entry = _memo.get(_tool_key(ticker, tool_name))
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            _memo.pop(_tool_key(ticker, tool_name), None)
            return None
        return value


def set_memoized_tool_data(ticker: str, tool_name: str, result: dict) -> None:
    with _memo_lock:
        if len(_memo) >= _MEMO_MAX_ENTRIES:
            now = time.monotonic()
            for key in [k for k, (expires_at, _) in _memo.items() if expires_at <= now]:
                _memo.pop(key, None)
            while len(_memo) >= _MEMO_MAX_ENTRIES:
                _memo.pop(min(_memo, key=lambda k: _memo[k][0]), None)  # soonest to expire
        _memo[_tool_key(ticker, tool_name)] = (
            time.monotonic() + effective_ttl(tool_name),
            result,
        )


def clear_memoized_tool_data() -> None:
    """Drop the in-process tier. For tests, and for anything that needs a forced refresh."""
    with _memo_lock:
        _memo.clear()


def get_cached_final_answer(ticker: str) -> dict | None:
    """Return the cached, fully-synthesized no-query result for a ticker, or None on a
    miss/unavailable cache. Only ever populated from the query-less default-explain path.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(_final_answer_key(ticker))
        if raw is None:
            return None
        return json.loads(raw)
    except (RedisError, OSError, TypeError, ValueError):
        _logger.exception("[redis_cache] final_answer read failed for %s", ticker)
        return None


def set_cached_final_answer(ticker: str, result: dict) -> None:
    """Store a fully-synthesized no-query result for a ticker (TTL: _FINAL_ANSWER_TTL_SECONDS)."""
    client = _get_client()
    if client is None:
        return
    try:
        # Also capped at midnight: a synthesized answer quotes get_events' day counts
        # ("reported 3 days ago"), which stop being true once the date rolls over.
        ttl = max(min(_FINAL_ANSWER_TTL_SECONDS, _seconds_until_midnight()), _MIN_TTL_SECONDS)
        client.setex(_final_answer_key(ticker), ttl, json.dumps(result, default=str))
    except (RedisError, OSError, TypeError, ValueError):
        _logger.exception("[redis_cache] final_answer write failed for %s", ticker)
