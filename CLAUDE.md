# Agentic Market Explainer — ground rules

Monorepo, mid-migration from a Streamlit monolith to a decoupled stack. Target architecture:

- `backend/volatility_explainer/` — the product: agent orchestrator, MCP-shaped tools, API clients. Will grow `api/` (FastAPI, SSE) and an empty-for-now `billing/` boundary.
- `frontend/` — Next.js + Tailwind + shadcn/ui (Phase 3; does not exist yet). Deploys to Vercel; backend keeps the Docker pipeline at api.market-explainer.com.
- `apps/` — legacy Streamlit UI. Being deleted in Phase 1; don't invest in it.

Migration phases (0 restructure+tests → 1 FastAPI+SSE, delete apps/ → 2 async refactor → 3 Next.js frontend → 4 metering/rate limiting). Telegram/Slack adapters and payment collection are explicitly out of scope for now — but keep the usage-ledger and billing module boundaries clean so freemium can be added later without rearchitecting.

## Rules

- **API-first.** All user form factors talk to the backend only through the versioned REST/SSE API (`/v1/...`). Never let frontend code import backend modules directly once the API exists. The SSE event schema (Pydantic models) is the source of truth for the contract.
- **Deterministic first, agentic second.** Price/vol math happens in plain code before any LLM call; the model can only end its turn via `submit_analysis` or `flag_out_of_scope`, never free text. Preserve this in any orchestrator change.
- **Degrade gracefully.** Every data source keeps a yfinance fallback; Redis and Supabase must remain optional (app runs end-to-end with only `ANTHROPIC_API_KEY`).
- **Backend goes async** (from Phase 2): `httpx.AsyncClient`, `async def` tools, yfinance wrapped in a thread; no new sync I/O on the request path.
- **UI palette:** dual theme. Light = white + blue only (#1565C0 primary family) — never coral or orange. Dark = trading-terminal look. Both themes from shared Tailwind tokens, designed together.
- **Tests before refactors.** Orchestrator behavior is pinned by `tests/agent/test_orchestrator.py` (scripted fake Anthropic client — no network). Keep it green; extend it when the loop changes.

## Commands

```bash
pip install -e ".[dev]"        # after pulling structural changes
pytest -q                      # all tests, no network needed
ruff check backend apps tests  # lint (CI runs both on every push)
```
