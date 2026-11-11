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
- **What's left to do?** `docs/ROADMAP.md`: Phase 4, candidates, and the known-debt tables.
- **Skip when searching:** `evals/fixtures/` (bot-committed JSON, MBs and growing),
  `frontend/node_modules/` (except the Next docs below), `frontend/out/`, `frontend/package-lock.json`.
- If the code contradicts the brief, trust the code, then fix the brief in the same change.

## Current focus (as of 2026-11-11; update or delete as steps land)

Goal: the README shows whether the agent finds the *true* cause (AGENTS §7 open question 1).
Remaining steps, in order:

1. Labelling kit: `python -m evals.label` shows a case's move and headlines and records the
   catalyst, "cause not in the data", "no catalyst" or "unclear" to a committed labels file.
   About 150 usable fixtures already exist once `cases.bucket_holds` drops the stale ones.
2. The user labels about 40 cases.
3. Judge scorer (catalyst rank-1 / top-3, abstention on controls, calibration; each vendor
   judges the other's answers, agreement reported), a full eval run, a new README table.
4. A logging config plus one structured per-run line with tokens and cost.
5. Eval fixtures moved off `main` to an orphan branch (no new credentials).

## Working rules

- **Before claiming done:** backend or eval changes → `pytest -q && ruff check backend tests
  evals scripts` (run inside `.venv`: `source .venv/bin/activate`); frontend changes →
  `cd frontend && npm run lint && npx tsc --noEmit` (lint blocks deploys).
- **Agent loop, prompt or provider changes:** also replay a few real cases. This spends real
  API credit (about $0.01), so say so in the summary:
  `python -m evals.run --models anthropic:claude-haiku-5-5,openai:gpt-6-luna@low --cases 3
  --repeats 1 --budget 0.05 --out <scratchpad>/smoke.jsonl`. Model output varies run to run,
  so this checks the loop end to end (completed, citations resolved, repairs recorded), not
  identical output.
- **Moving code that tests patch:** tests patch module attributes (`orchestrator._STREAMED_FIELD`,
  `orchestrator._partial_json_string`, `_TOOL_DISPATCH`, …). If code that reads one of these
  moves to another module, the patch silently stops applying while tests stay green. Check
  `git grep -n "orchestrator\.\w*" tests evals` before moving anything.
- **Logging:** the backend has no logging config, so `logger.info(...)` output is dropped and
  only `print` reaches Cloud Run. Add a config before converting any `print` (the `[quality]`
  and `[answer]` lines are the only production quality signal).
- **Frontend:** `frontend/CLAUDE.md` pulls in the Next.js 16 warning: read the bundled docs in
  `frontend/node_modules/next/dist/docs/` before writing Next code.
- **Anthropic SDK / model changes:** the model ID defaults in `config.py` (`anthropic_model`).
  Check current SDK guidance before changing streaming, tool use or prompt caching.
- **Secrets:** `.claude/settings.json` denies reading `.env` and `.env.local`. Don't try to work
  around it. Its `grep * .env` rule also blocks `grep … .env.example`, so read `.env.example`
  with the Read tool, or use `config.py`, which lists every setting.
- **Keep the brief current:** if a change alters the status snapshot, an invariant, a decision,
  or the repo map in AGENTS.md, update it in the same change. Test counts come from
  `pytest -q --co | tail -1` (offline) and `pytest -m live --co | tail -1`.
- **No hardcoded counts in README.md** (tests, live tests, decisions, quality flags). They drift
  within days. AGENTS.md §3 holds the only test count.

## Git and pull requests

- **Pull before branching:** the eval-capture workflow pushes a fixture commit to `main` every
  weekday, so a local `main` is usually behind `origin/main`.
- **One branch and one PR per change; the user merges.** Make it a single commit, because
  GitHub pre-fills the PR description from it, so write the commit message as the PR body.
- **`gh` is not installed.** After pushing, give the user
  `https://github.com/Sakthibats/Agentic-VolatilityExplainer/pull/new/<branch>`.
- **Say what merging deploys:** backend/tests/Dockerfile/pyproject paths → Cloud Run;
  `frontend/` → Cloudflare Pages; docs only → nothing. The frontend may land first, so it must
  tolerate the previous backend's response.
- **Two open branches:** check they merge cleanly with
  `git merge-tree --write-tree origin/<a> origin/<b>`.
- `git add` fails as a whole if it names a path already removed with `git rm`. Don't list
  deleted paths.

## Shell

- zsh: an unquoted glob such as `grep --include=*.py` fails with "no matches found", and grep
  never runs. Use `git grep -n <pattern> -- ':!evals/fixtures'` instead.
