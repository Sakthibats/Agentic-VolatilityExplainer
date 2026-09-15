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
  "AAPL is at $187.20, down 4.1% today. That is unusually large    ← code, right after step 2
   for this stock — about 3.3x its typical daily move."
  "A reported supply-chain delay is the most likely cause..."     ← Claude, written last
```

## What's worth a look

- **Deterministic before agentic.** The model never judges whether a move is significant — that
  math runs first, in code, and the model interprets the verdict.
- **A bounded, structured agent loop.** At most 7 turns, tools fanned out in parallel, and the only
  way to finish is a schema-defined tool call. Citations are attached from real headlines, never
  from the model.
- **Streaming that survives the user leaving.** Progress and the summary stream over SSE; the
  investigation runs independently of the connection, so an abandoned run still finishes and
  warms the cache.
- **Runs on free data.** Every source falls back to yfinance; Redis and Supabase are optional.
- **Behaviour pinned by tests.** 238 offline tests, including a scripted fake Anthropic client that
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

## Repo layout

```
backend/volatility_explainer/   FastAPI app, agent orchestrator, data tools, clients
frontend/                       Next.js 16 static export (Tailwind v4, shadcn/ui)
tests/                          pytest suite mirroring the backend layout
docs/                           architecture and roadmap
.github/workflows/              tests, backend deploy, frontend deploy, live contracts
```

## Documentation

| Doc | Read it for |
|---|---|
| [AGENTS.md](AGENTS.md) | The project brief: goals, invariants, decision log, open questions, where to change things. Start here — for humans and AI assistants alike |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Request lifecycle, the `/v1` API and SSE contract, caching, deployment, configuration |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Migration phases, what's next, what's out of scope |
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
| Quality | pytest · ruff · eslint · tsc · weekly live contract tests |
| Deploy | GitHub Actions → Docker Hub → Cloud Run (backend) · Cloudflare Pages (frontend) |
