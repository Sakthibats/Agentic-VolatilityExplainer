# Agentic Market Explainer

**Live:** https://market-explainer.com/

<img width="1222" height="763" alt="image" src="https://github.com/user-attachments/assets/8d5fbb86-2ba6-4419-ad0b-90cb79a46b13" />

Ask "why is TSLA down today" and get an actual investigation, not a chatbot guess from stale
training data. The backend pulls real price and volatility numbers first, decides **in plain
code** whether the move is statistically unusual, then lets a Claude tool-use loop fan out to
news, options, macro, sector, or upcoming catalysts only when the evidence warrants it —
returning ranked hypotheses with confidence levels and every number traceable to a real source.

```
"why did AAPL drop today?"
        ↓
  1. Scope guardrail + ticker resolution   (query/parsing.py — no LLM unless needed)
  2. Pull price + realized vol             (always, deterministic, no LLM call)
  3. Significance verdict computed in code (move_assessment: typical/elevated/unusual)
  4. Claude picks which tools to call next (news? options? macro? sector? earnings?)
  5. Terminal tool call → ranked hypotheses, evidence tiles, caveats
        ↓
  "AAPL fell 4.1% — over 2x its normal daily swing.
   Bloomberg reported a supply-chain delay this morning..."
```

---

## Repo map

Monorepo. Two independently deployed halves that only ever talk over the versioned `/v1` HTTP API.

```
backend/volatility_explainer/     # Python package (installed via hatchling, see pyproject.toml)
├── config.py                     # pydantic-settings; every secret is a SecretStr, all optional
├── api/
│   ├── app.py                    # FastAPI routes + SSE plumbing
│   ├── schemas.py                # ★ THE CONTRACT — Pydantic models for every response/event
│   └── service.py                # scope gate → final-answer cache → orchestrator → shaping
├── query/parsing.py              # scope guardrail + 4-stage ticker resolution
├── agent/
│   ├── orchestrator.py           # ★ the tool-use loop; tool JSON schemas live here
│   └── prompts.py                # system prompt (how to read price data, output rules)
├── mcp/tools/                    # 8 data tools — MCP-shaped, in-process today
│   ├── price.py                  # Finnhub quote + yfinance history; computes move_assessment
│   ├── news.py                   # Finnhub company news → yfinance fallback
│   ├── options.py                # yfinance chains: IV, put/call, skew, max pain, OI walls
│   ├── macro.py                  # FRED VIX → yfinance ^VIX/^GSPC fallback
│   ├── events.py                 # yfinance earnings date + hardcoded FOMC calendar
│   ├── analyst.py                # yfinance analyst consensus / price targets
│   ├── sector.py                 # sector-ETF relative comparison
│   └── _retry.py                 # small retry helper for flaky yfinance calls
├── marketdata/snapshots.py       # chart history + sidebar stats (feeds /v1/tickers/*)
├── clients/                      # finnhub.py, fred.py, redis_cache.py
└── analytics/supabase_logger.py  # optional usage logging: bounded queue + background worker

frontend/                         # Next.js 16 App Router, static export (`output: "export"`)
├── lib/api.ts                    # ★ mirrors api/schemas.py — keep in sync by hand
├── app/globals.css               # design tokens; light = white+blue, dark = trading terminal
├── app/layout.tsx                # header, providers (theme, feedback, investigation), GA tag
├── app/page.tsx                  # the whole investigation UI
├── app/about/page.tsx            # long-form methodology copy (rescued from the old Streamlit UI)
└── components/                   # investigation-provider (state lives here), timeline,
                                  #   evidence-tiles, hypotheses, price-chart, stats-panel, ui/

tests/                            # 102 tests, zero network — everything mocked
├── agent/test_orchestrator.py    # scripted fake Anthropic client; pins the whole loop
├── api/test_api.py               # routes + SSE event ordering + client-disconnect behavior
├── query/test_parsing.py         # guardrail + resolver, incl. "no network call" assertions
├── mcp/tools/*.py                # per-tool unit tests against mocked data sources
└── clients/test_redis_cache.py

.github/workflows/                # see Deployment below
Dockerfile · docker-compose.yml   # multi-stage build, non-root user, healthcheck
scripts/benchmark_api.py          # sequential latency vs. concurrent wall-time benchmark
CLAUDE.md · BACKLOG.md · PRIVACY.md
```

**Deleted, don't look for it:** the original Streamlit monolith (`apps/`). Several modules
carry "rescued from the retired Streamlit app" comments — that's history, not a live dependency.

---

## How the investigation actually runs

Read [`agent/orchestrator.py`](backend/volatility_explainer/agent/orchestrator.py) and
[`api/service.py`](backend/volatility_explainer/api/service.py) together — that's the whole flow.

1. **Scope gate first** ([`query/parsing.py`](backend/volatility_explainer/query/parsing.py)).
   A query >4 words with no local financial signal is rejected before touching yfinance or any
   LLM. Ticker resolution runs in 4 stages, cheapest first: concept phrases (`gold` → GLD-ish
   fund search) → uppercase ticker tokens → company-name search (must be a name *prefix* match,
   so "bake a cake" can't resolve to CAKE) → a conservative Claude Haiku fallback.
2. **Final-answer cache** — only for the *no-question* path ("explain the recent price action"),
   which is generic by construction. A query-specific ask always runs fresh.
3. **Deterministic price pre-fetch.** `get_price_data` is always called before any LLM turn, and
   is spliced into the message history as a synthetic `tool_use`/`tool_result` pair so the model
   reads it exactly like a tool call it made itself.
4. **`move_assessment` is computed in code**, never eyeballed by the model, on two axes: relative
   (|change| vs. this stock's own expected move, scaled by √time off annualized realized vol) and
   absolute (a fixed stock-agnostic magnitude floor, so a chronically volatile name can't get an
   18% drop rubber-stamped "typical"). Output: an `overall` level plus one plain-English `flags`
   sentence per non-typical horizon (1d/1w/2w/1mo/1y).
5. **Tool-use loop**, `claude-haiku-4-5-20251001`, `tool_choice: {"type": "any"}`, max **7 turns**.
   Turn 1 is the real tool-selection layer — the model picks whichever of the 7 remaining tools
   help and calls them together; all of that turn's tools are fanned out with `asyncio.gather`.
   Most investigations resolve in one round.
6. **Only two ways to end a turn:** `submit_analysis` (summary + ≤4 tiles + 2–3 ranked hypotheses)
   or `flag_out_of_scope`. Never free text. If the model writes prose anyway, the loop stops and
   the run comes back `status: "incomplete"` rather than hanging.
7. **Citations are attached server-side** from the real `get_news` headlines (first 3 with a URL) —
   the model never supplies links, so they can't be hallucinated.

### The `/v1` API

| Endpoint | Notes |
|---|---|
| `POST /v1/analyze` | SSE by default; `?stream=false` returns one `AnalysisResult` JSON doc. Optional `x-session-id` header (a UUID is minted otherwise). |
| `GET /v1/tickers/{ticker}/history?period=` | `1W`/`1M`/`6M`/`YTD`/`1Y` |
| `GET /v1/tickers/{ticker}/stats` | quick stats + analyst targets for the sidebar |
| `GET /v1/health` | version + `{"status": "ok"}` |

SSE event order (payload models all in [`api/schemas.py`](backend/volatility_explainer/api/schemas.py)):

```
investigation_started   → InvestigationStarted   (fires as soon as a ticker resolves, so the
step (0..n)             → Step                     frontend can start loading chart/stats early)
result | guardrail      → AnalysisResult | Guardrail   (exactly one, terminal)
error                   → ApiError                     (terminal, on failure)
```

`service.analyze()` **never raises** — failures come back as `status: "error"` so clients always
get a well-formed `AnalysisResult`.

---

## Design rules that must survive refactors

These are load-bearing. Breaking any of them changes what the product *is*.

- **API-first.** No frontend code ever imports backend modules. `api/schemas.py` is the source of
  truth; `frontend/lib/api.ts` is a hand-maintained mirror — change both together.
- **Deterministic first, agentic second.** Price/vol math and the significance verdict happen in
  plain code before any LLM call. The model interprets; it doesn't compute.
- **Structured output only.** The model ends its turn via a terminal tool call, never free text.
- **Degrade gracefully.** Every data source has a yfinance fallback. Redis and Supabase are
  strictly optional — the app runs end-to-end with **zero** keys, and `ANTHROPIC_API_KEY` is the
  only one that meaningfully improves it.
- **Backend is async; tools are deliberately sync.** LLM calls are awaited natively
  (`AsyncAnthropic`). Tool implementations stay sync because yfinance is sync-only, and are
  quarantined on worker threads via `asyncio.to_thread` — never call one directly on the event
  loop.
- **Client disconnect must not cancel the investigation.** The run is an independent
  `asyncio.Task` feeding an SSE queue; if the browser leaves, the work finishes and lands in the
  caches (finish-and-cache). Pinned by `tests/api/test_api.py::test_client_disconnect_lets_investigation_finish`.
- **Dual theme, shared tokens.** Light = white + blue (#1565C0 family) only — never coral/orange.
  Dark = trading terminal. Both from the same CSS variables in `app/globals.css`.
- **Tests before refactors.** `tests/agent/test_orchestrator.py` pins the loop with a scripted
  fake Anthropic client. Keep it green; extend it when the loop changes.

---

## Caching

Three independent layers, three jobs — all no-ops without `REDIS_URL`:

1. **Per-tool Redis cache** ([`clients/redis_cache.py`](backend/volatility_explainer/clients/redis_cache.py)).
   Checked tool-by-tool right before each fetch, so a tool the investigation never needs is never
   looked up. A hit still runs a fresh LLM synthesis. `get_macro` is market-wide, so it's cached
   under one shared `MARKET_*` key rather than duplicated per ticker.

   | TTL | Tools |
   |---|---|
   | 15 min | `get_price_data`, `get_macro` |
   | 30 min | `get_options_data`, `get_sector_comparison` |
   | 1 hour | `get_options_positioning` |
   | 4 hours | `get_news` |
   | 12 hours | `get_analyst_sentiment` |
   | 24 hours | `get_events` |

2. **Final-answer cache** (15 min) — skips tools *and* the LLM entirely, but only on the no-query
   default path. Written back on a background thread so the user isn't waiting on it.
3. **Anthropic prompt caching** — the system prompt and tool schemas carry `cache_control`, so only
   the growing tool-result tail is billed each turn.

Plus a 30-second in-process cache inside `options.py` for the expensive chain fetch.

---

## Deployment

Two pipelines, path-filtered so a frontend commit never rebuilds the backend image and vice versa.

| Workflow | Trigger | What it does |
|---|---|---|
| [`test.yml`](.github/workflows/test.yml) | pushes to **non-main** branches + all PRs | `pytest -q` + `ruff check backend tests` on Python 3.11 |
| [`docker-publish.yml`](.github/workflows/docker-publish.yml) | push to `main` touching `backend/`, `tests/`, `Dockerfile`, `pyproject.toml` | test → build & push `sakthibas98/agentic-market-explainer:{latest,run#}` to Docker Hub → `gcloud run deploy` |
| [`frontend-deploy.yml`](.github/workflows/frontend-deploy.yml) | push to `main` touching `frontend/` (PRs build+lint only) | `npm ci` → lint (non-blocking) → static export → Cloudflare Pages |

**Backend** → Google Cloud Run, service `agentic-market-explainer`, project
`agenticmarketexplainer-501814`, region `asia-southeast1`. The Dockerfile is multi-stage (deps
layer keyed only on `pyproject.toml`), runs as non-root `appuser`, has a `/v1/health` healthcheck,
and honors Cloud Run's injected `$PORT`.

**Frontend** → Cloudflare Pages, project `market-explainer`. `next.config.ts` sets
`output: "export"`, so it's a pure static bundle in `frontend/out/` with no Node server. Because
`NEXT_PUBLIC_API_URL` is inlined at build time, the workflow **hard-fails** if the repo variable
is unset rather than silently shipping a bundle pointing at `localhost:8080`.

Required CI secrets/vars: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `GCP_SA_KEY`,
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, and the repo variable `NEXT_PUBLIC_API_URL`.

> ⚠️ `CLAUDE.md` still says the frontend "deploys to Vercel" and lists the Vercel deploy as
> pending. That's stale — it ships to Cloudflare Pages and is live. Same for `.env.example`, which
> still references the deleted `apps/streamlit_app.py`.

---

## Local development

```bash
cp .env.example .env          # optional — the app runs with everything blank
pip install -e ".[dev]"       # re-run after structural changes
pytest -q                     # 102 tests, no network required
ruff check backend tests      # CI runs both on every push

uvicorn volatility_explainer.api.app:app --reload --port 8080
cd frontend && npm install && npm run dev    # :3000, reads NEXT_PUBLIC_API_URL
```

Smoke-test the API:

```bash
curl localhost:8080/v1/health
curl -N -X POST localhost:8080/v1/analyze -H 'content-type: application/json' \
     -d '{"query": "why is TSLA down"}'                    # SSE stream
curl -X POST 'localhost:8080/v1/analyze?stream=false' -H 'content-type: application/json' \
     -d '{"query": "why is TSLA down"}'                    # single JSON document
```

Or run the built image: `docker compose up --build` (serves on `:8080`, reads the same env vars).

Set `VOLX_LOG_LLM_PAYLOAD=1` for per-turn LLM diagnostics — payload sizes, content-block
breakdown, and a full dump of the system/tools/messages. Timing, token usage, and cache hits are
printed unconditionally.

### Environment variables

| Var | Required? | Effect if missing |
|---|---|---|
| `ANTHROPIC_API_KEY` | effectively yes | No reasoning step — the only key that really matters |
| `FINNHUB_API_KEY` | no | Price quotes + news fall back to yfinance |
| `FRED_API_KEY` | no | Macro falls back to yfinance `^VIX`/`^GSPC` |
| `REDIS_URL` | no | All three cache layers become silent no-ops |
| `SUPABASE_URL` / `SUPABASE_KEY` | no | Usage logging becomes a silent no-op |
| `NEXT_PUBLIC_API_URL` (frontend) | build-time | Defaults to `http://localhost:8080` |
| `NEXT_PUBLIC_GA_ID` (frontend) | no | Falls back to the checked-in GA4 id; production builds only |

---

## Stack

| Layer | Choice |
|---|---|
| Agent | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`), tool-use loop, max 7 turns, prompt caching |
| Tool protocol | [MCP](https://modelcontextprotocol.io/) tool-definition conventions — in-process today, standalone server on the roadmap |
| API | FastAPI + `sse-starlette`, versioned `/v1`, fully async |
| Frontend | Next.js 16 (App Router) + React 19 + Tailwind v4 + shadcn/ui + Radix, static export |
| Data | Finnhub (quotes, news), FRED (macro), yfinance (history, options, analyst, sector, fallback for everything) |
| Cache | Redis — per-tool + final-answer, optional |
| Analytics | Supabase (server-side usage log, optional) + GA4 on the frontend |
| Config | pydantic-settings, `SecretStr`, `.env` resolved from the repo root regardless of CWD |
| Testing / lint | pytest (`asyncio_mode = auto`) + ruff (line length 100, `E4/E7/E9/F/I/UP/B/C4/SIM/RUF`) |
| Deploy | Docker Hub → Cloud Run (backend), Cloudflare Pages (frontend), GitHub Actions |

---

## Roadmap

Migration phases: 0 restructure + tests ✅ → 1 FastAPI + SSE ✅ → 2 async refactor ✅ →
3 Next.js frontend ✅ (deployed) → **4 metering / rate limiting** (next).

Phase 4 adds an empty-for-now `billing/` boundary. Telegram/Slack adapters and payment collection
are explicitly out of scope — but keep the usage-ledger and billing seams clean so freemium can be
added later without rearchitecting. CORS is currently `allow_origins=["*"]` and gets tightened to
the frontend origin in the same phase.

Beyond that:

- **Stand up the real MCP server** — expose the existing tools via `mcp/server.py` for external clients.
- **A real historical IV rank** — replace the intra-chain IV percentile with a proper 52-week rank.
- **Crypto & FX coverage**, **multi-ticker comparisons**, **persistent query history**.

Known quality debt lives in [BACKLOG.md](BACKLOG.md) — most notably
`marketdata/snapshots.py` serving a **seeded synthetic random walk** when yfinance fails, which the
frontend can't distinguish from real prices.
