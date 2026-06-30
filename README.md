# Agentic Volatility Explainer

**Ask "why did this stock move?" and get a grounded, evidence-backed answer in plain English — not a generic recap.**

Type a ticker, a company name, or a plain question ("why is TSLA down today", "is gold overbought") and an LLM-driven agent investigates: it pulls real price/volatility data, decides — based on whether the move is actually unusual — whether it's worth checking news, options positioning, broader market context, or upcoming catalysts, then synthesizes ranked hypotheses with confidence levels, all backed by real numbers and never fabricated ones.

```
"why did AAPL drop today?"
        ↓
  ┌─────────────────────────────────────────────────────────┐
  │  1. Pull price + realized vol — always, no LLM call      │
  │  2. Move > 2× normal range?  → fan out news + options     │
  │     in parallel (deterministic, zero LLM round trips)     │
  │  3. Claude (tool-use loop) decides if anything ELSE is    │
  │     needed: macro context? earnings/FOMC proximity?       │
  │  4. Synthesize → ranked hypotheses, confidence, caveats   │
  └─────────────────────────────────────────────────────────┘
        ↓
  "AAPL fell 4.1% — more than 2x its normal daily swing.
   Bloomberg reported a supply-chain delay this morning..."
```

## Why this project is interesting

This isn't a prompt-wrapped chatbot. It's an agent designed around a deliberate cost/latency/accuracy tradeoff:

- **Hybrid deterministic + agentic pipeline.** Price data, and (when the move is statistically significant) news and options data, are fetched *before* the LLM is ever called — in parallel, via a thread pool — and spliced into the conversation as if the model had called them itself. The model only spends a reasoning turn on calls that are genuinely conditional (macro context, earnings/FOMC proximity). This cuts latency and token spend on every run while keeping the agent's tool-use loop intact for the cases that actually need judgment. See [`orchestrator.py`](src/volatility_explainer/agent/orchestrator.py).
- **Statistical significance gate, not vibes.** A move only triggers the expensive news/options fan-out if it exceeds ~2× the stock's own realized volatility (`change_pct` vs. `realized_vol_annualized_pct / sqrt(252)`) — so a normal 1% drift on a high-beta name doesn't get the same treatment as a genuine outlier move.
- **Prompt-engineered for trust, not just fluency.** The system prompt enforces a strict evidence discipline: every number in the output must trace back to a real tool result, missing data must say "Data unavailable" rather than be invented, and the model is explicitly told never to call a tool that's already been answered (with a cache fallback in code in case it does anyway). Output is forced into a single JSON contract for the UI, with a guardrail that hard-refuses non-market questions.
- **Written for a beginner, audited for jargon.** The prompt explicitly bans terms like "ATM IV", "skew", or "max pain" appearing unexplained — every claim has to be translated into plain English with the number attached, e.g. *"options traders are betting the stock settles near $98"* instead of *"max pain is $98."*
- **Resilient data layer.** Every market-data source (price, news, macro) tries a primary client (Alpaca / Finnhub / FRED) and falls back to `yfinance` on failure or missing API key — the app degrades gracefully instead of breaking when a key is unset.
- **Real options analytics, not a single number.** Beyond ATM implied volatility and IV rank, the options-positioning tool computes max pain, call/put open-interest "walls" (support/resistance), IV term structure trend across the 2–4 week horizon, and unusual volume-vs-open-interest activity to flag fresh positioning vs. stale interest.
- **Smart query parsing.** The search bar resolves tickers, company names ("tesla" → TSLA), and concept phrases ("gold", "the market", "S&P 500") through a layered resolver, with a guardrail tuned to avoid false positives (e.g. "I want to bake a cake today" shouldn't resolve to the ticker `CAKE`).
- **Latency-instrumented by design.** Every run logs per-tool and per-LLM-turn timing (`[agent] get_news 320ms`, `[llm] turn 2 (synthesis) 850ms`) so the deterministic/agentic split is empirically justified, not just assumed.

## Architecture

```
apps/streamlit_app.py  ──►  agent/orchestrator.py  ──►  Claude (tool-use loop)
                                    │
                                    ▼
                           mcp/tools/  (also exposed as a standalone MCP server)
                           ├── price.py     → clients/alpaca.py   (yfinance fallback)
                           ├── options.py   → yfinance options chains
                           ├── news.py      → clients/finnhub.py  (yfinance fallback)
                           ├── events.py    → yfinance earnings + hardcoded FOMC calendar
                           └── macro.py     → clients/fred.py     (yfinance VIX fallback)
                                    │
                                    ▼
                           domain/volatility.py  (pure business logic, e.g. IV rank)
```

The same tool functions back two surfaces: the in-process agent loop (`agent/orchestrator.py`) for the demo UI/API, and a standalone [MCP](https://modelcontextprotocol.io/) server (`mcp/server.py`) exposing the identical tools for any MCP-compatible client (Claude Desktop, etc.).

## Project layout

```
src/volatility_explainer/
├── config.py           # pydantic-settings, validated secrets
├── clients/             # external API adapters (Alpaca, Finnhub, FRED)
├── domain/              # pure business logic
├── agent/                # orchestrator + system prompt
├── mcp/                  # MCP server + tool implementations
└── api/                   # FastAPI routes

apps/
├── streamlit_app.py     # demo UI — animated investigation, evidence tiles, hypotheses
└── ui/                   # search parsing, guardrails, theming, rendering

tests/
├── unit/                 # domain logic
└── integration/          # mocked HTTP clients
```

## Stack

| Layer | Choice |
|---|---|
| Agent | Anthropic Claude (Haiku 4.5), tool-use loop, max 7 turns |
| Tool protocol | [MCP](https://modelcontextprotocol.io/) — tools are dual-exposed in-process and as a server |
| API | FastAPI |
| UI | Streamlit |
| Data | Alpaca (price), Finnhub (news), FRED (macro) — all with `yfinance` fallback |
| Config | Pydantic Settings, validated `.env` secrets |
| Testing | pytest + respx (mocked HTTP) |

## Quick start

```bash
cp .env.example .env   # fill in API keys (see below)
pip install -e ".[dev]"
pytest
streamlit run apps/streamlit_app.py
```

`yfinance` requires no API key, so the app runs end-to-end with **zero keys configured** — Alpaca/Finnhub/FRED are optional upgrades for better data quality and rate limits. `ANTHROPIC_API_KEY` is required for the agent's reasoning step.

## Run services separately

```bash
# Demo UI
streamlit run apps/streamlit_app.py

# Production API
uvicorn volatility_explainer.api.routes:app --reload

# MCP tool server (for use with Claude Desktop or other MCP clients)
python -m volatility_explainer.mcp.server
```

## Example

**Query:** `why did NVDA drop today`

1. Price tool runs immediately: NVDA down 3.2%, realized vol implies a normal daily move of ~1.4% → **2.3× normal, flagged significant**.
2. News, options data, and options positioning fetch in parallel (no LLM call yet).
3. Claude reviews the pre-fetched evidence, decides macro context is needed (broad tech selloff?), calls `get_macro`.
4. Synthesizes: *"NVDA fell 3.2% — more than double its normal daily move — alongside a broad tech selloff (VIX +8%) following a competitor's disappointing guidance. Options traders lean slightly bearish, expecting the stock to settle near $118 over the next few weeks."*
5. Ranked hypotheses returned with confidence and caveats, each traceable to a real tool result.
