# Volatility Explainer

An agentic tool that explains **why** a stock's implied volatility is elevated or depressed — by gathering price action, options data, news, macro context, and upcoming events, then synthesizing a ranked set of hypotheses.

## Architecture

```
apps/streamlit_app.py  ──►  agent/orchestrator.py  ──►  LLM reasoning loop
                                    │
                                    ▼
                           mcp/server.py (separate process)
                           ├── tools/price.py    → clients/alpaca.py
                           ├── tools/options.py
                           ├── tools/news.py     → clients/finnhub.py
                           ├── tools/events.py
                           └── tools/macro.py     → clients/fred.py
                                    │
                                    ▼
                           domain/volatility.py  (pure business logic)
```

Production API entrypoint: `volatility_explainer.api.routes` (FastAPI).

## Project layout

```
src/volatility_explainer/
├── config.py           # pydantic-settings, validated secrets
├── clients/            # external API adapters
├── domain/             # pure business logic
├── agent/              # orchestrator + prompts
├── mcp/                # MCP server + tool wrappers
└── api/                # FastAPI routes

apps/streamlit_app.py     # demo UI
tests/unit/               # domain logic
tests/integration/        # mocked HTTP clients
```

## Quick start

```bash
cp .env.example .env   # fill in API keys
pip install -e ".[dev]"
pytest
streamlit run apps/streamlit_app.py
```

## Run services separately

```bash
# Demo UI
streamlit run apps/streamlit_app.py

# Production API
uvicorn volatility_explainer.api.routes:app --reload

# MCP tool server
python -m volatility_explainer.mcp.server
```

## Stack

- **Frontend:** Streamlit (`apps/`)
- **API:** FastAPI (`src/volatility_explainer/api/`)
- **Agent:** Python orchestrator with tool-calling loop
- **Tools:** MCP server exposing market-data fetchers
- **Config:** Pydantic Settings (`.env` for local dev)
