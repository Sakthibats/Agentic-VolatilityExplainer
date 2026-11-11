# Eval harness

Replays recorded market data through the real agent loop, on any model behind the provider
seam (`backend/volatility_explainer/llm/`), and scores every answer in plain code. The same
cases, the same data and the same scorers for every model, so the comparison is like for like.

| Stage | State | Where |
|---|---|---|
| **Fixtures:** every tool's raw output for one ticker on one day | Recording daily | `capture.py`, `fixtures/<day>/<TICKER>.json` |
| **Cases:** a fixture plus the question a user asks about it | Built | `cases.py` |
| **Runner:** the real loop over fixture data, N models × R repeats, spend cap, resume | Built | `replay.py`, `run.py` |
| **Automatic scorers** (no judge model) | Built | `scorers.py`, `report.py` |
| **Labels + judge:** the true catalyst per case, scored for recall and abstention | Next step | |

## Run it

```bash
python -m evals.run --models anthropic:claude-haiku-5-5,openai:gpt-6-luna@low \
    --cases 40 --repeats 3 --budget 5 --out evals/results/<date>.jsonl
python -m evals.report evals/results/<date>.jsonl --write    # → <date>.md
```

A model is `<provider>:<model>[@<reasoning effort>]`; effort applies to OpenAI reasoning
models. Keys come from `.env` like the app's. Re-running with the same `--out` resumes, and
`--budget` (USD) is a hard stop across the whole file. Start with `--cases 5 --repeats 1` to
measure cost per run before a full run.

## How a case is replayed

- **Cases** are sampled from the fixtures across the three capture buckets (40% `move`, 35%
  `top_mover`, 25% `control`), deterministic for a seed. Queries alternate between naming only
  the stock (which reaches the loop as an empty question, as in production) and asking about the
  move ("why is TEAM down today?").
- **Stale buckets are left out.** Capture picks `move` and `control` from the lagging daily
  history (see "One correction" below), so `cases.bucket_holds` re-checks each against the
  corrected 1-day move: a `move` that was calm today, or a `control` that moved, is not sampled.
  On the first three weeks of fixtures that dropped 35 of 76 moves and 8 of 30 controls. Results
  recorded before 2026-11-11 (`results/2026-11-09`, `2026-11-10`) used the unfiltered buckets, so
  their "news on a notable move" row counts some calm days as notable.
- **Replay** runs `orchestrator.run_explainer` unchanged: the same prefetch, tool schemas, turn
  limit, citation handling and quality checks as production. Every tool in `_TOOL_DISPATCH`
  reads the active fixture instead of the network, and the tool caches are off. The fixture
  sits in a context variable, so concurrent replays never see each other's data. A provider
  error is recorded as `status: "error"`, not raised.
- **One correction to the data.** Fixtures are captured at 16:30 ET, before yfinance's daily
  history includes that day's bar. Until `tools/price.py` was fixed (2026-11) that meant the recorded "1-day" change and the significance verdict
  built on it describe the previous day, while `change_pct` comes from the live quote (they
  disagreed by more than half a point on 136 of the first 168 fixtures). `replay.normalize_price`
  takes "today" from the quote and recomputes the verdict, so no model is scored on
  contradictory inputs. Since the fix, `get_price_data` joins the live quote as today's close,
  so newer fixtures already agree and `normalize_price` leaves them unchanged.

## What the scorers measure

| Metric | How | Why it matters |
|---|---|---|
| Completed | the run ended with `submit_analysis` | prose or a turn-limit exit ships no answer |
| Schema-valid (after repairs) | ≤4 tiles, known tile agents, 2–3 hypotheses ranked 1..n, valid confidence, on the answer the reader got | the UI renders exactly this shape |
| Schema-valid as the model wrote it | no entry in the run's `answer_repairs`: what `orchestrator._normalize_answer` had to fix (dropped or extra entries, rewritten ranks) | the code hides schema breaks from the reader, so this is the model's own compliance (`n/a` for results recorded before 2026-11-11) |
| No quality flag | `agent/quality.py`, the production heuristics | the known write-up failures |
| Invented citation tags | a bracketed tag that isn't `[n]` | only `[n]` can become a real link |
| Figures found in the data | every `%` and `$` figure in the write-up, tiles and hypotheses must match a number in the tool data at the precision written | a cheap lower bound on made-up numbers |
| Explanation length | 40–70 words, as the schema asks | instruction following |
| News on a notable move | did it look for a catalyst when the move was notable | investigation depth |
| Tools, turns, latency, cost | from each run's `usage` | the price of the answer |
| Same rank-1 cause across repeats | word overlap of the top hypothesis between repeats | stability |

**Limits.** The figure check accepts a match anywhere in the tool data, so it catches invented
numbers but not a real number attached to the wrong fact. Nothing here knows the *true* cause
of a move: a fluent, well-grounded answer can still name the wrong catalyst.

## Next steps (not built)

1. **Labels.** For each `move` and `top_mover` case, the catalyst a human verified from the
   fixture's headlines (or "none found"); controls are labelled "no catalyst".
2. **Judge scorers.** Catalyst recall (is the labelled cause the rank-1 hypothesis, or in the
   top 3?), abstention on controls (low confidence or "no clear cause"), and calibration (how
   often a "high" confidence answer is right). Each vendor's model judges the other's answers,
   with judge agreement reported and disagreements checked by hand.
3. **Prompt variants** as extra arms, e.g. a prompt tuned for each vendor, since today's prompt
   was written against Claude.

## Fixtures

`.github/workflows/eval-capture.yml` runs `python -m evals.capture` each weekday at 21:30 UTC
and commits what it records. For each trading day it keeps:

- `move`: universe names whose **1-day** move the code rates elevated or unusual (catalyst
  candidates; at most 6). Before the 2026-11 price fix this used the previous day's move;
  `cases.bucket_holds` leaves those stale picks out.
- `control`: 2 universe names calm on every horizon (for testing abstention)
- `top_mover`: the 3 largest large-cap gainers and 3 losers from the Yahoo screener

Each fixture holds **all 8 data tools**, not only the ones the model picked that day, so a
replay under a different prompt or model never runs into missing data. A tool that failed is
recorded as `{"error": ...}`, the way the model would have seen it.

```bash
python -m evals.capture --dry-run           # show today's selection
python -m evals.capture --tickers NVDA,MU   # record specific tickers (also: workflow_dispatch)
```

Capture runs only after the close and paces itself under Finnhub's free-tier limit; over it,
tools fall back to yfinance and the fixture stops matching what production would have seen.
`keys_configured` records which keys were set; a tool that reports its actual source (for
example `get_macro`) says so in its own output.
