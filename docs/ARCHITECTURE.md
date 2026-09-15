# Architecture

The deep reference. For the one-screen overview, goals, and the decision log behind all of this,
start with [AGENTS.md](../AGENTS.md).

---

## Repo map

```
backend/volatility_explainer/     Python package (hatchling; see pyproject.toml)
├── config.py                     pydantic-settings; secrets are SecretStr, all optional; model ID
├── api/
│   ├── app.py                    FastAPI routes, CORS, SSE plumbing (task + queue)
│   ├── schemas.py                ★ THE CONTRACT — every response body and SSE payload
│   └── service.py                scope gate → final-answer cache → orchestrator → shaping → usage log
├── query/parsing.py              scope guardrail + 4-stage ticker resolution
├── agent/
│   ├── orchestrator.py           ★ the tool-use loop: prefetch, dispatch, streaming, citations
│   ├── tool_schemas.py           tool JSON schemas + the when-to-call guidance the model reads
│   └── prompts.py                system prompt: reading price data, output and framing rules
├── tools/                        8 sync data tools — MCP-shaped, in-process
│   ├── price.py                  Finnhub quote + yfinance history; computes move_assessment
│   ├── news.py                   Finnhub company news → yfinance fallback
│   ├── options.py                snapshot (IV, put/call, skew) + positioning (max pain, OI walls, term structure)
│   ├── analyst.py                dated up/downgrades, consensus trend, price targets
│   ├── sector.py                 stock vs. its sector ETF over the same horizons
│   ├── macro.py                  FRED VIX → yfinance ^VIX/^GSPC fallback
│   ├── events.py                 reported EPS beat/miss, next earnings, ex-dividend, static FOMC calendar
│   └── _retry.py                 small retry helper for flaky yfinance calls
├── marketdata/snapshots.py       chart history + sidebar stats (feeds /v1/tickers/*)
├── clients/                      finnhub.py · fred.py · redis_cache.py (memo + Redis)
└── analytics/supabase_logger.py  optional usage log: bounded queue, background worker, JSONL fallback

frontend/                         Next.js 16 App Router, static export (output: "export")
├── lib/api.ts                    ★ hand mirror of api/schemas.py + the SSE-over-fetch parser
├── app/globals.css               design tokens: light "Cobalt" / dark trading terminal
├── app/layout.tsx                header, providers (theme, feedback, investigation), GA4
├── app/page.tsx                  the investigation UI
├── app/about/page.tsx            long-form methodology copy
└── components/                   investigation-provider (state), query-bar, timeline, evidence-tiles,
                                  hypotheses, price-chart, stats-panel, feedback, support-button, ui/

tests/                            mirrors the backend layout; no network by default
├── agent/test_orchestrator.py    scripted fake Anthropic client pins the whole loop
├── api/test_api.py               routes, SSE ordering, client-disconnect behaviour
├── query/test_parsing.py         guardrail + resolver, incl. "no network call" assertions
├── tools/                        per-tool unit tests + test_live_contracts.py (pytest -m live)
└── clients/test_redis_cache.py

docs/theme-schemes.ts             archived alternate colour schemes (future theme picker)
scripts/benchmark_api.py          sequential latency vs. concurrent wall-time benchmark
```

---

## Request lifecycle

Read [`api/service.py`](../backend/volatility_explainer/api/service.py) and
[`agent/orchestrator.py`](../backend/volatility_explainer/agent/orchestrator.py) together — that is
the whole flow.

1. **Scope gate** ([`query/parsing.py`](../backend/volatility_explainer/query/parsing.py)). A query
   of more than 4 words with no local financial signal is rejected before touching yfinance or an
   LLM. Ticker resolution runs cheapest first: concept phrases (`gold` → a fund search) →
   uppercase ticker tokens → company-name search (must be a name *prefix* match, so "bake a cake"
   can't resolve to CAKE) → a conservative Claude fallback.
2. **`investigation_started`** fires as soon as a ticker resolves, so the frontend starts loading the
   chart and stats while the agent works.
3. **Final-answer cache** — only on the no-question path ("explain the recent price action"), which
   is generic by construction. A question-specific ask always runs fresh.
4. **Deterministic prefetch.** `get_price_data` and `get_events` run in parallel before any LLM
   turn, and are spliced into the history as a synthetic `tool_use`/`tool_result` pair, so the
   model reads them exactly like calls it made itself.
5. **`move_assessment` is computed in code** ([`tools/price.py`](../backend/volatility_explainer/tools/price.py)),
   on two axes: relative (|change| vs. this stock's expected move — one standard deviation, scaled
   by √time from annualized realized vol — banded typical < 1.5x ≤ elevated < 2.5x ≤ unusual) and
   absolute (a stock-agnostic magnitude floor, so a chronically volatile name can't get an 18% drop
   called "typical"). Output: an `overall` level plus one plain-English flag per non-typical
   horizon (1d/1w/2w/1mo/ytd/1y). The reader-facing overview states the stock's usual daily range
   ("usually moves up to about 3.7% a day") and names the absolute floor only as a comparison
   with other stocks ("normal for DDOG, but large by most stocks' standards").
6. **Tool-use loop.** Model from `settings.anthropic_model` (default `claude-haiku-4-5-20251001`),
   `tool_choice: {"type": "any"}`, max **7 turns**. Turn 1 is the real tool-selection layer: the
   model picks whichever tools help and calls them together; they fan out with `asyncio.gather`,
   each on a worker thread under a **15 s** timeout. A tool already called this run is served from
   memory, not re-fetched. Most investigations resolve in one round.
7. **Only two ways to finish:** `submit_analysis` (≤4 tiles → 2–3 ranked hypotheses → explanation) or
   `flag_out_of_scope`. If the model writes prose, the loop stops and the run comes back
   `status: "incomplete"` rather than hanging.
8. **Streaming the write-up, in two paragraphs.** Right after the pre-fetch,
   `tools/price.describe_move` turns the price data into a factual "what happened" paragraph — no
   LLM — sent as a single `overview` event and quoted to the model so it doesn't repeat it. Every
   turn is streamed; while `submit_analysis` is generated, its `explanation` field (the "why") is
   extracted from the partial JSON and emitted as cumulative `summary` events. `explanation` is the
   schema's LAST property on purpose: the model writes it after committing to tiles and ranked
   hypotheses, so the conclusion follows the reasoning. It is returned as `AnalysisResult.summary`.
9. **Server-side post-processing.**
   - *Citations.* `get_news` headlines with a URL are numbered (`ref` 1..n) before the model sees
     them. The explanation cites evidence as `[n]`; the server resolves each number to that
     headline's real link (`AnalysisResult.citations`) and removes any number that matches
     nothing. The news tile cites the first 3 headlines under the same numbers.
   - *Price anchoring.* Analyst upside is re-anchored to the same price the overview quotes.
   - *Quality checks* ([`agent/quality.py`](../backend/volatility_explainer/agent/quality.py)).
     Cheap heuristics flag known failure modes in the explanation: too long, restating the
     overview's figures, size words stronger than the code's verdict, analyst consensus offered
     as a cause, unmeasured forces (momentum, institutional conviction…), a causal claim with no
     citation, and invalid citation numbers. Flags are logged and returned on the orchestrator
     result — measured, never used to rewrite the text, and not part of the API contract.
10. **Shaping and logging.** `service.py` coerces the model output into schema objects (skipping
    malformed entries) and logs usage in the background. It never raises — failures come back as
    `status: "error"`.

---

## The `/v1` API

| Endpoint | Notes |
|---|---|
| `POST /v1/analyze` | SSE by default; `?stream=false` returns one `AnalysisResult` JSON document. Optional `x-session-id` header (a UUID is minted otherwise). Body: `{"query": "..."}`, 1–500 chars |
| `GET /v1/tickers/{ticker}/history?period=` | `1W` / `1M` / `6M` / `YTD` / `1Y` |
| `GET /v1/tickers/{ticker}/stats` | quick stats + analyst targets for the sidebar |
| `GET /v1/health` | `{"status": "ok", "version": ...}` |

SSE events (payload models in [`api/schemas.py`](../backend/volatility_explainer/api/schemas.py)):

```
investigation_started   → InvestigationStarted    once, when the ticker resolves
step        (0..n)      → Step                    progress label, emitted BEFORE the work it names
overview    (0..1)      → Overview                "what happened", computed in code, right after the price fetch
summary     (0..n)      → SummaryProgress         cumulative "why" text from the model — replace, don't append
result | guardrail      → AnalysisResult | Guardrail   exactly one, terminal
error                   → ApiError                terminal, on failure
```

**Disconnect semantics:** the investigation is an independent `asyncio.Task` feeding a queue. If the
client disconnects, only the SSE generator is cancelled; the run finishes and lands in the caches
(finish-and-cache).

---

## Caching

Four layers, each with its own job. Everything except the process memo and prompt caching is a
no-op without `REDIS_URL`.

1. **Per-tool cache** ([`clients/redis_cache.py`](../backend/volatility_explainer/clients/redis_cache.py)).
   Checked tool by tool right before each fetch — an in-process memo first, then Redis — so a tool
   the investigation never needs is never looked up. A hit still gets a fresh LLM synthesis.
   `get_macro` is market-wide and cached under one shared key.

   | TTL | Tools |
   |---|---|
   | 15 min | `get_price_data`, `get_macro` |
   | 30 min | `get_options_data`, `get_sector_comparison` |
   | 1 hour | `get_options_positioning` |
   | 4 hours | `get_news` |
   | 12 hours | `get_analyst_sentiment` (also expires at midnight) |
   | 24 hours | `get_events` (also expires at midnight) |

   Day-scoped tools expire at midnight because their payloads embed day counts ("earnings in 8
   days") that are only correct on the day they were computed.
2. **Final-answer cache** (15 min) — skips tools *and* the LLM, only on the no-question path. Written
   back on a background thread.
3. **Anthropic prompt caching** — the system prompt and tool list carry `cache_control`, so only the
   growing tool-result tail is processed fresh each turn.
4. A 30-second in-process cache inside `options.py` for the expensive chain fetch.

---

## Frontend

- **State lives in `InvestigationProvider`, in the root layout**, so switching between Home and About
  doesn't unmount an in-flight investigation or its SSE stream.
- **SSE is parsed by hand from the fetch body** (`lib/api.ts`), because `EventSource` can't POST. A new
  query aborts the previous stream.
- **The write-up is revealed on the client** (`lib/use-typewriter.ts`). The overview arrives as one
  event, the explanation in bursts, a cached answer all at once; a steady reveal that speeds up
  when behind makes all three read as streamed text. The "why" waits for the "what happened"
  paragraph, and reduced-motion users get the text immediately.
- **Theme:** `next-themes` with a class strategy, light by default. All colours are CSS variables in
  `app/globals.css`.
- **Analytics:** GA4 via `components/analytics.tsx`, production builds only.
- **Static export:** `next build` writes `frontend/out/`; there is no Node server in production.

---

## Deployment

Pipelines are path-filtered, so a frontend commit never rebuilds the backend image and vice versa.

| Workflow | Trigger | What it does |
|---|---|---|
| [`test.yml`](../.github/workflows/test.yml) | pushes to non-main branches + all PRs | `pytest -q` + `ruff check backend tests` (Python 3.11) |
| [`docker-publish.yml`](../.github/workflows/docker-publish.yml) | push to `main` touching `backend/`, `tests/`, `Dockerfile`, `pyproject.toml` | tests → build and push `sakthibas98/agentic-market-explainer:{latest,run#}` → `gcloud run deploy` |
| [`frontend-deploy.yml`](../.github/workflows/frontend-deploy.yml) | `frontend/` changes (PRs build + lint only) | `npm ci` → lint (blocking) → static export → Cloudflare Pages |
| [`live-contracts.yml`](../.github/workflows/live-contracts.yml) | Mondays 06:00 UTC, manual, PRs touching tools/clients | `pytest -m live` with spaced retries; scheduled failures open a `live-contracts` issue |

**Backend** → Google Cloud Run, service `agentic-market-explainer`, project
`agenticmarketexplainer-501814`, region `asia-southeast1`. Multi-stage Dockerfile (dependency layer
keyed only on `pyproject.toml`), non-root `appuser`, `/v1/health` healthcheck, honours Cloud Run's
`$PORT`.

**Frontend** → Cloudflare Pages, project `market-explainer`. `NEXT_PUBLIC_API_URL` is inlined at
build time, so the workflow hard-fails if the repo variable is unset rather than shipping a bundle
that points at `localhost:8080`.

Required CI secrets/vars: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `GCP_SA_KEY`,
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `FINNHUB_API_KEY` (live contracts), and the repo
variable `NEXT_PUBLIC_API_URL`.

---

## Configuration

Settings load through pydantic-settings from `.env` at the repo root, regardless of CWD.

| Var | Required? | Effect if missing |
|---|---|---|
| `ANTHROPIC_API_KEY` | for `/v1/analyze` | Investigations fail with `status: "error"`; chart/stats endpoints still work |
| `ANTHROPIC_MODEL` | no | Defaults to `claude-haiku-4-5-20251001` |
| `FINNHUB_API_KEY` | no | Quotes, news and upcoming earnings fall back to yfinance |
| `FRED_API_KEY` | no | Macro falls back to yfinance `^VIX` / `^GSPC` |
| `REDIS_URL` | no | Redis tool cache and final-answer cache become no-ops (process memo remains) |
| `SUPABASE_URL` / `SUPABASE_KEY` | no | Usage logging becomes a no-op. Service-role key: server-side only |
| `VOLX_LOG_LLM_PAYLOAD=1` | no | Enables per-turn payload sizes, content-block breakdown and full message dumps |
| `VOLX_SAVE_RUNS=runs.jsonl` | no | Appends every finished run (raw and resolved explanation, tool data, quality flags) to that file, for `scripts/quality_report.py`. Local use |
| `NEXT_PUBLIC_API_URL` (frontend) | build time | Defaults to `http://localhost:8080` |
| `NEXT_PUBLIC_GA_ID` (frontend) | no | Falls back to the checked-in GA4 ID |

---

## Observability

Currently stdout `print` lines, prefixed by source: `[agent]` per-tool timings and cache hits,
`[llm]` per-turn token usage (including cache read/write) and latency, `[redis]` final-answer
lookups, `[orchestrator]` / `[run:TICKER]` totals, and `[quality] TICKER flag, flag…` (or `clean`)
for every explanation — searchable in Cloud Run's log explorer. The same flags are stored per run in
the Supabase usage log's `quality_flags` column; the migration and reporting queries are in
[`docs/sql/query_log_quality_flags.sql`](sql/query_log_quality_flags.sql). Some modules (clients, analyst, events, analytics)
use `logging` instead. Moving to structured logs or traces is an open item — see
[AGENTS.md § Open questions](../AGENTS.md#7-open-questions--good-places-to-ideate).

---

## Testing strategy

- **Offline by default.** `pyproject.toml` sets `-m 'not live'`, so `pytest -q` never touches the
  network. Data sources are mocked at module level.
- **The loop is pinned with a fake Anthropic client** that replays scripted responses as real
  streaming events (including chunked `input_json_delta`s), so the partial-JSON explanation extraction
  runs for real.
- **Live contract tests** (`tests/tools/test_live_contracts.py`) assert only the *shape* of upstream
  responses — the failure mode that mocked tests structurally can't catch. They skip on 5xx/429.
- **Calendar tripwire:** `test_fomc_calendar_has_runway` fails 90 days before the static FOMC list
  runs out.
- **Write-up regression cases** (`tests/agent/test_quality.py`). Real bad explanations — starting
  with a DDOG write-up from 2026-09 — are pinned verbatim with the flags they must trip, alongside
  a clean example of the intended shape. To grow the set: run locally with `VOLX_SAVE_RUNS`, find
  offenders with `python scripts/quality_report.py runs.jsonl --show <flag>`, and add them here.
  These check the *checks*; they don't call the model, so prompt changes still need a live run.
