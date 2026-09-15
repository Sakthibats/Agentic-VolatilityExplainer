@AGENTS.md

# Claude Code notes

AGENTS.md (imported above) is the project brief and the rules. This file only adds
Claude-specific working notes.

- **Before claiming done:** backend changes → `pytest -q && ruff check backend tests`;
  frontend changes → `cd frontend && npm run lint && npx tsc --noEmit` (lint blocks deploys).
- **Frontend:** `frontend/CLAUDE.md` pulls in the Next.js 16 warning — read the bundled docs in
  `frontend/node_modules/next/dist/docs/` before writing Next code.
- **Anthropic SDK / model changes:** the model ID defaults in `config.py` (`anthropic_model`).
  Check current SDK guidance before changing streaming, tool use or prompt caching.
- **Keep the brief current:** if a change alters the status snapshot, an invariant, or a decision
  in AGENTS.md, update it in the same change.
