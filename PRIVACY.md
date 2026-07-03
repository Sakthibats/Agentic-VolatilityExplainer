# Privacy

What this app collects, and what it doesn't — kept short and specific rather than legal
boilerplate.

## What's logged

If the app operator has configured Supabase (`SUPABASE_URL`/`SUPABASE_KEY` in `.env`),
each investigation you run is logged for usage analytics:

- **Anonymous ID** — a random ID generated when you load the page. It's **session-scoped**:
  it resets on a hard refresh or new tab. There's no login, no account, and no tracking of
  the same visitor across separate visits.
- **Ticker** and the **question you typed** (if any).
- **Whether the move looked normal or unusual** for that stock (`move_assessment`), which
  optional tools the AI chose to call, the resulting hypotheses, and any news citations
  used.
- **How long the request took** (`elapsed_ms`).

If Supabase isn't configured, none of the above is collected — logging is a no-op by
design, not a fallback that silently degrades.

## What's NOT collected

- No account, email, or login is required to use the app.
- No IP address, device fingerprint, or browser tracking beyond the session-scoped
  anonymous ID above.
- No third-party ad or analytics trackers.

## One caveat

The question you type is logged as free text. If you type something identifying in your
question, that text is stored as-is — the app doesn't scan for or redact personal
information. Avoid including anything sensitive in your query.

## Where it's stored

In the operator's own Supabase (Postgres) project, in a `query_log` table
(see [`src/volatility_explainer/analytics/supabase_logger.py`](src/volatility_explainer/analytics/supabase_logger.py)
for the exact fields written). Not shared with any third party beyond Supabase itself as
the hosting provider.

## Questions

Reach out via the Feedback link in the app footer, or open an issue on the
[GitHub repo](https://github.com/Sakthibats/Agentic-VolatilityExplainer).
