"""Replay eval cases through one or more models and save every run, scored.

    python -m evals.run --models anthropic:claude-haiku-5-5,openai:gpt-6-luna@low \\
        --cases 40 --repeats 3 --budget 5 --out evals/results/2026-11-09.jsonl
    python -m evals.report evals/results/2026-11-09.jsonl

A model is `<provider>:<model>[@<reasoning effort>]`; effort applies to OpenAI reasoning
models. Re-running with the same --out resumes: finished (case, model, repeat) runs are kept
and skipped. --budget is a hard stop on total spend across the file, checked before each
run starts (runs already in flight can overshoot it by a few cents).

The loop's own per-turn logging goes to <out>.log; progress goes to the terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from pathlib import Path

from volatility_explainer.config import get_settings
from volatility_explainer.llm import PROVIDERS, build_provider

from evals.cases import Case, build_cases
from evals.replay import replay
from evals.scorers import score


def parse_model(spec: str):
    provider, _, rest = spec.partition(":")
    model, _, effort = rest.partition("@")
    if provider not in PROVIDERS or not model:
        raise SystemExit(f"bad --models entry {spec!r}; expected provider:model[@effort]")
    key = getattr(get_settings(), f"{provider}_api_key").get_secret_value()
    if not key:
        raise SystemExit(f"{provider.upper()}_API_KEY is not set; needed for {spec}")
    return build_provider(provider, model, key, reasoning_effort=effort or None)


def load_done(out: Path) -> tuple[set[tuple[str, str, int]], float]:
    done, spent = set(), 0.0
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            done.add((record["case_id"], record["model"], record["repeat"]))
            spent += (record.get("usage") or {}).get("cost_usd") or 0.0
    return done, spent


def to_record(case: Case, label: str, repeat: int, result: dict) -> dict:
    record = {
        "case_id": case.id, "day": case.day, "ticker": case.ticker, "bucket": case.bucket,
        "query": case.query, "model": label, "repeat": repeat,
        "status": result.get("status"), "error": result.get("error_message"),
        "overview": result.get("overview"), "summary": result.get("summary"),
        "tiles": result.get("tiles"), "hypotheses": result.get("hypotheses"),
        "citations": result.get("citations"), "quality_flags": result.get("quality_flags"),
        "answer_repairs": result.get("answer_repairs"),
        "usage": result.get("usage"), "wall_ms": result.get("wall_ms"),
    }
    record["scores"] = score(record, case.fixture())
    return record


async def main_async(args) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    labels = [m.strip() for m in args.models.split(",") if m.strip()]
    providers = {label: parse_model(label) for label in labels}
    cases = build_cases(args.cases, seed=args.seed)
    done, spent = load_done(out)

    jobs = [
        (case, label, repeat)
        for repeat in range(args.repeats)   # repeat-major: a budget stop leaves every
        for case in cases                   # model with the same cases covered
        for label in labels
        if (case.id, label, repeat) not in done
    ]
    print(f"{len(cases)} cases x {len(labels)} models x {args.repeats} repeats: "
          f"{len(jobs)} to run, {len(done)} already done, ${spent:.4f} spent of ${args.budget}",
          file=sys.stderr)

    semaphore = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    state = {"spent": spent, "finished": 0, "stopped": False}
    t0 = time.perf_counter()

    async def run_one(case: Case, label: str, repeat: int) -> None:
        async with semaphore:
            if state["spent"] >= args.budget:
                state["stopped"] = True
                return
            result = await replay(case.fixture(), case.query, providers[label])
            record = to_record(case, label, repeat, result)
            async with lock:
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
                cost = (record.get("usage") or {}).get("cost_usd")
                state["spent"] += cost or 0.0
                state["finished"] += 1
                print(f"[{state['finished']}/{len(jobs)}] {label:<34} {case.id:<18} "
                      f"{record['status']:<10} ${cost or 0:.5f}  total ${state['spent']:.4f}  "
                      f"({time.perf_counter() - t0:.0f}s)", file=sys.stderr)

    log_path = out.with_suffix(".log")
    with log_path.open("a", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        await asyncio.gather(*(run_one(*job) for job in jobs))

    if state["stopped"]:
        print(f"Stopped at the ${args.budget} budget; re-run with a higher --budget to resume.",
              file=sys.stderr)
    print(f"Done: {state['finished']} runs, ${state['spent']:.4f} total → {out}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", required=True, help="comma-separated provider:model[@effort]")
    parser.add_argument("--cases", type=int, default=40)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--budget", type=float, default=5.0, help="hard stop, in USD, across --out")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", required=True)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
