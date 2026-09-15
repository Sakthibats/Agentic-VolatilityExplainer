# Roadmap

Where the project has been, what's next, and what is deliberately out of scope. Goals and the
reasoning behind these choices are in [AGENTS.md](../AGENTS.md); known debt is in
[BACKLOG.md](../BACKLOG.md).

## Migration: Streamlit monolith → decoupled stack

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo restructure (`backend/`, `tests/`), orchestrator pinned by tests | ✅ |
| 1 | FastAPI + SSE skeleton, versioned `/v1`; Streamlit `apps/` deleted | ✅ |
| 2 | Async refactor: `AsyncAnthropic`, per-turn `asyncio.gather` fan-out, tools on threads | ✅ |
| 3 | Next.js frontend (dual theme), deployed to Cloudflare Pages; backend on Cloud Run | ✅ |
| 4 | Metering and rate limiting | **Next — not started** |

Since Phase 3: streaming summary events, deterministic events prefetch, analyst and sector tools,
weekly live contract tests, and a 2026-09 cleanup (`mcp/tools/` → `tools/`, tool schemas split out
of the orchestrator, model ID moved into config, frontend lint made blocking).

## Phase 4 — metering and rate limiting

The goal is to make freemium a *configuration change later*, not a rearchitecture — without
building payments now.

- **Rate-limit middleware** — a Redis token bucket per session/IP, starting **log-only** (or with
  generous limits); a no-op without Redis, like the other optional infrastructure.
- **Global spend guard** — a daily ceiling on LLM calls, since every investigation costs money.
- **Usage ledger** — a per-investigation record (session, ticker, tokens, cost estimate) in
  Supabase. The existing `query_log` is analytics; the ledger is the future billing source of truth.
- **`billing/` module boundary** — an empty-for-now package that the ledger and limits report
  through, so a payment provider can be slotted in later.
- **Tighten CORS** from `*` to the frontend origin.
- ~~Buy-me-a-coffee link~~ — already shipped (`frontend/components/support-button.tsx`).

## Candidates after Phase 4

Ordered roughly by value to the portfolio goal. None are committed.

1. **Offline eval harness** — golden set of historical moves with known catalysts; score catalyst
   recall, number fidelity and hypothesis calibration; use it to compare prompts and models.
2. **Structured observability** — per-run traces (turns, tools, tokens, cache hits, cost) in place of
   `print` logging.
3. **Honest chart fallback** — remove the synthetic random-walk history (BACKLOG).
4. **Real MCP server** — expose `tools/` over MCP for external clients.
5. **Historical IV rank** — replace the intra-chain IV percentile with a proper 52-week rank
   (needs stored IV history).
6. **Typed contract** — generate `frontend/lib/api.ts` from the OpenAPI schema, or add a contract test.
7. **Product breadth** — crypto and FX coverage, multi-ticker comparisons, persistent query history.

## Explicitly out of scope

- Payment collection (Stripe etc.). The planned progression is coffee link → freemium daily credits
  → credit packs + subscription tiers, and only once usage justifies it.
- Accounts and authentication.
- Telegram / Slack adapters (removed from scope 2026-07-27).
