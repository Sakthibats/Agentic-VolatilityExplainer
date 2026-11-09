"""Summarise a results file from evals.run into one comparison table per model.

    python -m evals.report evals/results/2026-11-09.jsonl            # print markdown
    python -m evals.report evals/results/2026-11-09.jsonl --write    # also write <file>.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from evals.scorers import rank1_agreement


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def _pctl(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def summarise(records: list[dict]) -> dict[str, dict]:
    by_model: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_model[record["model"]].append(record)

    table = {}
    for model, runs in by_model.items():
        scores = [r["scores"] for r in runs]
        done = [s for s in scores if s["completed"]]
        notable = [s for s in scores if s["notable"]]
        costs = [s["cost_usd"] for s in scores if s.get("cost_usd") is not None]
        latency = [s["llm_ms"] / 1000 for s in scores if s.get("llm_ms") is not None]
        claimed = sum(s["numbers_claimed"] for s in done)
        flags = Counter(f for s in done for f in s["quality_flags"])

        rank1s: dict[str, list[str]] = defaultdict(list)
        for r in runs:
            if r["scores"]["completed"]:
                rank1s[r["case_id"]].append(r["scores"]["rank1"])
        agreement = [a for v in rank1s.values() if len(v) > 1 and (a := rank1_agreement(v)) is not None]

        table[model] = {
            "runs": len(scores),
            "cases": len({r["case_id"] for r in runs}),
            "completed": _pct(len(done), len(scores)),
            "statuses": dict(Counter(s["status"] for s in scores)),
            "schema_valid": _pct(sum(not s["schema_problems"] for s in done), len(done)),
            "quality_clean": _pct(sum(not s["quality_flags"] for s in done), len(done)),
            "top_flags": flags.most_common(3),
            "bad_citation_tags": _pct(sum(s["bad_citation_tags"] > 0 for s in done), len(done)),
            "numbers_grounded": _pct(sum(s["numbers_grounded"] for s in done), claimed),
            "numbers_per_answer": f"{claimed / len(done):.1f}" if done else "n/a",
            "length_ok": _pct(sum(s["length_ok"] for s in done), len(done)),
            "news_on_notable": _pct(sum(s["called_news"] for s in notable), len(notable)),
            "avg_tools": f"{statistics.mean(s['n_tools'] for s in scores):.1f}" if scores else "n/a",
            "avg_turns": f"{statistics.mean(s['turns'] or 0 for s in scores):.1f}" if scores else "n/a",
            "llm_s_p50": _pctl(latency, 0.5),
            "llm_s_p95": _pctl(latency, 0.95),
            "cost_per_run": statistics.mean(costs) if costs else None,
            "cost_total": sum(costs),
            "rank1_agreement": statistics.mean(agreement) if agreement else None,
        }
    return table


_ROWS = [
    ("Runs (cases)", lambda m: f"{m['runs']} ({m['cases']})"),
    ("Completed with a structured answer", lambda m: m["completed"]),
    ("Schema-valid answers", lambda m: m["schema_valid"]),
    ("Write-ups with no quality flag", lambda m: m["quality_clean"]),
    ("Most common quality flags", lambda m: ", ".join(f"{f} ({n})" for f, n in m["top_flags"]) or "n/a"),
    ("Invented citation tags (not [n])", lambda m: m["bad_citation_tags"]),
    ("% and $ figures found in the tool data", lambda m: f"{m['numbers_grounded']} ({m['numbers_per_answer']}/answer)"),
    ("Explanation within 40-70 words", lambda m: m["length_ok"]),
    ("Checked news on a notable move", lambda m: m["news_on_notable"]),
    ("Avg. tools chosen / turns", lambda m: f"{m['avg_tools']} / {m['avg_turns']}"),
    ("Model time p50 / p95", lambda m: f"{m['llm_s_p50']:.1f}s / {m['llm_s_p95']:.1f}s" if m["llm_s_p50"] is not None else "n/a"),
    ("Cost per investigation", lambda m: f"${m['cost_per_run']:.4f}" if m["cost_per_run"] is not None else "n/a"),
    ("Cost per 1,000 investigations", lambda m: f"${1000 * m['cost_per_run']:.2f}" if m["cost_per_run"] is not None else "n/a"),
    ("Same rank-1 cause across repeats", lambda m: f"{m['rank1_agreement']:.2f}" if m["rank1_agreement"] is not None else "n/a"),
]


def markdown(table: dict[str, dict], source: str) -> str:
    models = list(table)
    lines = [
        f"| Metric | {' | '.join(f'`{m}`' for m in models)} |",
        f"|---|{'---|' * len(models)}",
    ]
    for label, cell in _ROWS:
        lines.append(f"| {label} | {' | '.join(cell(table[m]) for m in models)} |")
    total = sum(m["cost_total"] for m in table.values())
    lines += ["", f"Source: `{source}` · total spend ${total:.2f}"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results")
    parser.add_argument("--write", action="store_true", help="also write <results>.md")
    args = parser.parse_args()
    path = Path(args.results)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    text = markdown(summarise(records), path.as_posix())
    print(text)
    if args.write:
        path.with_suffix(".md").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
