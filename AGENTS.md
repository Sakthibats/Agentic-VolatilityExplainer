# AGENTS.md — Agentic Market Explainer

> **Starter context for any AI assistant** (Claude Code, Codex, Cursor, or a chat model you paste
> this into). It is written to be enough on its own to reason about goals, tradeoffs, and where to
> change things. Deeper references: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
> [docs/ROADMAP.md](docs/ROADMAP.md) · [BACKLOG.md](BACKLOG.md).
> Last reviewed: 2026-09-15.

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
| Quality gates | 238 offline pytest tests + 19 `live` upstream contract tests (weekly). ruff, eslint (blocking), tsc all clean. Heuristic quality flags on every explanation (`[quality]` log line) |
| Biggest gaps | No offline **eval harness** that scores the model's answers (only heuristic checks + pinned bad write-ups) · no rate limiting and CORS `*` · `print`-based logging · no cost-per-run tracking · chart silently falls back to synthetic prices |

## 4. Architecture in one screen

```
Browser — Next.js static export (Cloudflare Pages)
  │  POST /v1/analyze               SSE over a fetch stream (EventSource can't POST)
  │  GET  /v1/tickers/{t}/history   chart     ┐ plain JSON, loaded as soon as the
  │  GET  /v1/tickers/{t}/stats     sidebar   ┘ ticker resolves
  ▼
api/app.py        each investigation runs as its own asyncio.Task → queue → SSE
api/service.py    scope gate → final-answer cache (no-question path only) → orchestrator
                  → shape into schemas → background usage log. Never raises.
  ├─ query/parsing.py         guardrail + 4-stage ticker resolution (LLM only as last resort)
  └─ agent/orchestrator.py
       1. prefetch get_price_data + get_events in parallel — deterministic, no LLM
            → describe_move builds the "what happened" overview; sent at once
       2. splice them in as a synthetic tool_use / tool_result turn (overview quoted too)
       3. loop ≤7 turns · Haiku 4.5 · tool_choice=any · streamed
            model picks tools → asyncio.gather(to_thread(tool)), 15 s timeout each
       4. the turn may end ONLY via submit_analysis | flag_out_of_scope
       5. news citations attached server-side from real headlines
       ├─ agent/tool_schemas.py   what the model sees: schemas + when-to-call guidance
       ├─ agent/prompts.py        how to read the data, output and framing rules
       └─ tools/*.py              sync fetchers, each with a yfinance fallback
            └─ clients/           finnhub · fred · redis_cache (in-process memo + Redis)
marketdata/snapshots.py           chart history + sidebar stats
analytics/supabase_logger.py      optional usage log (bounded queue, JSONL fallback)
```

SSE order: `investigation_started` → `step`* → `overview`? (code-built "what happened") →
`summary`* (the model's "why"; cumulative text, not deltas) → exactly one terminal `result` |
`guardrail` | `error`. The contract is
`backend/volatility_explainer/api/schemas.py`, mirrored by hand in `frontend/lib/api.ts`.

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
- **Async backend, sync tools.** LLM calls are awaited (`AsyncAnthropic`). Tools stay sync (yfinance
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
   run as `incomplete` with no retry. *Revisit:* if the incomplete rate turns out to matter (it
   isn't measured today).
3. **Deterministic prefetch of price + events, spliced in as fake tool calls.** *Why:* both are needed
   on nearly every run and decide the first tool choice; this saves an LLM round trip for ~0
   marginal wall time, and the model reads them exactly like its own calls. *Cost:* the events fetch
   is paid even when irrelevant.
4. **Claude Haiku 4.5, ≤7 turns, `tool_choice: any`, prompt caching.** *Why:* latency and cost for a
   free public demo; most runs finish in one tool round (two LLM turns). *Cost:* shallower
   reasoning than a larger model. The model is configurable via `ANTHROPIC_MODEL`. *Revisit:* with
   evals, e.g. Haiku for tool selection and a larger model for synthesis.
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
    *Why:* cost and latency, while question-specific answers stay fresh. *Cost:* data up to one TTL
    stale.
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
    flags only reach Cloud Run logs and local `VOLX_SAVE_RUNS` files, not the Supabase usage log.
    *Revisit:* replace or back the heuristics with a scored eval set (open question 1).

## 7. Open questions — good places to ideate

Framed against the portfolio goal. Each is a live tradeoff, not a settled plan.

1. **Evals.** How is answer quality measured? A start exists: heuristic flags on every explanation,
   bad write-ups pinned in `tests/agent/test_quality.py`, and `scripts/quality_report.py` over runs
   saved with `VOLX_SAVE_RUNS`. Still missing: a golden set of historical moves with known
   catalysts, replayed through the model and scored for catalyst recall, numbers matching tool data,
   and hypothesis calibration. The highest-signal missing piece for an agentic showcase.
2. **Observability and cost.** Structured per-run traces (turns, tools chosen, tokens, cache hits, $)
   instead of `print`. Show cost per investigation on the About page?
3. **Abuse and spend control (Phase 4).** Redis token bucket per session/IP, a daily global LLM
   budget, CORS locked to the frontend origin. Log-only first, or enforce straight away?
4. **Model strategy.** Haiku everywhere, or split selection and synthesis across models? Depends on (1).
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
| Write-up quality checks | `agent/quality.py` + `tests/agent/test_quality.py` (add each new bad write-up as a regression case). Report over saved runs: `scripts/quality_report.py` |
| Citations | Numbering + resolution: `agent/orchestrator.py` (`_with_news_refs`, `_resolve_citations`) → `frontend/components/md.tsx` |
| Agent loop behaviour | `agent/orchestrator.py` + extend `tests/agent/test_orchestrator.py` |
| Significance thresholds | `tools/price.py` (`_RELATIVE_BANDS`, `_ABS_THRESHOLDS_PCT`) + `tests/tools/test_price.py` — also changes the overview wording and the size check in `agent/quality.py` |
| Scope guardrail / ticker resolution | `query/parsing.py` + `tests/query/test_parsing.py` |
| API shape / SSE events | `api/schemas.py` → `api/app.py`, `api/service.py` → `frontend/lib/api.ts` → `frontend/components/investigation-provider.tsx` |
| Investigation UI | `frontend/app/page.tsx` and `frontend/components/` (state lives in `investigation-provider.tsx`) |
| Colours / theme | `frontend/app/globals.css` only. Archived alternates: `docs/theme-schemes.ts` |
| Cache TTLs | `clients/redis_cache.py` |
| Settings / env vars | `config.py` + `.env.example` + the env table in `docs/ARCHITECTURE.md` |
| CI / deploy | `.github/workflows/`, `Dockerfile`, `frontend/next.config.ts` |

## 9. Commands

```bash
pip install -e ".[dev]"          # Python ≥3.11; re-run after moving modules
pytest -q                        # offline suite (live tests excluded by default)
pytest -m live                   # real upstream APIs — response-shape checks only
ruff check backend tests
uvicorn volatility_explainer.api.app:app --reload --port 8080

cd frontend && npm install
npm run dev                      # :3000; NEXT_PUBLIC_API_URL defaults to http://localhost:8080
npm run lint && npx tsc --noEmit
npm run build                    # static export → frontend/out/
```

CI: `test.yml` (non-main pushes and PRs) · `docker-publish.yml` (main, backend paths: tests → Docker
Hub → Cloud Run) · `frontend-deploy.yml` (frontend paths: lint → build → Cloudflare Pages on main) ·
`live-contracts.yml` (weekly, plus PRs touching tools/clients; opens an issue when the scheduled run
fails).

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
- Never read `.env`; `.claude/settings.json` denies it.
