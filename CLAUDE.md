# Agentic Market Explainer — ground rules

Monorepo, mid-migration from a Streamlit monolith to a decoupled stack. Target architecture:

- `backend/volatility_explainer/` — the product: `api/` (FastAPI, SSE — schemas.py is the contract), `query/` (scope guardrail + ticker resolution), `marketdata/`, agent orchestrator, MCP-shaped tools, API clients. Will grow an empty-for-now `billing/` boundary in Phase 4.
- `frontend/` — Next.js 16 (App Router) + Tailwind v4 + shadcn/ui. Design tokens live in `app/globals.css` (light = white+blue brand, dark = trading terminal; both from the same variables). `lib/api.ts` mirrors the backend schemas — keep in sync. Deploys to Vercel; backend keeps the Docker pipeline at api.market-explainer.com.
- The legacy Streamlit UI (`apps/`) is deleted; its About copy now lives in `frontend/app/about/page.tsx`.

Migration phases (0 restructure+tests ✅ → 1 FastAPI+SSE ✅ → 2 async refactor ✅ → 3 Next.js frontend ✅ (Vercel deploy pending) → 4 metering/rate limiting). Telegram/Slack adapters and payment collection are explicitly out of scope for now — but keep the usage-ledger and billing module boundaries clean so freemium can be added later without rearchitecting.

## Rules

- **API-first.** All user form factors talk to the backend only through the versioned REST/SSE API (`/v1/...`). Never let frontend code import backend modules directly once the API exists. The SSE event schema (Pydantic models) is the source of truth for the contract.
- **Deterministic first, agentic second.** Price/vol math happens in plain code before any LLM call; the model can only end its turn via `submit_analysis` or `flag_out_of_scope`, never free text. Preserve this in any orchestrator change.
- **Degrade gracefully.** Every data source keeps a yfinance fallback; Redis and Supabase must remain optional (app runs end-to-end with only `ANTHROPIC_API_KEY`).
- **Backend is async** (since Phase 2): the orchestrator and service are `async` — LLM calls awaited natively (`AsyncAnthropic`), per-turn tool fan-out via `asyncio.gather`. Tool implementations stay sync on purpose (yfinance is sync-only and every tool can fall back to it) and run via `asyncio.to_thread`; never call them directly on the event loop. Client disconnect mid-SSE must NOT cancel the investigation (finish-and-cache).
- **UI palette:** dual theme. Light = white + blue only (#1565C0 primary family) — never coral or orange. Dark = trading-terminal look. Both themes from shared Tailwind tokens, designed together.
- **Tests before refactors.** Orchestrator behavior is pinned by `tests/agent/test_orchestrator.py` (scripted fake Anthropic client — no network). Keep it green; extend it when the loop changes.

## Commands

```bash
pip install -e ".[dev]"        # after pulling structural changes
pytest -q                      # all tests, no network needed
ruff check backend tests       # lint (CI runs both on every push)
uvicorn volatility_explainer.api.app:app --reload --port 8080   # run the API locally
cd frontend && npm run dev     # frontend on :3000, talks to :8080 via NEXT_PUBLIC_API_URL
```
