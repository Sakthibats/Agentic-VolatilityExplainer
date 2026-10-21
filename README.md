# Agentic Market Explainer

**Live:** https://market-explainer.com/

<img width="1222" height="763" alt="image" src="https://github.com/user-attachments/assets/8d5fbb86-2ba6-4419-ad0b-90cb79a46b13" />

Ask "why is TSLA down today" and get an actual investigation, not a chatbot guess from stale
training data. The backend pulls real price and volatility numbers first, decides **in plain
code** whether the move is statistically unusual, then lets a Claude tool-use loop fan out to
news, options, analyst actions, sector, macro, or earnings only when the evidence warrants it —
returning ranked hypotheses with confidence levels and every number traceable to a real source.

```
"why did AAPL drop today?"
        ↓
  1. Scope guardrail + ticker resolution    no LLM unless it's needed
  2. Price, realized vol + event calendar   always fetched, deterministic
  3. Significance verdict computed in code  typical / elevated / unusual, per horizon
  4. Claude picks which tools to call       news? options? analyst? sector? macro?
  5. Structured finish                      evidence tiles → ranked hypotheses → explanation
        ↓
  "AAPL is at $187.20, down 4.1% today. It usually moves up to     ← code, right after step 2
   about 1.3% a day, so today's move is unusually large for AAPL."
  "Most likely a reported supply-chain delay [1]; tech stocks       ← Claude, written last;
   were flat, so this looks AAPL-specific."                          [1] linked by the server
```

## What's worth a look

- **Deterministic before agentic.** The model never judges whether a move is significant — that
  math runs first, in code, and the model interprets the verdict.
- **A bounded, structured agent loop.** At most 7 turns, tools fanned out in parallel, and the only
  way to finish is a schema-defined tool call. The model cites evidence only as `[n]`; the server
  turns each number into a real headline's link, so a link can't be invented.
- **Streaming that survives the user leaving.** Progress, a code-built overview and the model's
  explanation stream over SSE and are revealed as typed text; the investigation runs independently
  of the connection, so an abandoned run still finishes and warms the cache.
- **Runs on free data.** Every source falls back to yfinance; Redis and Supabase are optional.
- **Write-up quality is measured, not assumed.** Plain-code checks flag known failure modes in every
  explanation — overstating the move, restating numbers, analyst consensus offered as a cause,
  uncited catalysts — logged per run, with real bad write-ups pinned as regression tests.
- **Behaviour pinned by tests.** 241 offline tests, including a scripted fake Anthropic client that
  drives the whole loop, plus weekly live contract tests that catch upstream API shape changes.

## Quickstart

```bash
cp .env.example .env              # set ANTHROPIC_API_KEY; everything else is optional
pip install -e ".[dev]"
pytest -q
uvicorn volatility_explainer.api.app:app --reload --port 8080

cd frontend && npm install && npm run dev    # http://localhost:3000
```

```bash
curl -N -X POST localhost:8080/v1/analyze -H 'content-type: application/json' \
     -d '{"query": "why is TSLA down"}'
```

Or run the backend image: `docker compose up --build` (serves on `:8080`).

To see how the write-ups hold up, save runs while you use the app, then summarise their quality
flags:

```bash
VOLX_SAVE_RUNS=runs.jsonl uvicorn volatility_explainer.api.app:app --port 8080
python scripts/quality_report.py runs.jsonl            # add --show <flag> to read offenders
```

## Repo layout

```
backend/volatility_explainer/   FastAPI app, agent orchestrator, data tools, clients
frontend/                       Next.js 16 static export (Tailwind v4, shadcn/ui)
tests/                          pytest suite mirroring the backend layout
docs/                           architecture, roadmap, hand-run Supabase SQL
scripts/                        write-up quality report, API benchmark
.github/workflows/              tests, backend deploy, frontend deploy, live contracts
```

## Documentation

| Doc | Read it for |
|---|---|
| [AGENTS.md](AGENTS.md) | The project brief: goals, invariants, decision log, open questions, where to change things. Start here — for humans and AI assistants alike |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Request lifecycle, the `/v1` API and SSE contract, caching, deployment, configuration |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Migration phases, what's next, what's out of scope |
| [docs/sql/](docs/sql/) | Supabase schema changes to run by hand **before** deploying the code that needs them, plus reporting queries |
| [BACKLOG.md](BACKLOG.md) | Known security and code-quality debt |
| [PRIVACY.md](PRIVACY.md) | What gets logged |

## Stack

| Layer | Choice |
|---|---|
| Agent | Claude Haiku 4.5, tool-use loop (max 7 turns), streaming, prompt caching |
| API | FastAPI + `sse-starlette`, versioned `/v1`, fully async |
| Frontend | Next.js 16 (App Router) + React 19 + Tailwind v4 + shadcn/ui, static export |
| Data | Finnhub (quotes, news), FRED (macro), yfinance (history, options, analyst, sector, fallback) |
| Cache / analytics | Redis (optional) · Supabase usage log (optional) · GA4 |
| Quality | pytest · ruff · eslint · tsc · weekly live contract tests · heuristic write-up checks |
| Deploy | GitHub Actions → Docker Hub → Cloud Run (backend) · Cloudflare Pages (frontend) |
