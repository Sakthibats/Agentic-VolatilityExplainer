"""Summarise explanation quality flags across saved runs.

Run the API with VOLX_SAVE_RUNS=runs.jsonl, use the app for a while, then:

    python scripts/quality_report.py runs.jsonl
    python scripts/quality_report.py runs.jsonl --show consensus_as_cause

Flags are recomputed from each run's saved raw text and tool data with the CURRENT checks
in agent/quality.py, so the report also shows what a change to those checks would have
caught on past runs. A bad write-up worth pinning belongs in tests/agent/test_quality.py.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from volatility_explainer.agent.orchestrator import _resolve_citations
from volatility_explainer.agent.quality import check_explanation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", type=Path, help="JSONL file written via VOLX_SAVE_RUNS")
    parser.add_argument("--show", metavar="FLAG", help="print the runs that trip this flag")
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    checked = clean = 0
    for line in args.runs.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        run = json.loads(line)
        raw = run.get("raw_explanation") or run.get("summary") or ""
        if not raw:
            continue
        data = run.get("data") or {}
        text, _, removed = _resolve_citations(raw, data)
        flags = check_explanation(
            text,
            ticker=run.get("ticker") or "",
            query=run.get("query") or "",
            overview=run.get("overview") or "",
            tool_data=data,
            tiles=run.get("tiles") or [],
            removed_citations=removed,
        )
        checked += 1
        if not flags:
            clean += 1
        counts.update(flags)
        if args.show and args.show in flags:
            print(f"── {run.get('ticker')} · {run.get('query') or '(no question)'} · {run.get('saved_at')}")
            print(f"{text}\n")

    if not checked:
        print("No runs with an explanation found.")
        return
    print(f"runs checked: {checked}   clean: {clean} ({clean / checked:.0%})")
    for flag, n in counts.most_common():
        print(f"  {flag:<26} {n:>4}  {n / checked:>4.0%}")


if __name__ == "__main__":
    main()
