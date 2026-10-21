# Eval harness

Replays recorded market data through the real agent and scores the answers. Today only the
first stage exists; the rest is the plan (AGENTS.md, open question 1).

| Stage | State | Where |
|---|---|---|
| **Fixtures:** every tool's raw output for one ticker on one day | Recording daily | `capture.py`, `fixtures/<day>/<TICKER>.json` |
| **Cases:** a fixture plus a query and a hand-checked label (true catalyst, or none) | Not started | |
| **Runner:** serve a fixture through `_TOOL_DISPATCH`, run the real model 3× | Not started | |
| **Scorers:** completion, numbers vs. data, citations, tool choice, cost; catalyst recall and abstention via a judge model | Not started | |

## Fixtures

`.github/workflows/eval-capture.yml` runs `python -m evals.capture` each weekday at 21:30 UTC
and commits what it records. For each trading day it keeps:

- `move`: universe names whose **1-day** move the code rates elevated or unusual (catalyst
  candidates; at most 6)
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
