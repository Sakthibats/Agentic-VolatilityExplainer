# Agentic Market Explainer

**Every stock move gets a headline. Almost none of them get an investigation.**

Ask "why is TSLA down today" or "is gold overbought" and instead of a canned recap — or a chatbot pattern-matching off stale training data — an agent actually investigates: it pulls real price and volatility numbers first, decides *for itself* whether the move is even statistically unusual, then fans out to news, options positioning, macro context, or upcoming catalysts only when the evidence warrants it. It comes back with ranked hypotheses, confidence levels, and one hard rule: every number is real, or it says so.

```
"why did AAPL drop today?"
        ↓
  ┌─────────────────────────────────────────────────────────┐
  │  1. Pull price + realized vol — always, no LLM call     │
  │  2. Move > 2× normal range?  → fan out news + options   │
  │     in parallel (deterministic, zero LLM round trips)   │
  │  3. Tool-use loop decides if anything ELSE is needed:   │
  │     macro context? earnings/FOMC proximity? sector?     │
  │  4. Synthesize → ranked hypotheses, confidence, caveats │
  └─────────────────────────────────────────────────────────┘
        ↓
  "AAPL fell 4.1% — more than 2x its normal daily swing.
   Bloomberg reported a supply-chain delay this morning..."
```

## Why this exists

A generic LLM answering "why did X drop" is guessing from memory — no live price, no real news, no way to tell a routine 1% wiggle from a genuine 8% outlier. It'll happily narrate a confident-sounding cause for a move that was never statistically unusual in the first place. This project is the fix: **the reasoning only starts after the numbers are on the table**, and it only escalates when the numbers say something is actually going on.

## Not a prompt-wrapped chatbot

This is a hybrid pipeline built around a deliberate cost/latency/accuracy tradeoff — it only reasons (and spends tokens) when the situation genuinely calls for it, and it never reasons *before* it has real data to reason about.

- **Deterministic first, agentic second.** Price and realized volatility are computed in plain code before any model call happens. A significance verdict — is this move typical, elevated, or unusual? — is decided by math, not vibes, and handed to the reasoning layer as ground truth. The reasoning layer then picks, in a single batched turn, which of the remaining tools (news, options, macro, events, analyst sentiment, sector comparison) would actually change the answer — and only reaches for a second, deeper layer (e.g. options positioning) if the first layer's results specifically warrant it.
- **An extendable toolkit, not a hardcoded pipeline.** Every data source is a discrete [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) tool with its own schema and "when to call this" contract. Adding a capability means adding a tool, not rewriting the reasoning loop — and because MCP is a client-agnostic standard, the same tool functions are one wiring step away from serving any MCP-compatible client, not just this app (see [Roadmap](#roadmap)).
- **Engineered for trust, not fluency.** The model can only end its turn by calling one of two terminal tools — `submit_analysis` or `flag_out_of_scope` — never by writing free-text. That guarantees schema-valid output and removes any need to regex-extract JSON from prose. Every number in that output must trace back to a real tool result; missing data says "Data unavailable" instead of getting invented; a tool already answered earlier in the conversation is read from history, never re-called.
- **A framing guardrail against alarmist wording.** If a user calls a move a "crash" or "collapse" but the real number is unremarkable, the agent doesn't adopt that framing or go hunting for a dramatic catalyst that isn't there — it corrects the premise with the actual number first.
- **No unexplained jargon, ever.** The system prompt bans "ATM IV," "skew," "OI," and "max pain" as standalone terms — every claim gets translated into plain English with the number attached: *"options traders are betting the stock settles near $98"* instead of *"max pain is $98."*
- **Degrades gracefully, never breaks.** Price, news, and macro each try a primary client (Alpaca / Finnhub / FRED) and silently fall back to `yfinance` on failure or a missing key — the app runs end-to-end with zero API keys configured.

## The math behind "is this move actually unusual"

This is the part that keeps the agent honest — it's computed in code (`mcp/tools/price.py`), not eyeballed by the model:

1. **Annualized realized volatility** from the trailing 20 trading days of closes: `stdev(daily_returns) × √252 × 100`.
2. **Expected move per horizon**, scaling volatility by time: `expected_move = realized_vol / √252 × √trading_days_for_horizon` — a 1-day, 1-week, 2-week, 1-month, and 1-year expected range, each derived from the same annualized number.
3. **Two independent significance axes**, because either one alone lies in a different way:
   - *Relative*: `|actual_change| / expected_move` → **typical** (≤1×), **elevated** (≤2×), or **unusual** (>2×) — relative to *this stock's own* normal behavior.
   - *Absolute*: a fixed, stock-agnostic magnitude floor per horizon (e.g. a 1-day move needs >7% to count as "unusual" outright) — so a chronically volatile name can't get an 18% monthly drop rubber-stamped "typical" just because that's normal *for it specifically*.
   - The **overall verdict** is the more severe of the two, and when they disagree, the agent is hand-fed both framings explicitly rather than left to flatten the nuance itself.

The output is a plain-English "flag" per non-typical horizon, pre-written in code — the model is *told* to trust `move_assessment.overall` as ground truth, not re-derive it from raw percentages.

## Options analytics, not a single number

`mcp/tools/options.py` pulls a real yfinance options chain and derives:

- **ATM implied volatility** — average of the nearest call/put IV to spot, on the expiry closest to the 2–4 week investigation horizon.
- **IV skew** — OTM put IV (5% below spot) minus OTM call IV (5% above spot), in vol points — the market's crash-insurance premium.
- **Put/call ratio** by open interest.
- **Max pain** — the strike that minimizes total option-writer payout at expiry, computed by brute-force scanning every strike's aggregate call+put payout (`Σ OI × max(0, S−K)` for calls, `Σ OI × max(0, K−S)` for puts) and taking the minimum.
- **OI walls** — the top 3 strikes by open interest on each side, read as support/resistance.
- **IV term structure & its slope** across up to 3 expiries in the 12–30 day window, to tell "rising into a later catalyst" from "near-term risk that's expected to cool."
- **Unusual activity** — strikes where today's volume dwarfs existing open interest (`volume / max(OI, 1)`), which signals *fresh* positioning being put on right now, not stale resting interest.

One honest limitation baked into the code, not glossed over: yfinance has no historical options data, so "IV rank" here is really an **intra-chain IV percentile** (where today's ATM IV sits between the min and max IV *within the current chain*) — not a true 52-week IV rank. A real IV rank would need a paid historical-options data source.

## Investigator intuition: query resolution

Free text like *"why did tesla dip"* or *"is gold overbought"* has to become a ticker before any tool can run. `apps/ui/placeholders.py` resolves it through layered heuristics, each stricter than the last: explicit symbols and known concept phrases (gold → `GLD`, "the market" → `SPY`) resolve immediately; a loose company-name guess or an LLM-fallback resolution is treated as weaker evidence and cross-checked against the query's own words before the guardrail lets it through — specifically to stop an unrelated sentence like *"let's bake a cake today"* from silently resolving to the ticker `CAKE` (Cheesecake Factory) and sailing past the "is this even a market question" check.

## Caching — three different layers, three different jobs

It's easy to conflate these; they solve unrelated problems:

| Layer | What it caches | Where | Why |
|---|---|---|---|
| **Per-tool Redis cache** | Each tool's *raw* result (price, news, options, ...), individually keyed | `clients/redis_cache.py` | Avoid re-hitting Alpaca/Finnhub/yfinance for data that hasn't gone stale yet. Still runs a fresh LLM synthesis against the user's actual question — a cache hit here never skips reasoning. |
| **Final-answer Redis cache** | The fully synthesized summary/tiles/hypotheses, keyed by ticker only | `clients/redis_cache.py` | Only used for the no-query "explain the recent price action" default — the one path generic enough that a hit can skip the LLM call *entirely*. |
| **Anthropic prompt caching** | The system prompt and the (large, static) tool-definition schema | `agent/orchestrator.py`, via `cache_control: {"type": "ephemeral"}` | Both are identical on every turn of a multi-turn investigation, and identical across *every* run of the app — marking them cacheable means only the growing tool-result tail gets freshly processed each turn, instead of re-billing and re-latency-ing the full system prompt + ~8 tool schemas every single turn. |

Per-tool TTLs are tuned to how fast each source actually goes stale, not one flat number:

| Tool | TTL | Why |
|---|---|---|
| `get_price_data` | 15 min | Price / realized vol moves all day |
| `get_macro` | 15 min | VIX / S&P moves all day; cached once, shared across *every* ticker (it's market-wide, not ticker-specific) |
| `get_options_data` | 30 min | IV / put-call / skew snapshot drifts through the day |
| `get_sector_comparison` | 30 min | Tracks price-cadence moves vs. sector ETF |
| `get_options_positioning` | 1 hour | Max pain / OI walls settle slower than price |
| `get_analyst_sentiment` | 12 hours | Ratings / price targets rarely move intraday |
| `get_news` | 4 hours | Headlines don't repeat within a trading day |
| `get_events` | 24 hours | Earnings / FOMC dates are static day-to-day |

All three layers are optional and fail silent — no `REDIS_URL` means every cache call is a no-op, not an error.

## Usage analytics via Supabase

`analytics/supabase_logger.py` logs one row per investigation — anonymized (a per-session UUID, never anything identifying), fire-and-forget on a background thread so a slow or unreachable Supabase never adds latency to a user-facing answer. Each row captures: the ticker, the (optional) free-text query, the deterministic `move_assessment`, which tools were called and whether each came from Redis or a live fetch, the ranked hypotheses, any citations, and total elapsed milliseconds. That's enough to answer real product questions later — which tools actually get used, how often the significance gate fires, where latency goes, what people ask that the guardrail rejects — without ever storing anything that identifies a person. If the Supabase write fails twice, the row is appended to a local `data/failed_query_log.jsonl` instead of silently vanishing. Both `SUPABASE_URL`/`SUPABASE_KEY` are optional — logging is a no-op without them.

## Shaving latency, deliberately

- **Skip the LLM round trip for tools you always need.** `get_price_data` runs before the model is ever called, then gets spliced into the conversation as a real `tool_use`/`tool_result` pair — the model reads it exactly like it would read its own tool call, at the cost of zero reasoning turns.
- **Parallel fan-out, not a sequential chain.** Every tool the model picks in one turn runs concurrently via a `ThreadPoolExecutor`, and the code logs the batch's wall time next to each call's individual time — proof the fetches actually overlapped, not just an assumption.
- **Duplicate-call short-circuiting.** The model occasionally re-requests a tool it already has a result for (despite being told not to); those are served from the in-memory result for this run instead of paying for a redundant fetch or even a redundant Redis round trip.
- **Prompt caching cuts the reprocessed-token bill every turn** (see above) — the expensive part of the payload (system prompt + ~8 tool schemas) is marked `ephemeral` so only the actual tool-result tail grows turn over turn.
- **A hard 7-turn cap** on the tool-use loop, and a prompt that pushes almost everything into one batched first-layer decision — most investigations resolve in a single round.
- **Everything is timed and printed**: per-tool fetch time, per-turn LLM latency, cache-read/cache-write token counts from the API's own usage block, and a final `llm time vs. tool time` split per run — so the deterministic/agentic latency split is an empirical, logged claim, not a guess.

## Challenges along the way

- **Unofficial data sources are flaky.** `yfinance` has no SLA and occasionally hiccups on options-chain and history calls; `mcp/tools/_retry.py` wraps those calls in a small stdlib-only exponential-backoff retry rather than letting a transient failure kill an entire investigation.
- **Free-tier API gaps force real trade-offs.** Finnhub's free plan has no historical candles, so realized volatility and multi-horizon % change *always* come from yfinance's history, with Finnhub only supplying the live quote when a paid key is present. Similarly, no free source has historical options data, hence the intra-chain IV percentile compromise noted above — a "good enough, honestly labeled" answer beats a fabricated true IV rank.
- **Keeping the model grounded without making it robotic.** Early passes either over-hedged every sentence with caveats or confidently stated things the tools never actually returned. The fix was structural, not just prompt tone: terminal-tool-only output, a `move_assessment` computed in code instead of trusted to the model's mental math, and an explicit "Data unavailable" convention instead of letting a null quietly become a guess.
- **LLM-authored text is still attacker-reachable text.** Tile summaries and reasoning are ultimately derived from real news headlines pulled from Finnhub/yfinance — an untrusted, internet-sourced input flowing through the model into HTML. That surface got hardened with `html.escape()` on every LLM-authored string before it's interpolated into `unsafe_allow_html` markdown.
- **False positives in ticker resolution.** A naive company-name-substring match turns any sentence containing the word "cake" into a `CAKE` (Cheesecake Factory) lookup. The fix is the layered, confidence-tiered resolver described above, not a longer stop-word blocklist.
- **MCP is a dependency today, not yet a server.** The tool functions are already MCP-tool-shaped (name, description, JSON schema, dispatch), and the `mcp` SDK is installed — but they're currently wired directly into the in-process orchestrator, not yet exposed behind a standalone `mcp/server.py` for external MCP clients (Claude Desktop, etc.). That's the top item in the roadmap below, not a shipped feature.

## Architecture

```
apps/streamlit_app.py  ──►  agent/orchestrator.py  ──►  tool-use loop (Claude, Haiku 4.5)
                                    │
                                    ▼
                           mcp/tools/  (MCP-shaped: name, schema, dispatch — in-process today)
                           ├── price.py     → clients/alpaca.py   (yfinance fallback)
                           ├── options.py   → yfinance options chains
                           ├── news.py      → clients/finnhub.py  (yfinance fallback)
                           ├── events.py    → yfinance earnings + hardcoded FOMC calendar
                           ├── macro.py     → clients/fred.py     (yfinance VIX fallback)
                           ├── analyst.py   → yfinance analyst consensus
                           └── sector.py    → yfinance sector-ETF comparison
                                    │
                                    ▼
                           clients/redis_cache.py (per-tool)   analytics/supabase_logger.py
```

## Project layout

```
src/volatility_explainer/
├── config.py            # pydantic-settings, validated secrets
├── clients/              # external API adapters (Alpaca, Finnhub, FRED, Redis)
├── analytics/             # Supabase usage logging (fire-and-forget, background thread)
├── agent/                  # orchestrator (tool-use loop) + system prompt
└── mcp/tools/               # 8 MCP-shaped data tools — dual-purpose: in-process today, server-ready

apps/
├── streamlit_app.py     # demo UI — animated investigation, evidence tiles, hypotheses
└── ui/                    # search parsing/guardrails, theming, rendering, About page content

tests/
├── mcp/tools/             # tool-level unit tests (mocked data sources)
├── clients/               # Redis cache unit tests
└── apps/ui/                # query-parsing/resolver unit tests
```

## Stack

| Layer | Choice |
|---|---|
| Agent | Anthropic Claude (Haiku 4.5), tool-use loop, max 7 turns, prompt caching on system + tool defs |
| Tool protocol | [MCP](https://modelcontextprotocol.io/) tool-definition conventions (`mcp` SDK installed; standalone server on the roadmap) |
| UI | Streamlit + Plotly |
| Data | Alpaca (price), Finnhub (news), FRED (macro) — all with `yfinance` fallback |
| Cache | Redis — per-tool TTL cache + final-answer cache, both optional/no-op without `REDIS_URL` |
| Analytics | Supabase — anonymized, fire-and-forget usage logging with a local JSONL fallback |
| Config | Pydantic Settings, validated `.env` secrets |
| Testing | pytest (mocked HTTP clients) |
| Lint | ruff |

## Quick start

```bash
cp .env.example .env   # fill in API keys (see below)
pip install -e ".[dev]"
pytest
streamlit run apps/streamlit_app.py
```

`yfinance` requires no API key, so the app runs end-to-end with **zero keys configured** — Alpaca/Finnhub/FRED are optional upgrades for better data quality and rate limits, and Supabase/Redis are optional infrastructure that no-op cleanly without credentials. `ANTHROPIC_API_KEY` is the only one required for the agent's reasoning step.

Lint before committing: `ruff check .`

## Example

**Query:** `why did NVDA drop today`

1. Price tool runs immediately: NVDA down 3.2%, realized vol implies a normal daily move of ~1.4% → **2.3× normal, flagged significant**.
2. News, options data, and options positioning fetch in parallel (no LLM call yet).
3. The tool-use loop reviews the pre-fetched evidence, decides macro context is worth checking (broad tech selloff?), and calls `get_macro`.
4. Synthesizes: *"NVDA fell 3.2% — more than double its normal daily move — alongside a broad tech selloff (VIX +8%) following a competitor's disappointing guidance. Options traders lean slightly bearish, expecting the stock to settle near $118 over the next few weeks."*
5. Ranked hypotheses returned with confidence and caveats, each traceable to a real tool result.

*(The app's own [About page](apps/ui/about_content.py) covers this same ground interactively, plus FAQs and current limitations — open the app and click **About**.)*

## Roadmap

- **Stand up the actual MCP server.** Wire the existing MCP-shaped tools behind a real `mcp/server.py` so any MCP client (Claude Desktop, etc.) can call them directly, not just the in-process orchestrator.
- **A real historical IV rank.** Swap the intra-chain IV percentile for a proper 52-week IV rank once a historical-options data source is in the budget.
- **Crypto & FX coverage.** Extend beyond equities/ETFs to major crypto and FX pairs.
- **Multi-ticker comparisons.** Ask about two tickers at once ("AAPL vs MSFT this week") in a single run.
- **Persistent query history.** Save past investigations across sessions instead of resetting on refresh.
