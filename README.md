# Agentic Market Explainer

**Every stock move gets a headline. Almost none of them get an investigation.**

Ask "why is TSLA down today" or "is gold overbought" and instead of a canned recap, an LLM-driven agent actually investigates — pulling real price and volatility data first, deciding *for itself* whether the move is even statistically unusual, then fanning out to news, options positioning, macro context, or upcoming catalysts only when the evidence warrants it. It comes back with ranked hypotheses, confidence levels, and a hard rule: every number is real, or it says so.

```
"why did AAPL drop today?"
        ↓
  ┌─────────────────────────────────────────────────────────┐
  │  1. Pull price + realized vol — always, no LLM call     │
  │  2. Move > 2× normal range?  → fan out news + options   │
  │     in parallel (deterministic, zero LLM round trips)   │
  │  3. Claude (tool-use loop) decides if anything ELSE is  │
  │     needed: macro context? earnings/FOMC proximity?     │
  │  4. Synthesize → ranked hypotheses, confidence, caveats │
  └─────────────────────────────────────────────────────────┘
        ↓
  "AAPL fell 4.1% — more than 2x its normal daily swing.
   Bloomberg reported a supply-chain delay this morning..."
```

## Not a prompt-wrapped chatbot

This is an agent built around a deliberate cost/latency/accuracy tradeoff — it only thinks (and spends tokens) when the situation actually calls for it:

- **Hybrid deterministic + agentic pipeline.** Price data — and, only if the move is significant, news and options data — is fetched *before* the LLM is ever called, in parallel via a thread pool, then spliced into the conversation as if the model had called it itself. Claude only spends a reasoning turn on calls that are genuinely conditional (macro context, earnings/FOMC proximity). Same accuracy, a fraction of the latency and token spend. See [`orchestrator.py`](src/volatility_explainer/agent/orchestrator.py).
- **Statistical significance gate, not vibes.** The expensive news/options fan-out only fires if a move exceeds ~2× the stock's own realized volatility — a normal 1% drift on a high-beta name doesn't get the same treatment as a genuine outlier.
- **Engineered for trust, not fluency.** Every number in the output must trace back to a real tool result; missing data says "Data unavailable" instead of being invented; the model is told never to re-call an already-answered tool (with a code-level cache fallback in case it does anyway); output is forced into a single JSON contract, with a guardrail that hard-refuses non-market questions.
- **No jargon allowed.** The prompt bans unexplained terms like "ATM IV," "skew," or "max pain" — every claim gets translated into plain English with the number attached, e.g. *"options traders are betting the stock settles near $98"* instead of *"max pain is $98."*
- **Degrades gracefully, never breaks.** Every data source (price, news, macro) tries a primary client (Alpaca / Finnhub / FRED) and silently falls back to `yfinance` on failure or missing key.
- **Real options analytics, not a single number.** Max pain, call/put open-interest "walls," IV term structure trend, and unusual volume-vs-open-interest activity — on top of ATM IV and IV rank.
- **Smart query parsing.** Resolves tickers, company names ("tesla" → TSLA), and concepts ("gold," "the market") through a layered resolver tuned against false positives (e.g. "bake a cake" won't resolve to the ticker `CAKE`).
- **Latency-instrumented by design.** Every run logs per-tool and per-turn timing, so the deterministic/agentic split is an empirical claim, not an assumption.

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

The same tool functions back two surfaces: the in-process agent loop (`agent/orchestrator.py`) for the Streamlit demo, and a standalone [MCP](https://modelcontextprotocol.io/) server (`mcp/server.py`) exposing the identical tools for any MCP-compatible client (Claude Desktop, etc.) — see [MCP server](#mcp-server) below.

## Project layout

```
src/volatility_explainer/
├── config.py            # pydantic-settings, validated secrets
├── clients/              # external API adapters (Alpaca, Finnhub, FRED)
├── domain/                # pure business logic
├── agent/                  # orchestrator + system prompt
└── mcp/                     # MCP server + tool implementations

apps/
├── streamlit_app.py     # demo UI — animated investigation, evidence tiles, hypotheses
└── ui/                    # search parsing, guardrails, theming, rendering

tests/
└── mcp/tools/             # tool-level unit tests (mocked data sources)
```

## Stack

| Layer | Choice |
|---|---|
| Agent | Anthropic Claude (Haiku 4.5), tool-use loop, max 7 turns |
| Tool protocol | [MCP](https://modelcontextprotocol.io/) — tools are dual-exposed in-process and as a server |
| UI | Streamlit |
| Data | Alpaca (price), Finnhub (news), FRED (macro) — all with `yfinance` fallback |
| Config | Pydantic Settings, validated `.env` secrets |
| Testing | pytest (mocked HTTP clients) |

## Quick start

```bash
cp .env.example .env   # fill in API keys (see below)
pip install -e ".[dev]"
pytest
streamlit run apps/streamlit_app.py
```

`yfinance` requires no API key, so the app runs end-to-end with **zero keys configured** — Alpaca/Finnhub/FRED are optional upgrades for better data quality and rate limits. `ANTHROPIC_API_KEY` is required for the agent's reasoning step.

Lint before committing: `ruff check .`

## MCP server

The same tools also run as a standalone [MCP](https://modelcontextprotocol.io/) server for any MCP-compatible client (Claude Desktop, etc.):

```bash
python -m volatility_explainer.mcp.server
```

## Example

**Query:** `why did NVDA drop today`

1. Price tool runs immediately: NVDA down 3.2%, realized vol implies a normal daily move of ~1.4% → **2.3× normal, flagged significant**.
2. News, options data, and options positioning fetch in parallel (no LLM call yet).
3. Claude reviews the pre-fetched evidence, decides macro context is needed (broad tech selloff?), calls `get_macro`.
4. Synthesizes: *"NVDA fell 3.2% — more than double its normal daily move — alongside a broad tech selloff (VIX +8%) following a competitor's disappointing guidance. Options traders lean slightly bearish, expecting the stock to settle near $118 over the next few weeks."*
5. Ranked hypotheses returned with confidence and caveats, each traceable to a real tool result.
