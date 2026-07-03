# Backlog — quick security & code quality scan

Results of a quick manual scan (grep-based + targeted code reading, not a full audit).
Nothing here is fixed yet — this is a prioritized list for follow-up.

---

## Security

### 🔴 HIGH — Stored XSS via unescaped LLM output rendered with `unsafe_allow_html=True`

`apps/ui/components.py`: `_md_to_html()` (used by `render_final_output_box`) and
`render_agent_tile()` embed the LLM's `summary`, `tile.summary`, `tile.reasoning`, and
`tile.title` directly into HTML strings passed to `st.markdown(..., unsafe_allow_html=True)`
with **no escaping**.

This text is Claude-synthesized from real-world, attacker-influenceable inputs — news
headlines pulled from Finnhub/Yahoo (`mcp/tools/news.py`). A crafted headline could smuggle
an HTML/JS payload through the model and into the rendered page.

Confirmed exploitable — this passes straight through unescaped:
```python
_md_to_html("AAPL dipped because <img src=x onerror=alert(document.cookie)> of earnings.")
# → <p ...>AAPL dipped because <img src=x onerror=alert(document.cookie)> of earnings.</p>
```
(Browsers don't execute `<script>` inserted via `innerHTML`, but `onerror`/`onload` attribute
handlers on `<img>`/`<svg>` do fire — so this is a real, if not maximally severe, vector:
session/cookie theft, page defacement, disruptive rendering.)

The `citations` feature (added this session) already does this correctly —
`html.escape()` is applied to `c.url`/`c.source` before embedding. The same treatment needs
to be applied to `tile.summary`, `tile.reasoning`, `tile.title`, and the main analysis
`content` string in `render_final_output_box`.

**Fix shape:** `html.escape()` any LLM-authored text before interpolating into an HTML
string, or switch those specific fields to `st.markdown(..., unsafe_allow_html=False)` /
`st.write()` where raw HTML formatting isn't actually needed.

**Files:** `apps/ui/components.py` (`_md_to_html`, `render_agent_tile`,
`render_final_output_box`, `render_guardrail_error`)

---

## Secrets handling

### ✅ No hardcoded secrets found
- `.env` is gitignored and was never committed (`git log --all -- .env` is empty).
- All API keys load via `pydantic-settings` + `SecretStr`, and are never printed to logs
  (checked every `get_secret_value()` call site).

### 🟡 LOW — `SUPABASE_KEY` is expected to be the `service_role` key
This is safe *only* because `analytics/supabase_logger.py` runs exclusively server-side. If
this logging logic ever moves client-side (e.g. a future JS/mobile frontend), swapping in the
privileged `service_role` key there would bypass Row Level Security entirely. Worth a
callout comment near the setting, not just in chat history.

### 🟡 LOW — raw user query text is logged to Supabase unsanitized
Not a code vulnerability, but a data-handling note: free-text queries could contain PII.
Worth a retention/anonymization policy (e.g. TTL on `query_log`, or stripping the raw
`query` column) before this is used beyond a personal demo.

---

## Code quality

### 🟡 MEDIUM — 4 silent `except Exception: pass` blocks
No logging on failure, making production debugging harder ("why did FRED never return
data?" has no trail):
- `src/volatility_explainer/mcp/tools/macro.py:15`
- `src/volatility_explainer/mcp/tools/events.py:64`
- `apps/ui/placeholders.py:170`
- `apps/ui/placeholders.py:204`

Consistent with the app's deliberate multi-source-fallback design (Finnhub → yfinance,
etc.), so these shouldn't raise — but a one-line `print(f"... FAILED — {exc}")` (already the
pattern used elsewhere in the same files) costs nothing and would help debugging.

### 🟢 LOW — dependencies pinned with unbounded `>=`
`requirements.txt` / `pyproject.toml` have no upper bounds on any dependency. A fresh
install today could pull in an untested future major version of `anthropic`, `streamlit`,
etc. Consider upper-bounding or adding a lockfile if reproducibility becomes a concern.

### 🟢 LOW — no automated check that `mcp/server.py` and `orchestrator.py` stay in sync
Already found and fixed once this session (server.py was missing `get_options_positioning`).
Nothing currently prevents this drift from recurring the next time a tool is added to one
file but not the other. A cheap test asserting
`set(server tool names) == set(orchestrator._TOOL_DEFINITIONS names)` would catch it for free.

---

## Not flagged (checked, looked clean)
- No `eval`/`exec`/`pickle.load`/`os.system`/`shell=True` anywhere in the codebase.
- No TLS verification bypasses (`verify=False`).
- No SQL injection surface — the only DB write (`supabase_logger.py`) uses the Supabase
  client's parameterized `.insert()`, not raw SQL string building.
- No bare `except:` clauses.
