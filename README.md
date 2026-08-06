# Agentic Market Explainer

FastAPI backend (REST + SSE) at api.market-explainer.com, Next.js frontend on Vercel.

<img width="1468" height="773" alt="image" src="https://github.com/user-attachments/assets/74599fd6-539f-464c-8f5f-e4ed63ba0444" />

Ask "why is TSLA down today" and get an actual investigation, not a chatbot guess pulled from stale training data. The agent pulls real price and volatility numbers first, decides for itself whether the move is statistically unusual, then fans out to news, options, macro, or upcoming catalysts only when the evidence warrants it — returning ranked hypotheses with confidence levels, and every number traceable to a real source.

```
"why did AAPL drop today?"
        ↓
  1. Pull price + realized vol — always, no LLM call
  2. Move > 2× normal range?  → fan out news + options (parallel, no LLM call)
  3. Tool-use loop decides what else is needed (macro? earnings? sector?)
  4. Synthesize → ranked hypotheses, confidence, caveats
        ↓
  "AAPL fell 4.1% — over 2x its normal daily swing.
   Bloomberg reported a supply-chain delay this morning..."
```

## Why it's different

- **Deterministic first, agentic second.** Price and volatility are computed in plain code before any model call. The reasoning layer only spends tokens once the numbers say something's actually unusual.
- **An extendable toolkit, not a hardcoded pipeline.** Each data source is a discrete [MCP](https://modelcontextprotocol.io/) tool — adding a capability means adding a tool, not rewriting the reasoning loop.
- **Structured output only.** The model can only end its turn via a terminal tool call (`submit_analysis` or `flag_out_of_scope`), never free text. Every number must trace back to a real tool result, or it's marked "Data unavailable."
- **Degrades gracefully.** Price, news, and macro each fall back to `yfinance` if a paid source is missing or fails — the app runs end-to-end with zero API keys configured.

The significance math, options analytics, ticker resolution, and FAQs are covered in more depth on the [About page](frontend/app/about/page.tsx).

## Architecture

```
POST /v1/analyze (FastAPI, SSE)  ──►  agent/orchestrator.py  ──►  tool-use loop (Claude Haiku 4.5)
                                    │
                                    ▼
                           mcp/tools/  (MCP-shaped: name, schema, dispatch — in-process today)
                           ├── price.py     → clients/finnhub.py  (yfinance always, for history)
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

## Concurrency

The request path is fully async: LLM turns — the long poles — are awaited natively
(`AsyncAnthropic`), and per-turn tool fan-out runs via `asyncio.gather`. Tool
implementations stay deliberately sync — every tool can fall back to yfinance, which is
sync-only — and are quarantined on worker threads, so the event loop is never blocked.
Finnhub/FRED share persistent HTTP clients (connection keep-alive instead of a handshake
per call). If a client disconnects mid-stream, the investigation finishes anyway and its
result lands in the caches — the work is already paid for.

Measured honestly (7 live investigations per variant, same machine): single-run latency is
LLM-dominated and unchanged (~9.5s mean); 4 concurrent investigations complete in ~17s wall
(3.1× vs serial). The async gain is headroom — a thread is no longer held hostage for each
15-second request, so concurrent capacity scales with the event loop, not the thread pool.

## Caching

Three layers, three jobs: a per-tool Redis cache avoids re-hitting APIs for data that hasn't gone stale; a final-answer cache skips the LLM call entirely for the generic "explain recent price action" default; Anthropic prompt caching marks the static system prompt and tool schemas as reusable so only the growing tool-result tail gets billed each turn. TTLs range from 15 minutes (price, macro) to 24 hours (event dates), tuned to how fast each source actually changes. All three layers are optional and no-op without `REDIS_URL`.

## Project layout

```
backend/volatility_explainer/
├── config.py            # pydantic-settings, validated secrets
├── api/                  # FastAPI app: /v1/analyze (SSE + JSON), tickers, health; schemas = the contract
├── query/                 # scope guardrail + ticker resolution (concept/symbol/name/LLM fallback)
├── marketdata/             # price history, quick stats, analyst targets (yfinance)
├── clients/                 # external API adapters (Finnhub, FRED, Redis)
├── analytics/                # Supabase usage logging (fire-and-forget, background thread)
├── agent/                     # orchestrator (tool-use loop) + system prompt
└── mcp/tools/                  # 8 MCP-shaped data tools — dual-purpose: in-process today, server-ready

frontend/                # Next.js (App Router) + Tailwind v4 + shadcn/ui — deploys to Vercel

tests/
├── api/                   # route + SSE-stream tests (orchestrator mocked)
├── agent/                 # orchestrator loop tests (scripted fake Anthropic client)
├── query/                 # query-parsing/resolver unit tests
├── mcp/tools/             # tool-level unit tests (mocked data sources)
└── clients/               # Redis cache unit tests

.github/workflows/
├── test.yml               # pytest + ruff on every push/PR
└── docker-publish.yml     # test job, then build + push to Docker Hub (main only, gated on tests passing)

Dockerfile             # multi-stage build, non-root runtime user, healthcheck
docker-compose.yml     # local run with .env-driven config
```

## Stack

| Layer | Choice |
|---|---|
| Agent | Anthropic Claude (Haiku 4.5), tool-use loop, max 7 turns, prompt caching |
| Tool protocol | [MCP](https://modelcontextprotocol.io/) tool-definition conventions (standalone server on the roadmap) |
| API | FastAPI — REST + SSE streaming, versioned `/v1` |
| UI | Next.js (App Router) + Tailwind v4 + shadcn/ui, dual light/dark theme |
| Data | Finnhub (price, news), FRED (macro) — `yfinance` fallback throughout |
| Cache | Redis — per-tool + final-answer, optional |
| Analytics | Supabase — anonymized usage logging, optional |
| Config | Pydantic Settings, validated `.env` secrets |
| Testing / Lint | pytest, ruff |
| CI/CD | GitHub Actions — test + lint on every push/PR; Docker Hub publish on `main` gated on tests passing |

## Quick start

```bash
cp .env.example .env   # fill in API keys (see below)
pip install -e ".[dev]"
pytest
uvicorn volatility_explainer.api.app:app --reload --port 8080
```

Then:

```bash
curl localhost:8080/v1/health
curl -N -X POST localhost:8080/v1/analyze -H 'content-type: application/json' \
     -d '{"query": "why is TSLA down"}'                  # SSE stream
curl -X POST 'localhost:8080/v1/analyze?stream=false' -H 'content-type: application/json' \
     -d '{"query": "why is TSLA down"}'                  # single JSON document
```

`yfinance` needs no API key, so the app runs end-to-end with zero keys configured. `ANTHROPIC_API_KEY` is the only one required for the agent's reasoning step; Finnhub/FRED improve data quality, Supabase/Redis are optional infra.

Lint before committing: `ruff check backend tests`

## Roadmap

- **Stand up the actual MCP server** — expose the existing tools behind `mcp/server.py` for external MCP clients.
- **A real historical IV rank** — swap the intra-chain IV percentile for a proper 52-week rank.
- **Crypto & FX coverage**
- **Multi-ticker comparisons**
- **Persistent query history**
