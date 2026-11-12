# Agentic Market Explainer

**Ask "why did TSLA move?" and get an investigation, not a chatbot guess.** Plain code computes
whether the move is statistically unusual. Then a bounded tool-use loop (Claude or OpenAI, the
visitor's choice) collects the evidence and must finish with a structured, cited answer.

**[▶ Try it live: market-explainer.com](https://market-explainer.com/)** ·
[How it works (About page)](https://market-explainer.com/about) ·
[Run it locally](#quickstart) ·
[Architecture](docs/ARCHITECTURE.md) ·
[Design brief and decision log](AGENTS.md)

[![Backend: test & deploy](https://github.com/Sakthibats/Agentic-VolatilityExplainer/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Sakthibats/Agentic-VolatilityExplainer/actions/workflows/docker-publish.yml)
[![Frontend: lint & deploy](https://github.com/Sakthibats/Agentic-VolatilityExplainer/actions/workflows/frontend-deploy.yml/badge.svg)](https://github.com/Sakthibats/Agentic-VolatilityExplainer/actions/workflows/frontend-deploy.yml)
[![Live data contracts (weekly)](https://github.com/Sakthibats/Agentic-VolatilityExplainer/actions/workflows/live-contracts.yml/badge.svg)](https://github.com/Sakthibats/Agentic-VolatilityExplainer/actions/workflows/live-contracts.yml)

| | |
|---|---|
| **Built by** | [Sakthivel Baskaran](https://github.com/Sakthibats), solo: product, agent design, backend, frontend, infra, CI/CD and operations |
| **Status** | Public and live since July 2026. Free, no sign-up |
| **Usage** | 800+ investigations in its first two months, peaking at 30 daily users (Supabase usage log) |
| **Runs on** | One agent loop, two vendors: visitors pick GPT-6 Luna (the default) or Claude Haiku 5.5 per run, chosen on [eval results](#model-evaluation-claude-vs-openai) · FastAPI on Cloud Run (scales to zero) · Next.js static export on Cloudflare Pages |
| **Quality gates** | Offline pytest suite (the agent loop is driven by scripted fake Claude and OpenAI streams) · weekly live data-contract tests · quality checks on every write-up · [an eval harness](#model-evaluation-claude-vs-openai) that replays recorded market data through any model |

<img width="1222" height="763" alt="Market Explainer answering why a stock moved: price chart, evidence tiles, ranked hypotheses and a cited explanation" src="https://github.com/user-attachments/assets/8d5fbb86-2ba6-4419-ad0b-90cb79a46b13" />

## How an investigation runs

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

## Architecture

```mermaid
flowchart LR
    U[Browser<br/>Next.js static export<br/>Cloudflare Pages] -- "POST /v1/analyze<br/>SSE stream" --> API
    U -- "GET /v1/tickers/{t}/history, /stats" --> API

    subgraph CR [FastAPI on Cloud Run]
        API[api/app.py<br/>each run is its own asyncio.Task] --> SVC[api/service.py<br/>scope gate · answer cache · never raises]
        SVC --> G[query/parsing.py<br/>guardrail + ticker resolution]
        SVC --> O[agent/orchestrator.py]
        O -- "first: prefetch in parallel, no LLM" --> P[price + realized vol<br/>events calendar]
        P -- "significance verdict<br/>+ 'what happened' overview" --> O
        O -- "then: ≤7 turns, a tool call forced every turn" --> C[(llm/ provider seam<br/>GPT-6 Luna · or Claude Haiku 5.5)]
        C -- "picks tools" --> T[tools/: news · options · analyst<br/>sector · macro · earnings]
        C -- "must end with" --> S[submit_analysis<br/>or flag_out_of_scope]
        S --> Q[agent/quality.py<br/>flags, never rewrites]
    end

    T --> D[(Finnhub · FRED · yfinance fallback)]
    T --> R[(Redis cache, optional)]
    Q --> L[(Supabase usage log, optional)]
```

Events stream to the browser in a fixed order: `step`* → `overview` (built by code) → `summary`*
(the model's "why") → exactly one `result` | `guardrail` | `error`. The full request lifecycle,
API contract, caching layers and deployment are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Reading the code in 10 minutes

Four files carry the design. Read them in this order:

| # | File | What to look for |
|---|---|---|
| 1 | [`api/schemas.py`](backend/volatility_explainer/api/schemas.py) | The contract. `AnalysisResult` is the whole answer, and the SSE events (`Step`, `Overview`, `SummaryProgress`, `Guardrail`, `ApiError`) are everything the browser can receive |
| 2 | [`agent/orchestrator.py`](backend/volatility_explainer/agent/orchestrator.py) | `run_explainer`, the loop: deterministic prefetch, at most 7 turns, tools on threads with timeouts, ending only through `submit_analysis` or `flag_out_of_scope`. The answer then goes through [`agent/answer.py`](backend/volatility_explainer/agent/answer.py): `[n]` citations resolved to real links by the server, and the schema re-applied with each repair reported |
| 3 | [`tools/price.py`](backend/volatility_explainer/tools/price.py) | Significance computed in code before any LLM call: `_RELATIVE_BANDS`, `_assess_moves` and `describe_move`, the "what happened" paragraph the model never writes |
| 4 | [`tests/agent/test_orchestrator.py`](tests/agent/test_orchestrator.py) | How agent behaviour is pinned: a scripted fake model drives the real loop through turn limits, prose endings, hanging tools and invented citations |

Then, depending on interest: [`llm/base.py`](backend/volatility_explainer/llm/base.py) for the
vendor seam, [`agent/quality.py`](backend/volatility_explainer/agent/quality.py) for the write-up
checks, and [`evals/`](evals/README.md) for the model comparison. Paths are relative to
`backend/volatility_explainer/` except tests and evals.

## Evaluation and safety design

An LLM explaining market moves can fail in a few predictable ways. Each one is handled in code,
not left to the prompt, and each control is pinned by tests:

| Risk | Control | Where |
|---|---|---|
| The model calls a 1% move a "crash", or plays down an 18% drop | Significance is computed **in code** against the stock's own √time-scaled realized vol, plus an absolute floor. The model reads the verdict and can't override it. The user's wording is not treated as evidence | [`tools/price.py`](backend/volatility_explainer/tools/price.py), framing rule in [`agent/prompts.py`](backend/volatility_explainer/agent/prompts.py) |
| Invented sources or links | Headlines are numbered by the server. The model may only cite `[n]`, and the server turns each number into a real URL or removes it. A link can't come from the model | [`agent/answer.py`](backend/volatility_explainer/agent/answer.py) |
| Free-form or unparseable output | The only ways to end a run are the `submit_analysis` or `flag_out_of_scope` tool calls, so the answer always has a schema. If the model writes prose instead, the run returns `incomplete`; the prose is never parsed | [`agent/tool_schemas.py`](backend/volatility_explainer/agent/tool_schemas.py) |
| Runaway loops and spend | At most 7 turns, a 15 s timeout per tool, Haiku, layered caching and prompt caching | [`agent/orchestrator.py`](backend/volatility_explainer/agent/orchestrator.py) |
| Off-topic use or advice-seeking | A scope guardrail runs before any LLM call, and the model has its own out-of-scope exit. The product describes past price action only; it never gives signals or recommendations | [`query/parsing.py`](backend/volatility_explainer/query/parsing.py) |
| A data source fails | Every tool falls back to yfinance. Redis, Supabase, Finnhub and FRED are all optional, and `service.analyze()` never raises | [`tools/`](backend/volatility_explainer/tools/) |
| An upstream API silently changes shape | Live contract tests run weekly and on PRs that touch data code. A failed scheduled run opens an issue | [`tests/tools/test_live_contracts.py`](tests/tools/test_live_contracts.py) |
| A weak or misleading write-up | Plain-code checks score every explanation for known failure modes, including overstating the move, analyst consensus offered as a cause, uncited catalysts and invalid citations. The flags are logged per run and never alter the answer. Real bad write-ups are pinned as regression tests | [`agent/quality.py`](backend/volatility_explainer/agent/quality.py), [`tests/agent/test_quality.py`](tests/agent/test_quality.py) |
| A loop change breaks agent behaviour | Scripted fake Anthropic and OpenAI streams drive the whole loop in tests: tool choice, timeouts, turn limits, terminal tools, prose endings and citations. An API test checks that a client disconnect doesn't cancel the run | [`tests/agent/test_orchestrator.py`](tests/agent/test_orchestrator.py), [`tests/api/test_api.py`](tests/api/test_api.py) |

**Not done yet** (tracked in [AGENTS.md §7](AGENTS.md#7-open-questions--good-places-to-ideate)):
the eval below has no hand-labelled catalysts yet, so it measures grounding, structure, cost and
stability but not whether the model named the *true* cause. Rate limiting and a locked-down CORS
policy are planned for Phase 4.

## Model evaluation: Claude vs. OpenAI

The agent loop talks to models only through a thin provider seam
([`llm/`](backend/volatility_explainer/llm/)): one ~200-line adapter per vendor, and an
orchestrator that never imports a vendor SDK. Each adapter keeps its vendor's specifics:
Claude's explicit cache breakpoints and fine-grained tool streaming, and OpenAI's strict function
schemas with reasoning items sent back each turn. Visitors pick the vendor per run; the model
behind each vendor is server config, so which model runs in production comes down to measurement.

**Method.** [`evals/`](evals/) replays 40 recorded investigations through the unchanged
production loop: every data tool serves a fixture captured after a real trading day, and nothing
else changes. The cases mix notable moves, the day's top movers and calm control stocks, and each
case runs 3 times per model. All 480 runs cost **$1.82** in total. Every score is plain code, with
no judge model: [`evals/README.md`](evals/README.md) lists what each one measures.

| Metric (40 cases × 3 runs each) | Claude Haiku 4.5 *(production at the time)* | Claude Haiku 5.5 | GPT-6 Luna, reasoning low | GPT-6 Luna, reasoning off |
|---|---|---|---|---|
| Ended with a structured answer | 100% | 92% | 100% | 100% |
| Answer fits the schema (tile cap, ranked hypotheses) | 99% | 44% | 100% | 100% |
| Write-up with no quality flag | 8% | 88% | 88% | 88% |
| Explanation within the 40–70 words asked for | 12% | 87% | 92% | 92% |
| Invented citation tags (not `[n]`) | 8% | 1% | 0% | 0% |
| % and $ figures found in the tool data | 96% | 98% | 99% | 100% |
| Looked for news when the move was notable | 100% | 98% | 97% | 100% |
| Model time, median / p95 | 16.7 s / 23.7 s | 8.9 s / 10.6 s | 10.4 s / 12.8 s | 10.8 s / 12.9 s |
| **Cost per 1,000 investigations** | **$13.11** | **$1.04** | **$0.50** | **$0.50** |

Full table, including tool counts and run-to-run stability: [`evals/results/2026-11-09.md`](evals/results/2026-11-09.md).

**What it found**
- **Haiku 4.5, then the production model, costs the most and writes the longest.** It runs 13× to 26×
  the price of the others, 88% of its explanations miss the requested length (almost all by
  running long), and 8% use citation tags like
  `[ref 3]` that the server can't turn into links.
- **Haiku 5.5 is cheaper and faster, but breaks the answer schema** on 56% of its completed runs (a fifth tile,
  or a missing hypothesis rank) and refused 9 in-scope questions as off-topic, 7 of them calm
  stocks where the honest answer was "nothing unusual". The schema breaks happen because Claude
  doesn't validate tool input when its input is streamed in fine-grained chunks. OpenAI's strict
  mode does validate, and both Luna arms produced no schema violations.
- **GPT-6 Luna was the cheapest and most consistent on these checks.** It was half the cost of
  Haiku 5.5, with comparable latency, and turning reasoning off changed nothing measurable here.
- **The eval also found two bugs.** First, the ticker fallback never worked on Haiku 4.5: the
  model wraps its JSON reply in a code fence and the parse error was swallowed. That's fixed.
  Second, after the close, yfinance's daily history lags the live quote, so "today" can be the
  previous day's move. That is now fixed in production: `tools/price.py` joins the live quote
  as today's close when the history doesn't have it yet. The eval keeps its own correction for
  fixtures recorded before the fix ([details](evals/README.md#how-a-case-is-replayed)).

**What changed.** Both Haiku 5.5 failures were fixed before switching: a clearer scope rule in
the prompt, and code that re-applies the answer contract (`answer.normalize_answer`: malformed entries
dropped, at most 4 tiles, hypotheses ranked by the order written). A re-run on the same 40 cases
([`2026-11-10.md`](evals/results/2026-11-10.md), one run each, $0.08) had Haiku 5.5 completing
100% of runs (up from 92%) and passing the schema check on 98% (up from 44%, mostly because the
code now repairs the answer). Claude runs moved to Haiku 5.5 on 2026-11-10, and GPT-6 Luna became
the default in the model picker.

**Caveats.** The prompts were written and tuned against Claude, so vendor-specific prompt tuning
could move these numbers. The quality flags are regex heuristics with known false positives (for
example, a negated "out-of-the-ordinary" still counts as overstating). The "notable move" row
above counts some calm days as notable: capture picked its `move` group from the lagging daily
history, and about half of those were calm on the day replayed (the screener's top movers were
unaffected). Case sampling now leaves those out
([details](evals/README.md#how-a-case-is-replayed)). None of this measures
whether the model named the *true* catalyst; that needs hand-labelled cases and a judge model,
the next step in [`evals/README.md`](evals/README.md#next-steps-not-built). The model choice
above rests on cost, latency and structure; it should be revisited once accuracy is measured too.

```bash
python -m evals.run --models anthropic:claude-haiku-5-5,openai:gpt-6-luna@low \
    --cases 40 --repeats 3 --budget 5 --out evals/results/<date>.jsonl
python -m evals.report evals/results/<date>.jsonl --write
```

## Engineering decisions

- **Deterministic before agentic.** Price data and the event calendar are fetched in parallel
  before the first model call. They're added to the conversation as if the model had requested
  them, which saves an LLM round trip.
- **The write-up runs in reasoning order.** The "what happened" paragraph is templated in code and
  streams within seconds. The model's "why" is the last field of the schema, so it's written
  *after* the evidence tiles and ranked hypotheses it summarises.
- **Runs survive a closed tab.** Each investigation runs as its own task and streams over SSE. An
  abandoned run still finishes and fills the cache.
- **Cheap to run.** Free data sources work with no paid keys, the backend scales to zero, and
  caching happens at four layers.
- **Every tradeoff is written down.** [AGENTS.md](AGENTS.md) holds the decision log, each entry
  with why, cost and when to revisit, plus the invariants the code must keep.

## Quickstart

Run it locally in two terminals. Needs Python ≥ 3.11 and Node ≥ 20.9.

**1. Backend** (http://localhost:8080):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # set OPENAI_API_KEY and/or ANTHROPIC_API_KEY; the rest is optional
pytest -q                         # offline, no keys needed
uvicorn volatility_explainer.api.app:app --reload --port 8080
```

**2. Frontend** (http://localhost:3000, calls the backend on `:8080` by default):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and ask about a ticker. The model picker in the query bar defaults
to OpenAI, so switch it to Claude if you only set `ANTHROPIC_API_KEY`.

Only an LLM key is required. Without `FINNHUB_API_KEY` and `FRED_API_KEY` every tool falls back
to yfinance; without `REDIS_URL` nothing is cached across runs; without the Supabase settings no
usage is logged. A `REDIS_URL` shared with a deployed instance shares its cache too, so a local
code change may not show for a ticker until its cached data expires (15 minutes for prices).

Without the frontend, stream an investigation straight from the API (`provider` is `openai` or
`anthropic`; if omitted, `LLM_PROVIDER` decides, default `anthropic`):

```bash
curl -N -X POST localhost:8080/v1/analyze -H 'content-type: application/json' \
     -d '{"query": "why is TSLA down", "provider": "openai"}'
```

Or run the backend image instead of step 1: `docker compose up --build` (serves on `:8080`).

To check write-up quality, save runs while you use the app, then summarise their quality flags:

```bash
VOLX_SAVE_RUNS=runs.jsonl uvicorn volatility_explainer.api.app:app --port 8080
python scripts/quality_report.py runs.jsonl            # add --show <flag> to read offenders
```

## Documentation

Each kind of information lives in one place:

| Doc | Read it for |
|---|---|
| [AGENTS.md](AGENTS.md) | The project brief: goals, invariants, decision log, open questions, a file-by-file repo map, and where to change things. Start here to work on the code, whether you're a person or an AI assistant |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Request lifecycle, the `/v1` API and SSE contract, caching, deployment, configuration |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What's next, known security and code-quality debt, and what's out of scope |
| [evals/README.md](evals/README.md) | How the model comparison works and what each score measures |
| [docs/sql/](docs/sql/) | Supabase schema changes to run by hand **before** deploying the code that needs them |
| [PRIVACY.md](PRIVACY.md) | What gets logged |

## Stack

| Layer | Choice |
|---|---|
| Agent | GPT-6 Luna or Claude Haiku 5.5 via the `llm/` seam, tool-use loop (max 7 turns), streaming, prompt caching |
| API | FastAPI + `sse-starlette`, versioned `/v1`, fully async |
| Frontend | Next.js 16 (App Router) + React 19 + Tailwind v4 + shadcn/ui, static export |
| Data | Finnhub (quotes, news), FRED (macro), yfinance (history, options, analyst, sector, fallback) |
| Cache / analytics | Redis (optional) · Supabase usage log (optional) · GA4 |
| Quality | pytest · ruff · eslint · tsc · weekly live contract tests · heuristic write-up checks · replay eval harness (`evals/`) |
| Deploy | GitHub Actions → Docker Hub → Cloud Run (backend) · Cloudflare Pages (frontend) |

---

Market Explainer describes past price action for information and education. It is not financial
advice.
