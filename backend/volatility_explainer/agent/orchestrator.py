"""Agent orchestrator — Claude-driven tool-use loop for financial investigation."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from typing import Any

import anthropic
from volatility_explainer.agent.prompts import SYSTEM_PROMPT
from volatility_explainer.agent.quality import check_explanation
from volatility_explainer.agent.tool_schemas import TERMINAL_TOOLS, TOOL_DEFINITIONS
from volatility_explainer.clients.redis_cache import (
    get_cached_tool_data,
    get_memoized_tool_data,
    set_cached_tool_data,
    set_memoized_tool_data,
)
from volatility_explainer.config import get_settings
from volatility_explainer.tools.analyst import apply_reference_price, fetch_analyst_sentiment
from volatility_explainer.tools.events import fetch_events
from volatility_explainer.tools.macro import fetch_macro
from volatility_explainer.tools.news import fetch_news
from volatility_explainer.tools.options import fetch_options_data, fetch_options_positioning
from volatility_explainer.tools.price import describe_move, fetch_price_data
from volatility_explainer.tools.sector import fetch_sector_comparison

# Set VOLX_LOG_LLM_PAYLOAD=1 for per-turn LLM diagnostics: payload sizes, the content-block
# breakdown, and a full dump of the system/tools/messages sent to the model. Off by default;
# timing, token usage, and cache hits are always printed.
_LOG_LLM_PAYLOAD = os.environ.get("VOLX_LOG_LLM_PAYLOAD") == "1"

# Set VOLX_SAVE_RUNS=path/to/runs.jsonl to append every finished run — its text, tool data
# and quality flags — to that file, for scripts/quality_report.py and new regression cases
# in tests/agent/test_quality.py. Off by default; meant for local runs, not production.
_SAVE_RUNS_PATH = os.environ.get("VOLX_SAVE_RUNS") or None

_TOOL_DISPATCH: dict[str, Any] = {
    "get_price_data":          lambda inp: fetch_price_data(inp["ticker"]),
    "get_news":                lambda inp: fetch_news(inp["ticker"]),
    "get_options_data":        lambda inp: fetch_options_data(inp["ticker"]),
    "get_options_positioning": lambda inp: fetch_options_positioning(inp["ticker"]),
    "get_analyst_sentiment":   lambda inp: fetch_analyst_sentiment(inp["ticker"]),
    "get_sector_comparison":   lambda inp: fetch_sector_comparison(inp["ticker"]),
    "get_macro":               lambda _: fetch_macro(),
    "get_events":              lambda inp: fetch_events(inp["ticker"]),
}

_MAX_TURNS = 7

# Ceiling on any single tool fetch. Measured tool times are 90-700ms; the retry helper in
# tools/_retry.py can add roughly another second. 15s is far above anything healthy,
# which is the point — it exists to break a hang, not to trim the p99.
_TOOL_TIMEOUT_SECONDS = 15.0

# Fetched deterministically, in parallel, before the first LLM turn. A tool earns a place
# here only if it is needed on essentially every investigation AND informs the FIRST
# tool-selection decision — otherwise it belongs in the model's hands.
#   get_price_data — move_assessment is the input to every subsequent choice.
#   get_events     — whether the stock just reported, or is about to, is what decides
#                    whether the catalyst check is news or earnings; the model cannot make
#                    that call on turn one without it. It also carries the ex-dividend date,
#                    which stops a mechanical drop being explained as a news event — no use
#                    if the model never thinks to ask for it.
# Their fetches overlap, so the batch costs max(), not sum(): measured at ~0ms marginal
# wall time over the price fetch alone, and it saves a whole LLM round trip.
_PREFETCH_TOOLS: tuple[str, ...] = ("get_price_data", "get_events")

# submit_analysis's why-paragraph — the one field streamed to the reader as it is written.
# Surfaced as the result's `summary`; see tool_schemas.py for why it is the LAST property.
_STREAMED_FIELD = "explanation"


def _fetch_with_cache(name: str, ticker: str, fetch_fn: Callable[[], dict]) -> tuple[dict, bool]:
    """Check the caches for this one tool's result before calling its live fetch_fn.

    Two tiers, both under the same per-tool TTL: an in-process memo first (no network at
    all, and the only tier that exists when Redis is not configured), then Redis. Lookup
    happens tool-by-tool, right when a tool is about to be used — not as one big upfront
    batch — so a tool the investigation never needs is never checked at all.

    Returns (result, was_cache_hit). A miss fetches fresh and populates both tiers
    immediately so the next request for this ticker can hit.
    """
    memoized = get_memoized_tool_data(ticker, name)
    if memoized is not None:
        return memoized, True

    cached = get_cached_tool_data(ticker, [name])
    if name in cached:
        set_memoized_tool_data(ticker, name, cached[name])
        return cached[name], True

    result = fetch_fn()
    set_cached_tool_data(ticker, {name: result})
    set_memoized_tool_data(ticker, name, result)
    return result, False


def _execute_tool(name: str, inputs: dict, ticker: str) -> tuple[dict, bool]:
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}, False
    try:
        return _fetch_with_cache(name, ticker, lambda: fn(inputs))
    except Exception as exc:
        return {"error": str(exc)}, False


def _run_tool_timed(name: str, inputs: dict, ticker: str) -> tuple[str, dict, bool, float]:
    """_execute_tool with its own wall-clock timing, for the per-tool diagnostics."""
    t0 = time.perf_counter()
    result, hit = _execute_tool(name, inputs, ticker)
    return name, result, hit, time.perf_counter() - t0


async def _run_tool_guarded(name: str, inputs: dict, ticker: str) -> tuple[str, dict, bool, float]:
    """_run_tool_timed on a worker thread, under a deadline.

    Tools fan out with asyncio.gather, which waits for ALL of them — so without a ceiling
    one unresponsive upstream holds the whole turn, and the SSE stream behind it, open
    indefinitely. Every tool here normally answers in well under a second; the timeout is a
    hang-breaker, not a latency target. On expiry the model is handed an error for that one
    tool and the investigation continues on whatever else returned.

    The worker thread is not actually cancelled — that is a property of to_thread, not an
    oversight. It runs to completion in the background, and if it does eventually succeed
    its cache write still lands, so the next request for this ticker benefits from it.
    """
    t0 = time.perf_counter()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_tool_timed, name, inputs, ticker),
            timeout=_TOOL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        elapsed = time.perf_counter() - t0
        print(f"[agent] {name:<25} TIMED OUT after {_TOOL_TIMEOUT_SECONDS:.0f}s — continuing without it")
        return (
            name,
            {"error": f"{name} timed out after {_TOOL_TIMEOUT_SECONDS:.0f}s"},
            False,
            elapsed,
        )


def _with_price_context(name: str, result: dict, tool_data: dict) -> dict:
    """Re-anchor a tool's price-relative numbers to the ONE price this run is built on.

    get_analyst_sentiment computes upside against yfinance's `current`, while the summary
    quotes get_price_data's price (Finnhub when configured). Intraday those diverge, and a
    write-up that names two different prices for one stock is simply wrong. Applied to
    cache hits too — see analyst.apply_reference_price for why that matters.
    """
    if name != "get_analyst_sentiment":
        return result
    return apply_reference_price(result, (tool_data.get("get_price_data") or {}).get("price"))


def _with_news_refs(name: str, result: dict) -> dict:
    """Number get_news's linked headlines 1..n as `ref`, so the model can cite one as [n]
    and the server can map that number back to the real link (see _resolve_citations).

    Returns a copy — `result` may be the very object held in the in-process memo. Applied to
    cache hits too, and idempotent.
    """
    if name != "get_news" or not result.get("headlines"):
        return result
    numbered, ref = [], 0
    for original in result["headlines"]:
        headline = {k: v for k, v in original.items() if k != "ref"}
        if headline.get("url"):
            ref += 1
            headline["ref"] = ref
        numbered.append(headline)
    return {**result, "headlines": numbered}


def _with_run_context(name: str, result: dict, tool_data: dict) -> dict:
    """Every per-run adjustment a tool result gets before the model — or the reader — sees it."""
    return _with_news_refs(name, _with_price_context(name, result, tool_data))


# Labels for the LLM turns themselves. These are emitted BEFORE the call they describe,
# which is the whole point: a step stays on screen until the NEXT one arrives, so a label
# emitted after its work reports time that has already elapsed — and silently charges its
# own duration to whichever label came before it. The final synthesis turn is the single
# longest step in a run (~10s), and it used to be attributed to whatever tool the model
# happened to name last, making that tool look broken.
_STEP_DECIDING = "Deciding what to investigate..."
_STEP_SYNTHESIZING = "Synthesizing findings..."

_STEP_LABELS: dict[str, str] = {
    "get_price_data":          "Pulling price data...",
    "get_news":                "Scanning recent news headlines...",
    "get_options_data":        "Checking options market mood...",
    "get_options_positioning": "Checking what options traders expect next...",
    "get_analyst_sentiment":   "Checking analyst ratings and price targets...",
    "get_sector_comparison":   "Comparing against sector peers...",
    "get_macro":               "Checking broader market context...",
    "get_events":              "Checking earnings dates and upcoming catalysts...",
}


def _partial_json_string(buffer: str, field: str) -> str | None:
    """Pull a top-level string field out of a JSON object that is still being streamed.

    The model streams submit_analysis's input as raw JSON fragments, so mid-flight the
    buffer is unparseable (`{..., "explanation": "AAPL fell because a supp`). This reads the
    value of `field` out of that partial text so it can be rendered as it is written,
    rather than after the whole payload lands. Returns None until the field's opening
    quote has arrived.

    Escapes are decoded via json.loads on the isolated value, and a trailing half-written
    escape (`\\u00` with the rest still in flight) is trimmed until it parses — so the
    caller never sees a mangled character.
    """
    key = f'"{field}"'
    start = buffer.find(key)
    if start == -1:
        return None
    colon = buffer.find(":", start + len(key))
    if colon == -1:
        return None

    i = colon + 1
    while i < len(buffer) and buffer[i].isspace():
        i += 1
    if i >= len(buffer) or buffer[i] != '"':
        return None  # value hasn't started (or isn't a string)

    chars: list[str] = []
    escaped = False
    for char in buffer[i + 1 :]:
        if escaped:
            chars.append(char)
            escaped = False
        elif char == "\\":
            chars.append(char)
            escaped = True
        elif char == '"':
            break  # closing quote — the value is complete
        else:
            chars.append(char)

    raw = "".join(chars)
    while raw:
        try:
            return json.loads(f'"{raw}"')
        except ValueError:
            raw = raw[:-1]  # trailing escape still arriving — drop it and retry
    return ""


def _attach_news_citations(tiles: list[dict], tool_data: dict) -> list[dict]:
    """Attach numbered {number, source, url} citations to the news tile, sourced directly
    from get_news's headlines — not from the LLM — so links are always real, never
    hallucinated. Up to the first 3 linked headlines, numbered by their `ref`, so a [2] in
    the explanation and [2] on the tile are the same article.
    """
    headlines = (tool_data.get("get_news") or {}).get("headlines") or []
    linked = [h for h in headlines if h.get("ref")][:3]
    citations = [
        {"number": h["ref"], "source": h.get("source") or "Source", "url": h["url"]}
        for h in linked
    ]
    if not citations:
        return tiles
    for tile in tiles:
        if isinstance(tile, dict) and tile.get("agent") == "news":
            tile["citations"] = citations
            break
    return tiles


_CITATION_MARKER = re.compile(r"\s*\[(\d+)\]")


def _resolve_citations(explanation: str, tool_data: dict) -> tuple[str, list[dict], int]:
    """Turn the explanation's [n] markers into real citations.

    The model writes only a number. Each is looked up among this run's numbered get_news
    headlines (see _with_news_refs): a match keeps its marker and yields a citation carrying
    the headline's real link; a number that matches nothing is removed from the text rather
    than shown. Returns (text, citations in number order, count of markers removed).
    """
    refs = {
        h["ref"]: h
        for h in (tool_data.get("get_news") or {}).get("headlines") or []
        if isinstance(h, dict) and h.get("ref")
    }
    cited: dict[int, dict] = {}
    removed = 0

    def resolve(match: re.Match[str]) -> str:
        nonlocal removed
        number = int(match.group(1))
        headline = refs.get(number)
        if headline is None:
            removed += 1
            return ""
        cited[number] = {
            "number": number, "source": headline.get("source") or "Source", "url": headline["url"],
        }
        return match.group(0)

    text = _CITATION_MARKER.sub(resolve, explanation)
    return text, [cited[n] for n in sorted(cited)], removed


def _save_run(record: dict) -> None:
    """Append one finished run to the VOLX_SAVE_RUNS file, as a JSON line."""
    with open(_SAVE_RUNS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


async def run_explainer(
    ticker: str,
    query: str = "",
    on_step: Callable[[str], None] | None = None,
    on_summary: Callable[[str], None] | None = None,
    on_overview: Callable[[str], None] | None = None,
) -> dict:
    """Run the investigation: a deterministic parallel pre-fetch of _PREFETCH_TOOLS (price —
    non-negotiable, it also feeds the sideline chart — plus events), then a Claude-driven
    loop whose first turn is the real tool-selection layer. Informed by move_assessment, the
    event calendar and the user's question, it picks whichever of
    news/options/macro/analyst/sector genuinely help and calls them together in one turn. A
    second round only happens if the first round's results specifically warrant deeper
    digging; most investigations resolve in the first round.

    Async architecture: LLM turns (the long poles) are awaited natively; tool fetches stay
    sync — every tool can fall back to yfinance, which is sync-only — and run quarantined
    on worker threads, fanned out per turn with asyncio.gather. The event loop is never
    blocked, so many investigations can run concurrently in one process.

    Every tool fetch checks Redis right before calling it (see _fetch_with_cache) — there is
    no upfront bulk cache lookup, so a tool the investigation never needs is never checked.

    The write-up reaches the reader in two paragraphs, in the order they can honestly be
    known. on_overview fires once, right after the pre-fetch, with the deterministic "what
    happened" paragraph (tools/price.describe_move) — no LLM involved. on_summary then
    receives submit_analysis's `explanation` (the "why") as it is written, which the schema
    places after tiles and hypotheses so it is generated from them rather than ahead of
    them. on_summary is called with the cumulative text each time, not a delta, so a dropped
    call cannot corrupt it.
    """
    ticker = ticker.upper()
    run_t0 = time.perf_counter()

    settings = get_settings()
    api_key = settings.anthropic_api_key.get_secret_value() or None
    client = anthropic.AsyncAnthropic(api_key=api_key)

    tool_data: dict[str, dict] = {}
    cache_hit_names: set[str] = set()
    llm_time = 0.0
    tool_time = 0.0

    # ── Deterministic pre-fetch — skip the LLM round trip for tools we always need ──
    if on_step:
        for name in _PREFETCH_TOOLS:
            on_step(_STEP_LABELS[name])

    batch_t0 = time.perf_counter()
    # One worker thread each, overlapped — the batch costs the slowest, not the sum.
    prefetched = await asyncio.gather(
        *(_run_tool_guarded(name, {"ticker": ticker}, ticker) for name in _PREFETCH_TOOLS)
    )
    tool_time += time.perf_counter() - batch_t0  # wall time of the batch, not the sum
    for name, result, hit, elapsed in prefetched:
        tool_data[name] = _with_run_context(name, result, tool_data)
        if hit:
            cache_hit_names.add(name)
        print(f"[agent] {name:<25} {elapsed * 1000:6.0f}ms  {'(cached, redis)' if hit else '(deterministic)'}")

    # The "what happened" paragraph, straight from code — on screen while the model is still
    # choosing tools, so the why-paragraph can take the time to be written last.
    overview = describe_move(tool_data.get("get_price_data") or {})
    if overview and on_overview:
        on_overview(overview)

    if query:
        user_content = (
            f"Investigate {ticker}. The user's question, which your explanation must directly "
            f"answer: \"{query}\""
        )
    else:
        user_content = f"Investigate {ticker} — explain the recent price action."
    if overview:
        # The model must know exactly what the reader has already seen, or it restates it.
        user_content += (
            f"\n\nThe reader has already been shown this factual overview, computed from the "
            f"price data: \"{overview}\" Your explanation appears directly beneath it."
        )

    messages: list[dict] = [{"role": "user", "content": user_content}]

    # Splice the deterministically pre-fetched results in as a real assistant tool_use /
    # user tool_result turn — this is the exact format the model already handles reliably
    # for genuine tool calls, so it reads pre-fetched data the same way it reads its own.
    if tool_data:
        assistant_blocks = [
            {"type": "tool_use", "id": f"toolu_prefetch_{name}", "name": name, "input": {"ticker": ticker}}
            for name in tool_data
        ]
        result_blocks = [
            {"type": "tool_result", "tool_use_id": f"toolu_prefetch_{name}", "content": json.dumps(result, default=str)}
            for name, result in tool_data.items()
        ]
        messages.append({"role": "assistant", "content": assistant_blocks})
        messages.append({"role": "user", "content": result_blocks})

    # system is a single static block across every turn of this run (and identical across
    # runs) — mark it cacheable so only the growing tool-result tail gets re-processed each
    # turn. TOOL_DEFINITIONS carries its own cache_control on its last entry.
    system_blocks = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    final_kind: str | None = None  # "analysis" | "guardrail" | None (ran out of turns)
    final_input: dict = {}

    for turn in range(_MAX_TURNS):
        if on_step:
            # Turn 1 picks tools; every later turn is usually the write-up. When a later
            # turn instead asks for more data, its tool labels simply supersede this one.
            on_step(_STEP_DECIDING if turn == 0 else _STEP_SYNTHESIZING)

        if _LOG_LLM_PAYLOAD:
            messages_json = json.dumps(messages, default=str)
            print(
                f"[llm]   turn {turn + 1} payload          messages={len(messages)}  "
                f"~{len(SYSTEM_PROMPT) + len(messages_json):,} chars (system+history, excl. tool defs)"
            )
            print(f"[llm]   turn {turn + 1} system:\n{SYSTEM_PROMPT}")
            print(f"[llm]   turn {turn + 1} messages:\n{json.dumps(messages, indent=2, default=str)}")

        llm_t0 = time.perf_counter()
        # Streamed so the explanation can be surfaced as it is generated (see on_summary in
        # the docstring). get_final_message() still hands back the same Message object the
        # non-streaming call returned, so everything below is unchanged.
        streamed_text = ""
        streaming_tool: str | None = None
        input_json = ""

        async with client.messages.stream(
            model=settings.anthropic_model,
            max_tokens=2000,
            system=system_blocks,
            tools=TOOL_DEFINITIONS,
            tool_choice={"type": "any"},
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    streaming_tool = block.name if block.type == "tool_use" else None
                    input_json = ""
                elif (
                    on_summary is not None
                    and streaming_tool == "submit_analysis"
                    and event.type == "content_block_delta"
                    and event.delta.type == "input_json_delta"
                ):
                    input_json += event.delta.partial_json
                    partial = _partial_json_string(input_json, _STREAMED_FIELD)
                    if partial and partial != streamed_text:
                        streamed_text = partial
                        on_summary(partial)

            response = await stream.get_final_message()

        llm_elapsed = time.perf_counter() - llm_t0
        llm_time += llm_elapsed

        usage = response.usage
        print(
            f"[llm]   turn {turn + 1} usage            in={usage.input_tokens} "
            f"(cache_read={usage.cache_read_input_tokens or 0}, "
            f"cache_write={usage.cache_creation_input_tokens or 0})  out={usage.output_tokens}"
        )
        # Breakdown of where output tokens actually went — a "text" block here is a preamble
        # the model wrote before its tool call, pure overhead we could suppress with a forced
        # tool_choice; "tool_use" size approximates the JSON payload itself (tiles/hypotheses).
        if _LOG_LLM_PAYLOAD:
            for block in response.content:
                if block.type == "text":
                    print(f"[llm]   turn {turn + 1} content block     text       {len(block.text):5d} chars (preamble — unwanted)")
                elif block.type == "tool_use":
                    size = len(json.dumps(block.input, default=str))
                    print(f"[llm]   turn {turn + 1} content block     tool_use   {size:5d} chars  ({block.name})")

        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        terminal_block = next((b for b in tool_blocks if b.name in TERMINAL_TOOLS), None)
        print(f"[llm]   turn {turn + 1} {'(final)' if terminal_block else '(tool selection)':<17} {llm_elapsed * 1000:6.0f}ms")

        messages.append({"role": "assistant", "content": response.content})

        if terminal_block:
            # No step emitted here on purpose — _STEP_SYNTHESIZING already went out before
            # this turn's call, so it covered the generation the user actually waited on.
            final_kind = "guardrail" if terminal_block.name == "flag_out_of_scope" else "analysis"
            final_input = terminal_block.input
            break

        if not tool_blocks:
            # Model replied with plain text instead of calling a tool (ignoring the
            # instruction to always finish via submit_analysis/flag_out_of_scope). Nothing
            # to send back — an empty tool_result user turn is rejected by the API — so
            # stop here rather than loop again; falls through to the "incomplete" status.
            break

        if on_step:
            for block in tool_blocks:
                on_step(_STEP_LABELS.get(block.name, f"Running {block.name}..."))

        tool_result_blocks: list[dict] = []
        results_by_id: dict[str, dict] = {}
        turn_tool_max = 0.0

        # The model occasionally re-requests a tool it already called this run (despite
        # the system prompt instruction not to) — serve those from the in-memory result
        # instead of paying for a redundant fetch or even a redundant Redis round trip.
        fresh_blocks = []
        for block in tool_blocks:
            if block.name in tool_data:
                print(f"[agent] {block.name:<25}   cached (duplicate call skipped)")
                results_by_id[block.id] = tool_data[block.name]
            else:
                fresh_blocks.append(block)

        batch_t0 = time.perf_counter()
        # Each sync tool runs on its own worker thread; gather overlaps them so the
        # turn costs max(tool times), not sum, and the event loop stays free.
        batch_results = await asyncio.gather(
            *(_run_tool_guarded(b.name, b.input, ticker) for b in fresh_blocks)
        )
        for block, (_, result, hit, elapsed) in zip(fresh_blocks, batch_results, strict=True):
            turn_tool_max = max(turn_tool_max, elapsed)  # tools run in parallel within a turn
            if hit:
                cache_hit_names.add(block.name)
            print(f"[agent] {block.name:<25} {elapsed * 1000:6.0f}ms  {'(cached, redis)' if hit else ''}")
            result = _with_run_context(block.name, result, tool_data)
            tool_data[block.name] = result
            results_by_id[block.id] = result
        if _LOG_LLM_PAYLOAD and len(fresh_blocks) > 1:
            # Wall time of the whole batch vs. the slowest individual call — if these are
            # close, the fetches genuinely overlapped rather than running one after another.
            batch_elapsed = time.perf_counter() - batch_t0
            print(f"[agent] {'+'.join(b.name for b in fresh_blocks):<25} {batch_elapsed * 1000:6.0f}ms  (batch wall time, n={len(fresh_blocks)})")
        tool_time += turn_tool_max

        for block in tool_blocks:
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(results_by_id[block.id], default=str),
            })

        messages.append({"role": "user", "content": tool_result_blocks})

    total_elapsed = time.perf_counter() - run_t0
    print(f"[orchestrator] {ticker:<6} total {total_elapsed * 1000:6.0f}ms  (llm {llm_time * 1000:.0f}ms, tools {tool_time * 1000:.0f}ms)")

    # Tools whose data came from Redis this run rather than a live fetch.
    cache_hits = sorted(cache_hit_names)

    if final_kind == "guardrail":
        return {
            "ticker": ticker,
            "data": tool_data,
            "overview": "",
            "summary": "",
            "tiles": [],
            "hypotheses": [],
            "status": "guardrail",
            "error_message": final_input.get("message", ""),
            "cache_hits": cache_hits,
        }

    explanation = final_input.get(_STREAMED_FIELD) or ""
    if not isinstance(explanation, str):
        explanation = ""
    summary, citations, removed = _resolve_citations(explanation, tool_data)
    tiles = _attach_news_citations(final_input.get("tiles", []), tool_data)

    # Measured, never enforced: the flags describe the write-up, they don't change it.
    quality_flags: list[str] = []
    if summary:
        try:
            quality_flags = check_explanation(
                summary, ticker=ticker, query=query, overview=overview,
                tool_data=tool_data, tiles=tiles, removed_citations=removed,
            )
            print(f"[quality] {ticker:<6} {', '.join(quality_flags) or 'clean'}")
        except Exception as exc:  # a heuristic must never cost the reader their answer
            print(f"[quality] {ticker:<6} check FAILED — {exc}")

    result = {
        "ticker": ticker,
        "data": tool_data,
        "overview": overview,
        "summary": summary,
        "citations": citations,
        "tiles": tiles,
        "hypotheses": final_input.get("hypotheses", []),
        "status": "complete" if final_kind == "analysis" else "incomplete",
        "cache_hits": cache_hits,
        "quality_flags": quality_flags,
    }
    if _SAVE_RUNS_PATH:
        record = {
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "query": query,
            "raw_explanation": explanation,
            **result,
        }
        await asyncio.to_thread(_save_run, record)
    return result
