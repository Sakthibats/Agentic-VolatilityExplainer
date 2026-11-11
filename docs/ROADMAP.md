# Roadmap

What's next, the known debt, and what is deliberately out of scope. Goals and the reasoning
behind these choices are in [AGENTS.md](../AGENTS.md).

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

## Known debt

From a grep-based scan plus targeted reading, not a full audit. Paths are relative to
`backend/volatility_explainer/`.

### Security and spend

| Severity | Issue | Fix |
|---|---|---|
| 🟠 Medium | No rate limiting on `POST /v1/analyze`: every call can trigger paid LLM turns, with no bound per client or per day | Phase 4: token bucket + daily spend guard |
| 🟡 Low | CORS is `allow_origins=["*"]` in `api/app.py` | Phase 4: the frontend origin only |
| 🟡 Low | `SUPABASE_KEY` is expected to be the `service_role` key. Safe only because `analytics/supabase_logger.py` runs server-side; client-side, it would bypass Row Level Security | A warning comment next to the setting in `config.py` |
| 🟡 Low | Raw query text is logged to Supabase. Free text could contain personal data | A retention policy (TTL on `query_log`) or drop the raw `query` column |

### Correctness and code quality

| Severity | Issue | Fix |
|---|---|---|
| 🟠 Medium | After the close, yfinance's daily history lags the live quote, so "today" can be the previous day's move. The eval corrects its own data (`evals/replay.normalize_price`); production doesn't | Take "today" from the live quote in `tools/price.py`, as the eval does |
| 🟡 Medium | Silent `except Exception: pass` at three fallback boundaries (`tools/macro.py` FRED branch; `query/parsing.py` `_resolve_ticker_llm` and `_resolve_ticker`): no trail when a fallback fails | A one-line log each; they should still not raise |
| 🟡 Medium | Mixed `print` and `logging`. The operational lines (orchestrator timings, the `[quality]` line, service) use `print`; clients, analyst, events and analytics use `logging` | Candidate 2. Add a logging config first: none exists, so `logger.info` output is dropped today |
| 🟡 Low | The `query_log` table isn't defined in the repo, only later changes (`docs/sql/`). A fresh Supabase project can't be rebuilt, and nothing checks the logger's payload against the table | A full `create table` in `docs/sql/`; Supabase CLI migrations later |
| 🟢 Low | Dependencies use unbounded `>=` except `yfinance` and `ruff`, so a fresh install can pull an untested major version | Upper bounds or a lockfile |
| 🟢 Low | `frontend/lib/api.ts` mirrors `api/schemas.py` by hand, with no drift check | Candidate 5 |

### Checked and clean

- No `eval`/`exec`/`pickle.load`/`os.system`/`shell=True`, no `verify=False`, no bare `except:`.
- No SQL injection surface: the only DB write uses the Supabase client's parameterized `.insert()`.
- No hardcoded secrets: `.env` is gitignored and was never committed; keys load via
  `pydantic-settings` + `SecretStr` and are never printed. The GA4 ID in
  `frontend/components/analytics.tsx` is public by design.
- No stored-XSS path: React escapes by default, there is no `dangerouslySetInnerHTML`, and
  `components/md.tsx` renders only `**bold**` and `[n]` citations from model output.

## Explicitly out of scope

- Payment collection (Stripe etc.). The planned progression is coffee link → freemium daily credits
  → credit packs + subscription tiers, and only once usage justifies it.
- Accounts and authentication.
- Telegram / Slack adapters (removed from scope 2026-07-27).
