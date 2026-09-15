# Backlog — security & code quality

Known debt from a grep-based + targeted-reading scan (not a full audit). Product features and
phase work live in [docs/ROADMAP.md](docs/ROADMAP.md). The retired Streamlit UI's issues went with
it — the stored-XSS class in particular is gone by construction: React escapes by default, there
is no `dangerouslySetInnerHTML` in `frontend/`, and `components/md.tsx` renders only `**bold**`
from model output, never links or HTML.

Paths below are relative to `backend/volatility_explainer/`.

---

## Security & spend

### 🟠 MEDIUM — no rate limiting on `POST /v1/analyze`
Every call can trigger paid LLM turns, and nothing bounds request volume per client or per day.
Planned for Phase 4 (token bucket + daily spend guard).

### 🟡 LOW — CORS is `allow_origins=["*"]`
In `api/app.py`. Tighten to the frontend origin in Phase 4.

### 🟡 LOW — `SUPABASE_KEY` is expected to be the `service_role` key
Safe only because `analytics/supabase_logger.py` runs exclusively server-side. If logging ever
moves client-side, that key would bypass Row Level Security entirely. Worth a callout comment next
to the setting in `config.py`.

### 🟡 LOW — raw user query text is logged to Supabase unsanitized
Not a code vulnerability, but free-text queries could contain PII. Worth a retention or
anonymization policy (TTL on `query_log`, or dropping the raw `query` column) before this goes
beyond a personal demo.

---

## Code quality

### 🟡 MEDIUM — chart falls back to synthetic random prices
`_synthetic_price_history()` in `marketdata/snapshots.py` returns a seeded random walk when
yfinance fails, and the API serves it as a normal `PriceHistory` — the frontend can't tell it from
real data. Prefer surfacing the failure (empty points + an "unavailable" state).

### 🟡 MEDIUM — silent `except Exception: pass` blocks
No trail when a fallback path fails ("why did FRED never return data?"):
- `tools/macro.py` — `fetch_macro`, FRED branch
- `query/parsing.py` — `_resolve_ticker_llm`
- `query/parsing.py` — `_resolve_ticker`

These are deliberate fallback boundaries and shouldn't raise, but a one-line log costs nothing.

### 🟡 MEDIUM — mixed `print` and `logging`
About 25 `print` calls (orchestrator, service, a few tools) carry the operational timings, while
clients, analyst, events and analytics use `logging`. Hard to filter or ship to a log backend.
Standardise on `logging` (or structured traces) — see ROADMAP.

### 🟢 LOW — dependencies pinned with unbounded `>=`
`pyproject.toml` has no upper bounds except `yfinance` and `ruff`. A fresh install could pull an
untested future major of `anthropic`, `fastapi`, etc. Consider upper bounds or a lockfile if
reproducibility starts to matter.

### 🟢 LOW — hand-maintained TypeScript mirror of the API
`frontend/lib/api.ts` can drift from `api/schemas.py` with no automated check.

---

## Not flagged (checked, looked clean)
- No `eval`/`exec`/`pickle.load`/`os.system`/`shell=True` anywhere.
- No TLS verification bypasses (`verify=False`).
- No SQL injection surface — the only DB write (`supabase_logger.py`) uses the Supabase client's
  parameterized `.insert()`, not raw SQL.
- No bare `except:` clauses.
- No hardcoded secrets: `.env` is gitignored and was never committed; every key loads via
  `pydantic-settings` + `SecretStr` and is never printed. (The GA4 measurement ID in
  `frontend/components/analytics.tsx` is a public value.)
