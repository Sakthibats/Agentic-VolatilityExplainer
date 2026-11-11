# Roadmap

Where the project has been, what's next, and what is deliberately out of scope. Goals and the
reasoning behind these choices are in [AGENTS.md](../AGENTS.md); known debt is in
[BACKLOG.md](../BACKLOG.md).

## Where it came from

The project started as a Streamlit monolith and was migrated to the current FastAPI + Next.js
stack in four phases (0–3: repo restructure, `/v1` API, async backend, new frontend), all done.
Phase 4 is next.

## Phase 4 — metering and rate limiting (next, not started)

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

1. **Eval labels and a judge** — the replay harness and automatic scorers exist (`evals/`); add
   hand-labelled catalysts and a judge model to score catalyst recall, abstention and calibration.
2. **Structured observability** — per-run traces (turns, tools, tokens, cache hits, cost) in place of
   `print` logging.
3. **Real MCP server** — expose `tools/` over MCP for external clients.
4. **Historical IV rank** — replace the intra-chain IV percentile with a proper 52-week rank
   (needs stored IV history).
5. **Typed contract** — generate `frontend/lib/api.ts` from the OpenAPI schema, or add a contract test.
6. **Product breadth** — crypto and FX coverage, multi-ticker comparisons, persistent query history.

## Explicitly out of scope

- Payment collection (Stripe etc.). The planned progression is coffee link → freemium daily credits
  → credit packs + subscription tiers, and only once usage justifies it.
- Accounts and authentication.
- Telegram / Slack adapters (removed from scope 2026-07-27).
