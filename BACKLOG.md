# Backlog — security & code quality

Open follow-ups from a grep-based + targeted-reading scan (not a full audit). Items that
only applied to the retired Streamlit UI (`apps/`) have been dropped along with it — the
stored-XSS class in particular is gone by construction now: React escapes by default, there
is no `dangerouslySetInnerHTML` anywhere in `frontend/`, and `components/md.tsx` renders
only `**bold**` from model output, never links or HTML.

---

## Secrets handling

### 🟡 LOW — `SUPABASE_KEY` is expected to be the `service_role` key
Safe *only* because `analytics/supabase_logger.py` runs exclusively server-side. If this
logging ever moves client-side, that privileged key would bypass Row Level Security
entirely. Worth a callout comment next to the setting in `config.py`.

### 🟡 LOW — raw user query text is logged to Supabase unsanitized
Not a code vulnerability, but free-text queries could contain PII. Worth a
retention/anonymization policy (TTL on `query_log`, or dropping the raw `query` column)
before this goes beyond a personal demo.

---

## Code quality

### 🟡 MEDIUM — silent `except Exception: pass` blocks
No logging on failure, so "why did FRED never return data?" leaves no trail:
- [macro.py:17](backend/volatility_explainer/mcp/tools/macro.py#L17)
- [events.py:64](backend/volatility_explainer/mcp/tools/events.py#L64)
- [parsing.py:156](backend/volatility_explainer/query/parsing.py#L156)
- [parsing.py:190](backend/volatility_explainer/query/parsing.py#L190)

These are deliberate fallback boundaries and shouldn't raise — but a one-line
`print(f"... FAILED — {exc}")` (already the pattern elsewhere in the same files) costs
nothing and helps debugging.

### 🟡 MEDIUM — chart falls back to synthetic random prices
[`_synthetic_price_history()`](backend/volatility_explainer/marketdata/snapshots.py#L56)
returns a seeded random walk when yfinance fails, and the API serves it as a normal
`PriceHistory` — the frontend can't tell it apart from real data. Prefer surfacing the
failure (empty points + an "unavailable" state) over plausible-looking fake prices.

### 🟢 LOW — dependencies pinned with unbounded `>=`
`pyproject.toml` / `requirements.txt` have no upper bounds. A fresh install could pull an
untested future major of `anthropic`, `fastapi`, etc. Consider upper bounds or a lockfile
if reproducibility starts to matter.

---

## Not flagged (checked, looked clean)
- No `eval`/`exec`/`pickle.load`/`os.system`/`shell=True` anywhere.
- No TLS verification bypasses (`verify=False`).
- No SQL injection surface — the only DB write (`supabase_logger.py`) uses the Supabase
  client's parameterized `.insert()`, not raw SQL.
- No bare `except:` clauses.
- No hardcoded secrets: `.env` is gitignored and was never committed; every key loads via
  `pydantic-settings` + `SecretStr` and is never printed.
