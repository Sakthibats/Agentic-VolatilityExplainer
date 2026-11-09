@AGENTS.md

# Claude Code notes

AGENTS.md (imported above) is the project brief and the rules. This file only adds
Claude-specific working notes.

## Orient from the brief, not by exploring

The brief is enough to start any task without walking the repo:

- **Which files?** §8 "Where to change things" maps tasks to files, and the §4 "Repo map" gives
  every file's role. Open the named files directly. Don't run repo-wide `find`/`grep`/Explore
  just to get your bearings.
- **How does X work?** Read only the matching section of `docs/ARCHITECTURE.md`: Request
  lifecycle · The `/v1` API · Caching · Frontend · Deployment · Configuration (env vars) · Usage
  log (Supabase) · Observability · Testing strategy.
- **Skip when searching:** `evals/fixtures/` (bot-committed JSON, MBs and growing),
  `frontend/node_modules/` (except the Next docs below), `frontend/out/`, `frontend/package-lock.json`.
- If the code contradicts the brief, trust the code, then fix the brief in the same change.

## Working rules

- **Before claiming done:** backend changes → `pytest -q && ruff check backend tests`;
  frontend changes → `cd frontend && npm run lint && npx tsc --noEmit` (lint blocks deploys).
- **Frontend:** `frontend/CLAUDE.md` pulls in the Next.js 16 warning: read the bundled docs in
  `frontend/node_modules/next/dist/docs/` before writing Next code.
- **Anthropic SDK / model changes:** the model ID defaults in `config.py` (`anthropic_model`).
  Check current SDK guidance before changing streaming, tool use or prompt caching.
- **Pull before branching:** the eval-capture workflow pushes a fixture commit to `main` every
  weekday, so a local `main` is usually behind `origin/main`.
- **Secrets:** `.claude/settings.json` denies reading `.env*`, `*.pem`, `*.key` and
  `credentials.json`. Don't try to work around it; `.env.example` lists every variable.
- **Keep the brief current:** if a change alters the status snapshot, an invariant, a decision,
  or the repo map in AGENTS.md, update it in the same change. Test counts come from
  `pytest -q --co | tail -1` (offline) and `pytest -m live --co | tail -1`.
