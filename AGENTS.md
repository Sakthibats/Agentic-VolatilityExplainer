# AGENTS.md — Agentic Market Explainer

> **Starter context for any AI assistant** (Claude Code, Codex, Cursor, or a chat model you paste
> this into). It is written to be enough on its own to reason about goals, tradeoffs, and where to
> change things. Deeper references: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
> [docs/ROADMAP.md](docs/ROADMAP.md) · [BACKLOG.md](BACKLOG.md).
> Last reviewed: 2026-11-10.

## 1. What this is

A web app that answers *"why did TSLA move?"* with an actual investigation instead of a chatbot
guess. The backend computes price and realized-volatility significance **in plain code**, then a
bounded Claude tool-use loop decides which evidence to pull (news, options, analyst actions,
sector, macro, earnings/events). It must finish by calling a structured `submit_analysis` tool: ≤4
evidence tiles, 2–3 ranked hypotheses with confidence and caveats, and an explanation written
last. Progress, a code-built "what happened" overview, and the model's "why" stream to the browser
over SSE.

Live at https://market-explainer.com · repo `Sakthibats/Agentic-VolatilityExplainer` · solo project.

## 2. Goals and non-goals

**Primary goal: a portfolio / interview showcase** of production-minded agentic engineering. When
weighing tradeoffs, optimise for these, in order:

1. **Engineering judgment visible in the code** — deterministic work before the LLM, a bounded agent
   loop, structured outputs, graceful degradation, a clear API contract, tests that pin agent
   behaviour.
2. **Clarity** — a reviewer should grasp the design in ten minutes. Prefer fewer, well-explained
   moving parts over feature breadth.
3. **Low running cost** — self-funded: Haiku, layered caching, scale-to-zero hosting.
4. **Product growth** — secondary. Keep the seams for freemium; don't build it.

**Non-goals for now:** payments/Stripe, accounts/auth, Telegram or Slack adapters, crypto/FX,
multi-ticker comparison, anything resembling trading advice or signals.

## 3. Status snapshot

| Area | State |
|---|---|
| Product | Live. Single-ticker investigations, price chart + stats sidebar, About page, feedback (mailto), buy-me-a-coffee link |
| Migration | Streamlit monolith → FastAPI + Next.js. Phases 0–3 ✅. **Phase 4 (metering / rate limiting) is next and not started** |
| Backend | FastAPI, fully async, `/v1` REST + SSE, Docker → Google Cloud Run |
| Frontend | Next.js 16 static export → Cloudflare Pages |
| Quality gates | 310 offline pytest tests + 23 `live` tests (19 upstream data contracts, weekly; 4 LLM-vendor checks that skip without keys). ruff, eslint (blocking), tsc all clean. Heuristic quality flags on every explanation (`[quality]` log line) |
| Models | Users pick the vendor per run with a model picker in the query bar: OpenAI (`OPENAI_MODEL`, default `gpt-6-luna`; the picker's default) or Claude (`ANTHROPIC_MODEL`, Haiku 5.5). Requests without `provider` use `LLM_PROVIDER` (default `anthropic`). Both run the same loop behind `llm/`; the eval harness compares models on recorded data (`evals/`, results in the README) |
| Biggest gaps | The eval scores answers automatically but has **no labelled catalysts or judge yet**, so it can't measure whether the model found the true cause · yfinance's daily bar lags the close, so "today" can be the previous day's move after the close (`evals/README.md`) · no rate limiting and CORS `*` · `print`-based logging · token usage and `cost_usd` are returned per run (`result["usage"]`) but not logged · chart silently falls back to synthetic prices |

## 4. Architecture in one screen

```
Browser — Next.js static export (Cloudflare Pages)
  │  POST /v1/analyze               SSE over a fetch stream (EventSource can't POST)
  │  GET  /v1/tickers/{t}/history   chart     ┐ plain JSON, loaded as soon as the
  │  GET  /v1/tickers/{t}/stats     sidebar   ┘ ticker resolves
  │  GET  /v1/models                the model picker: each vendor's model + availability
  ▼
api/app.py        each investigation runs as its own asyncio.Task → queue → SSE
api/service.py    vendor check → scope gate → final-answer cache (no-question path, per vendor)
                  → orchestrator → shape into schemas → background usage log. Never raises.
  ├─ query/parsing.py         guardrail + 4-stage ticker resolution (LLM only as last resort)
  └─ agent/orchestrator.py
       1. prefetch get_price_data + get_events in parallel — deterministic, no LLM
            → describe_move builds the "what happened" overview; sent at once
       2. splice them in as a synthetic tool_use / tool_result turn (overview quoted too)
       3. loop ≤7 turns · a tool call forced every turn · streamed · via llm/ (Claude | OpenAI)
            model picks tools → asyncio.gather(to_thread(tool)), 15 s timeout each
       4. the turn may end ONLY via submit_analysis | flag_out_of_scope
       5. the model cites headlines as [n]; the server resolves each to a real link or drops it
       6. agent/quality.py flags the explanation — logged per run, never rewrites it
       ├─ agent/tool_schemas.py   what the model sees: schemas + when-to-call guidance
       ├─ agent/prompts.py        how to read the data, output and framing rules
       └─ tools/*.py              sync fetchers, each with a yfinance fallback
            └─ clients/           finnhub · fred · redis_cache (in-process memo + Redis)
marketdata/snapshots.py           chart history + sidebar stats
analytics/supabase_logger.py      optional usage log incl. quality_flags (schema changes: docs/sql/)
```

SSE order: `investigation_started` → `step`* → `overview`? (code-built "what happened") →
`summary`* (the model's "why"; cumulative text, not deltas) → exactly one terminal `result` |
`guardrail` | `error`. The contract is
`backend/volatility_explainer/api/schemas.py`, mirrored by hand in `frontend/lib/api.ts`.

### Repo map

Every tracked file that matters, with a one-line role. ★ marks the files to read first. Keep this
current: adding, moving or deleting a file updates this map in the same change.

```
backend/volatility_explainer/     Python package (hatchling; pytest pythonpath = . and backend)
├── config.py                     pydantic-settings; keys are SecretStr, all optional; LLM_PROVIDER + models
├── api/
│   ├── app.py                    routes, CORS, SSE plumbing (one asyncio.Task + queue per run)
│   ├── schemas.py                ★ THE CONTRACT: every response body and SSE payload
│   └── service.py                vendor check → scope gate → final-answer cache → orchestrator → shaping → usage log
├── query/parsing.py              scope guardrail, 4-stage ticker resolution, _specific_question
├── llm/                          ★ the vendor seam: one turn in, one turn out
│   ├── base.py                   neutral conversation types + the LLMProvider interface
│   ├── anthropic_provider.py     Claude: cache breakpoints, fine-grained streaming, tool_choice any
│   ├── openai_provider.py        OpenAI Responses API: strict tools, reasoning items replayed
│   └── pricing.py                $ per 1M tokens per model → cost_usd on every run
├── agent/
│   ├── orchestrator.py           ★ the loop: prefetch, _TOOL_DISPATCH, streaming, citations, usage
│   ├── tool_schemas.py           tool schemas + when-to-call guidance; submit_analysis stays last
│   ├── prompts.py                system prompt: reading data, output, framing and data rules
│   └── quality.py                heuristic write-up flags (measure, never rewrite)
├── tools/                        8 sync data tools, MCP-shaped but in-process; each falls back to yfinance
│   ├── price.py                  get_price_data: quote, history, realized vol, move_assessment, describe_move
│   ├── news.py                   get_news: Finnhub company news → yfinance
│   ├── options.py                get_options_data (IV, put/call, skew) + get_options_positioning
│   │                             (max pain, OI walls, term structure)
│   ├── analyst.py                get_analyst_sentiment: up/downgrades, consensus trend, targets
│   ├── sector.py                 get_sector_comparison: stock vs. its sector ETF, same horizons
│   ├── macro.py                  get_macro: FRED VIX → yfinance ^VIX/^GSPC
│   ├── events.py                 get_events: EPS beat/miss, next earnings, ex-div, static FOMC list
│   └── _retry.py                 with_retry: backoff helper for flaky yfinance calls
├── clients/                      finnhub.py (key sent as a header) · fred.py (key stripped from
│                                 errors) · redis_cache.py (in-process memo + Redis, per-tool TTLs)
├── marketdata/snapshots.py       chart history + sidebar stats behind /v1/tickers/{t}/*
└── analytics/supabase_logger.py  optional usage log: bounded queue, background worker

frontend/                         Next.js 16 App Router, static export (output: "export")
├── app/layout.tsx                header, providers (theme, feedback, investigation), GA4
├── app/page.tsx                  the investigation UI
├── app/about/page.tsx            long-form methodology copy
├── app/globals.css               ★ all colour tokens: light blue / dark trading terminal
├── lib/api.ts                    ★ hand mirror of api/schemas.py + the SSE-over-fetch parser
├── lib/model-choice.ts           the chosen LLM vendor (localStorage; default OpenAI), read when a run starts
├── lib/use-typewriter.ts         paced reveal of the streamed write-up
├── lib/utils.ts                  cn() class merge
└── components/
    ├── investigation-provider.tsx  run state + SSE; in the root layout so navigation keeps the stream
    ├── query-bar · timeline (InvestigationLog) · evidence-tiles (AGENT_ICONS) · hypotheses
    ├── md.tsx                    **bold** + [n] → citation links from result.citations
    ├── price-chart · stats-panel · nav-tabs · theme-toggle · model-picker (vendor logo + menu, in query-bar)
    ├── vendor-icons              OpenAI / Claude marks (MIT, lobe-icons), monochrome
    ├── feedback · support-button · analytics (GA4 ID, public by design)
    └── ui/                       shadcn primitives: badge, button, card

tests/                            mirrors the backend; offline by default (`pytest -m live` for upstream)
├── agent/                        test_orchestrator (scripted fake Anthropic client pins the loop) ·
│                                 test_quality (real bad write-ups pinned verbatim)
├── api/test_api.py               routes, SSE order, client disconnect still finishes the run
├── query/test_parsing.py         guardrail + resolver, incl. "no network call" assertions
├── tools/                        one test file per tool + test_live_contracts.py (19 live tests)
├── clients/                      test_redis_cache · test_api_keys (keys never in URLs or errors)
├── analytics/                    test_supabase_logger (queued payload, quality_flags semantics)
├── llm/                          pricing + selection · test_openai_provider (scripted fake Responses
│                                 stream through the real loop) · test_live_providers (pytest -m live)
└── evals/                        test_capture (selection) · test_replay_and_scorers (isolation, scorers)

evals/                            capture.py (daily fixture recorder) · cases.py · replay.py (fixture
                                  data through the real loop) · run.py (models x repeats, $ cap) ·
                                  scorers.py · report.py · README.md · results/ (committed runs + tables)
                                  fixtures/<day>/<TICKER>.json: bot-committed each weekday, ~10 KB
                                  each and growing. Don't read or search them unless working on evals
scripts/                          quality_report.py (flag rates over VOLX_SAVE_RUNS) ·
                                  benchmark_api.py (sequential vs. concurrent latency)
docs/                             ARCHITECTURE.md · ROADMAP.md · sql/ (hand-run Supabase changes) ·
                                  theme-schemes.ts (archived alternate colour schemes)
.github/workflows/                test · docker-publish · frontend-deploy · live-contracts · eval-capture
root                              pyproject.toml (deps, ruff, pytest config) · Dockerfile ·
                                  docker-compose.yml · .env.example · BACKLOG.md · PRIVACY.md
```

## 5. Invariants — don't break these without an explicit decision

- **API-first.** The frontend talks to the backend only through `/v1`. `api/schemas.py` is the source
  of truth; change `frontend/lib/api.ts` in the same commit.
- **Deterministic first, agentic second.** Price/vol math and the `move_assessment` verdict are
  computed in `tools/price.py` before any LLM call. The model interprets; it never computes
  significance.
- **Structured endings only.** The loop ends via `submit_analysis` or `flag_out_of_scope`. If the
  model writes prose instead, the run returns `status: "incomplete"` — prose is never parsed.
- **Links never come from the model.** Headlines are numbered server-side; the model may only cite
  `[n]`, and the server resolves each number to the real URL (`AnalysisResult.citations`) or
  removes it. Tile citations come straight from `get_news`.
- **Quality checks measure, never rewrite.** `agent/quality.py` flags the explanation; it must not
  alter or block the answer, and a failing check must not fail the run.
- **Degrade gracefully.** Every data source keeps a yfinance fallback. Redis, Supabase, Finnhub and
  FRED are all optional. `service.analyze()` never raises.
- **Keys stay out of logs.** Tools print upstream errors, and httpx puts the full URL in every
  error message, so an API key must never sit in a URL or an exception string. Finnhub takes its key
  in the `X-Finnhub-Token` header; FRED only accepts a query param, so `clients/fred.py` strips
  `api_key` from errors before re-raising. Pinned by `tests/clients/test_api_keys.py`.
- **Vendor-neutral loop.** `agent/orchestrator.py` never imports a vendor SDK; everything vendor-specific
  (message shapes, cache markers, streaming events, usage) lives in `llm/<vendor>_provider.py`. A new
  vendor is a new adapter plus its fake-stream tests, not a change to the loop.
- **Async backend, sync tools.** LLM calls are awaited (`AsyncAnthropic` / `AsyncOpenAI`). Tools stay sync (yfinance
  is sync-only) and run via `asyncio.to_thread`. Never call a tool directly on the event loop.
- **Finish-and-cache.** A client disconnect must not cancel the investigation — pinned by
  `tests/api/test_api.py::test_client_disconnect_lets_investigation_finish`.
- **Write-up order.** `explanation` stays the LAST property of `submit_analysis`, after tiles and
  hypotheses, so the "why" is written from them (tested). The "what happened" overview comes from
  code (`tools/price.describe_move`), never the model. `submit_analysis` stays last in
  `TOOL_DEFINITIONS` (it carries the prompt-cache breakpoint).
- **Theme.** Light = white + blue (`#1565C0` family), never coral/orange. Dark = trading terminal.
  Both come from tokens in `frontend/app/globals.css`; no hardcoded colours in components.
- **Tests before refactors.** `tests/agent/test_orchestrator.py` drives the loop with a scripted fake
  Anthropic client. Keep it green and extend it whenever the loop changes.

## 6. Decision log — why it is the way it is

Each entry: the decision, why, what it costs, and when to reconsider.

1. **Significance is computed in code** — relative to the stock's own √time-scaled realized vol
   (typical < 1.5x one standard deviation ≤ elevated < 2.5x ≤ unusual), plus an absolute magnitude
   floor. *Why:* auditable and repeatable; the model can neither rubber-stamp an 18% drop as
   "typical" nor inflate a 1% move because the user said "crash". The bands were widened from
   1x/2x in 2026-09: a 1x move happens about one day in three, so DDOG up 4% on a ~3.7% usual day
   was being called "larger than usual". *Cost:* hand-tuned thresholds, never backtested; wider
   bands also mean fewer flagged moves, so news is fetched less often. *Revisit:* once an eval set
   exists.
2. **Terminal tools instead of JSON-in-text.** *Why:* schema-shaped output, no regex extraction, an
   explicit out-of-scope path. *Cost:* a large tool schema in every request; a prose reply ends the
   run as `incomplete` with no retry. A schema is a request, not a guarantee: Claude doesn't
   validate tool input it streams, so `orchestrator._normalize_answer` re-applies the contract in
   code (malformed entries dropped, ≤4 tiles, ≤3 hypotheses ranked by the order written).
   *Revisit:* if the incomplete rate turns out to matter (the eval measures it; production
   doesn't).
3. **Deterministic prefetch of price + events, spliced in as fake tool calls.** *Why:* both are needed
   on nearly every run and decide the first tool choice; this saves an LLM round trip for ~0
   marginal wall time, and the model reads them exactly like its own calls. *Cost:* the events fetch
   is paid even when irrelevant.
4. **Claude Haiku 5.5, ≤7 turns, `tool_choice: any`, prompt caching.** *Why:* latency and cost for a
   free public demo; most runs finish in one tool round (two LLM turns). Moved from Haiku 4.5 on
   2026-11-10 after the eval: ~12x cheaper, about twice as fast, and far fewer quality flags. Its
   two failures there, wrongly refusing in-scope tickers and breaking the tile/rank schema, were
   fixed first (a clearer scope rule in the prompt; `_normalize_answer`, decision 2). *Cost:*
   shallower reasoning than a larger model, and extended thinking stays off (forced tool calls
   rule it out). The model is configurable via `ANTHROPIC_MODEL`. *Revisit:* with labelled evals,
   e.g. Haiku for tool selection and a larger model for synthesis.
5. **Async FastAPI with sync tools on threads** — not Go, not async rewrites of each tool. *Why:* the
   workload is I/O-bound, and yfinance (the universal fallback) is sync-only. *Cost:* `to_thread`
   work can't be cancelled, so a timed-out tool keeps running (its cache write still lands); the
   default thread pool caps concurrency.
6. **SSE over a POST fetch stream, with the investigation decoupled from the connection.** *Why:* live
   progress UX, and navigating away doesn't waste a paid run. *Cost:* abandoned runs are still paid
   for; there's no resume-by-id, so a reconnect starts a new run (possibly served from cache).
7. **Hand-mirrored TypeScript types instead of OpenAPI codegen.** *Why:* one client, a small schema,
   zero tooling. *Cost:* drift is caught only by review. *Revisit:* a second client, or frequent
   schema churn.
8. **Next.js static export on Cloudflare Pages** (the original plan was Vercel). *Why:* the UI is
   entirely client-side; free static hosting with no Node server. *Cost:* no SSR or per-ticker OG
   pages, no same-origin API proxy (hence CORS), and `NEXT_PUBLIC_API_URL` is baked in at build.
9. **Backend on Cloud Run via Docker Hub.** *Why:* container portability and scale to zero. *Cost:*
   cold starts; the in-process memo is per instance.
10. **Layered caching** — per-process memo → Redis with per-tool TTLs (day-scoped tools also expire at
    midnight) → final-answer cache only when no question was asked → Anthropic prompt caching.
    "No question" means the query only names the ticker ("TSLA", "why did tesla move today"):
    `query/parsing._specific_question` strips the subject and generic ask-words. Until 2026-10 the
    raw text always counted as a question, so the final-answer cache never served a request.
    *Why:* cost and latency, while question-specific answers stay fresh. *Cost:* data up to one TTL
    stale; a generic query gets the generic answer, not one framed around the user's wording.
11. **yfinance everywhere as fallback**, pinned `>=1.4,<1.5`, with weekly live contract tests. *Why:*
    runs with no paid data keys. *Cost:* scraping-based and fragile — a silent return-type change
    once left `get_events` returning only a hardcoded FOMC date while the suite stayed green.
12. **Tools are MCP-*shaped* but in-process.** The package was renamed `mcp/tools/` → `tools/` in
    2026-09 because no MCP server exists. *Revisit:* if exposing the tools to external MCP clients
    becomes a goal.
13. **No auth, no billing.** A session-scoped anonymous ID; usage is logged to Supabase server-side.
    *Why:* usage is unproven. Phase 4 adds a usage ledger and rate-limit middleware (log-only first)
    so freemium later is configuration, not a rearchitecture.
14. **A static FOMC calendar** in `tools/events.py` (currently through 2027-12-08). *Why:* no free,
    reliable API. *Cost:* a manual yearly refresh — `test_fomc_calendar_has_runway` fails 90 days
    before the list runs out, on purpose.
15. **Two-paragraph write-up: overview from code first, explanation from the model last.** *Why:*
    with `summary` as the first schema property, the model committed to a "why" before generating
    its tiles and ranked hypotheses — it felt fast but concluded before it reasoned. Now a
    deterministic overview lands right after the pre-fetch, and the explanation is generated after
    the hypotheses. *Cost:* the first model-written word arrives a few seconds later (tiles and
    hypotheses are generated first); the overview's wording is templated. *Revisit:* if tiles and
    hypotheses should stream progressively too.
16. **A fixed explanation shape, checked by heuristics rather than enforced.** The explanation must
    give cause + confidence, one dated piece of evidence cited as `[n]`, then market/sector context
    if it was checked; prompt rules ban repeating the overview, consensus as a cause, unmeasured
    forces and facts from memory. `agent/quality.py` flags violations in plain code. *Why:* a
    production DDOG write-up broke all of these at once, and prompt rules alone can't be verified
    without measurement. *Cost:* regex heuristics have false negatives (tuned for precision); the
    flags reach Cloud Run logs and the Supabase `query_log.quality_flags` column (labels only, not
    the text), so reading offending write-ups still needs a local `VOLX_SAVE_RUNS` capture.
    *Revisit:* replace or back the heuristics with a scored eval set (open question 1).

17. **A thin in-house provider seam, not LiteLLM or LangChain** (2026-11). `llm/base.py` defines a
    neutral conversation and `run_turn()`; one adapter per vendor. *Why:* the loop depends on
    things generic layers flatten: streaming a partially written tool call, explicit cache
    breakpoints, forcing a tool call, and replaying OpenAI reasoning items verbatim. Two ~200-line
    adapters keep all of that visible and tested. It also turns "which model?" into a measured
    question (`evals/`) and removes vendor lock-in. *Cost:* two adapters and two fake streams to
    maintain; each vendor's schema enforcement differs (OpenAI strict mode rejects a schema
    violation, Claude with fine-grained streaming does not validate). *Revisit:* a third vendor,
    or if either SDK's streaming events change shape (the live tests catch that).

18. **Users choose the vendor, the server chooses the model** (2026-11). `AnalyzeRequest.provider`
    is `openai` | `anthropic`; the query-bar picker sends it, defaulting to OpenAI. *Why:* lets a
    visitor compare the two loops side by side, and the model IDs stay server config, so a client
    can't pick an expensive model; `GET /v1/models` tells the UI which model IDs those are and which
    vendors have a key. A vendor without a key fails before any data is fetched, with a message
    saying to switch. The final-answer cache is keyed per vendor, and each `query_log` row
    records `llm_provider` / `llm_model`. *Cost:* two API keys to keep funded; the cache hit rate is
    split across vendors; the ticker-resolution fallback still uses `LLM_PROVIDER`. *Revisit:* once
    evals pick a winner on accuracy, or if spend control (Phase 4) needs a per-vendor budget.

## 7. Open questions — good places to ideate

Framed against the portfolio goal. Each is a live tradeoff, not a settled plan.

1. **Evals.** How is answer quality measured? In place: heuristic flags on every production
   explanation (`agent/quality.py`, bad write-ups pinned in `tests/agent/test_quality.py`), daily
   fixtures of all 8 tools' raw output (`evals/capture.py`, since 2026-10), and since 2026-11 a
   harness that replays those fixtures through the real loop on any model and scores completion,
   schema validity, figures against the data, invented citations, tool choice, cost and stability
   (`evals/README.md`). Still missing: labelled catalysts and a judge model for catalyst recall,
   abstention and calibration, which is what "is the answer right?" needs.
2. **Observability and cost.** Structured per-run traces (turns, tools chosen, tokens, cache hits, $)
   instead of `print`. Show cost per investigation on the About page?
3. **Abuse and spend control (Phase 4).** Redis token bucket per session/IP, a daily global LLM
   budget, CORS locked to the frontend origin. Log-only first, or enforce straight away?
4. **Model strategy.** The eval compares Haiku 4.5, Haiku 5.5 and GPT-6 Luna on cost, latency and
   grounding; Claude runs moved to Haiku 5.5 on that evidence (decision 4), and visitors can switch
   vendor per run (decision 18). Changing either vendor's
   model is one env var; the open part is answer accuracy, which needs
   the labelled cases from (1).
5. **Contract safety.** Generate `lib/api.ts` from FastAPI's OpenAPI schema, or add a contract test?
6. **A real MCP server.** Expose `tools/` to Claude Desktop and others? Good signal, but a second
   surface to maintain.
7. **Data honesty.** Replace the synthetic chart fallback with an explicit "unavailable" state.
8. **Deeper vol analytics.** A true 52-week IV rank needs stored IV history — where would it live,
   and is it worth it?

## 8. Where to change things

Backend paths are relative to `backend/volatility_explainer/`.

| Task | Touch |
|---|---|
| Add a data tool | `tools/<name>.py` (sync, returns a dict, yfinance fallback) → `agent/tool_schemas.py` (schema, when-to-call text, add to the tile `agent` enum) → `agent/orchestrator.py` `_TOOL_DISPATCH` + `_STEP_LABELS` → `clients/redis_cache.py` `TOOL_TTL_SECONDS` → `frontend/components/evidence-tiles.tsx` `AGENT_ICONS` → `tests/tools/` (plus a live contract test) |
| What the model is told | Per-tool guidance and the explanation's shape: `agent/tool_schemas.py`. Global reading, output, framing and data rules: `agent/prompts.py` |
| Eval fixtures (daily capture) | `evals/capture.py` (selection rules, pacing) + `tests/evals/test_capture.py`; schedule in `.github/workflows/eval-capture.yml` |
| Eval runner / scorers / report | `evals/cases.py`, `evals/replay.py`, `evals/run.py`, `evals/scorers.py`, `evals/report.py` + `tests/evals/test_replay_and_scorers.py` |
| Add or change an LLM vendor | `llm/<vendor>_provider.py` + `llm/__init__.py` (`build_provider`) + `llm/pricing.py` + `config.py` + a fake-stream test in `tests/llm/` + a case in `tests/llm/test_live_providers.py` |
| Model prices | `llm/pricing.py` (update the date in its docstring) |
| Write-up quality checks | `agent/quality.py` + `tests/agent/test_quality.py` (add each new bad write-up as a regression case). Report over saved runs: `scripts/quality_report.py` |
| Citations | Numbering + resolution: `agent/orchestrator.py` (`_with_news_refs`, `_resolve_citations`) → `frontend/components/md.tsx` |
| Agent loop behaviour | `agent/orchestrator.py` + extend `tests/agent/test_orchestrator.py` |
| Significance thresholds | `tools/price.py` (`_RELATIVE_BANDS`, `_ABS_THRESHOLDS_PCT`) + `tests/tools/test_price.py` — also changes the overview wording and the size check in `agent/quality.py` |
| Scope guardrail / ticker resolution | `query/parsing.py` + `tests/query/test_parsing.py` |
| API shape / SSE events | `api/schemas.py` → `api/app.py`, `api/service.py` → `frontend/lib/api.ts` → `frontend/components/investigation-provider.tsx` |
| Investigation UI | `frontend/app/page.tsx` and `frontend/components/` (state lives in `investigation-provider.tsx`) |
| Colours / theme | `frontend/app/globals.css` only. Archived alternates: `docs/theme-schemes.ts` |
| Cache TTLs | `clients/redis_cache.py` |
| Upstream HTTP clients / API keys | `clients/finnhub.py`, `clients/fred.py` + `tests/clients/test_api_keys.py` (keys never in URLs or errors) + a live contract test |
| Usage-log fields (Supabase) | `analytics/supabase_logger.py` + a SQL file in `docs/sql/` (run in Supabase **before** deploying) + `PRIVACY.md` + `tests/analytics/` |
| Settings / env vars | `config.py` + `.env.example` + the env table in `docs/ARCHITECTURE.md` |
| CI / deploy | `.github/workflows/`, `Dockerfile`, `frontend/next.config.ts` |

## 9. Commands

```bash
pip install -e ".[dev]"          # Python ≥3.11; re-run after moving modules
pytest -q                        # offline suite (live tests excluded by default)
pytest -m live                   # real upstream APIs — response-shape checks only
ruff check backend tests
uvicorn volatility_explainer.api.app:app --reload --port 8080
VOLX_SAVE_RUNS=runs.jsonl uvicorn volatility_explainer.api.app:app --port 8080   # also save each run
python scripts/quality_report.py runs.jsonl   # quality-flag rates; --show <flag> prints offenders
python -m evals.capture --dry-run             # today's eval-fixture selection (no LLM calls)
python -m evals.run --models anthropic:claude-haiku-5-5,openai:gpt-6-luna@low --cases 5 --repeats 1 --budget 0.5 --out /tmp/pilot.jsonl
python -m evals.report evals/results/2026-11-09.jsonl   # comparison table from a results file
pytest -m live tests/llm                      # each vendor still accepts our exact request

cd frontend && npm install
npm run dev                      # :3000; NEXT_PUBLIC_API_URL defaults to http://localhost:8080
npm run lint && npx tsc --noEmit
npm run build                    # static export → frontend/out/
```

CI: `test.yml` (non-main pushes and PRs) · `docker-publish.yml` (main, backend paths: tests → Docker
Hub → Cloud Run) · `frontend-deploy.yml` (frontend paths: lint → build → Cloudflare Pages on main) ·
`live-contracts.yml` (weekly, plus PRs touching tools/clients; opens an issue when the scheduled run
fails) · `eval-capture.yml` (weekdays 21:30 UTC, main only: records eval fixtures and commits them
under `evals/fixtures/`).

## 10. Gotchas

- **Next.js 16 is newer than most training data.** Read `frontend/node_modules/next/dist/docs/`
  before writing Next code (see `frontend/AGENTS.md`). The newer `react-hooks` lint rules (e.g.
  `set-state-in-effect`) are enforced and block deploys.
- `frontend/` uses `output: "export"`: no request-time server rendering, no API routes, no middleware.
- Tests patch seams at module level (`orchestrator.get_settings`, `orchestrator._TOOL_DISPATCH`, …).
  If you move an import, move the patch target with it.
- The in-process tool memo is module-global; tests call `clear_memoized_tool_data()`.
- Tool results pass through `_with_run_context` (fresh and cached alike): analyst upside is
  re-anchored to the run's price, and news headlines get their citation `ref` numbers.
- The streamed explanation can briefly show a `[n]` the server later removes; the final result's
  `summary` is authoritative.
- Some docstrings say "rescued from the retired Streamlit app" — history only; `apps/` is gone.
- **Supabase schema before code.** The `query_log` table isn't defined in the repo; columns added
  since live as hand-run SQL in `docs/sql/`. Supabase rejects a row with an unknown column (and the
  fallback file is lost on a Cloud Run restart), so run the SQL *before* deploying code that logs a
  new field, and revert code before dropping one.
- **Frontend and backend deploy independently** from the same push, and the frontend usually lands
  first. Frontend code must tolerate the previous backend's response — e.g. default a new field.
- Never read `.env`; `.claude/settings.json` denies it.
