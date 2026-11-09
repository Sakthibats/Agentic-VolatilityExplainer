"""Automatic scorers: plain code, no judge model, so every number in the report is repeatable.

Each scorer reads one run record (what run.py saved) and the fixture it was replayed on.
What they can't tell you, whether the model found the TRUE catalyst, needs labelled cases and
a judge (evals/README.md, next steps).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from evals.replay import fixture_tools

_AGENTS = {"price", "news", "options", "macro", "events", "analyst", "sector"}
_CONFIDENCE = {"high", "medium", "low"}

# Numbers a reader would take as facts: percentages and dollar amounts.
_PCT = re.compile(r"(?<![\w.])([+\-\u2212]?\d+(?:\.\d+)?)\s?%")
_USD = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(trillion|billion|million|[TBMK]\b)?", re.IGNORECASE)
# A bracketed source tag that isn't a numbered headline citation: "[analyst data]", "[news]".
# Only [n] is allowed; the server turns [n] into a link and can do nothing with anything else.
_BAD_TAG = re.compile(r"\[(?!\d+\])[^\]\n]{1,40}\]")


def _numbers_in(value) -> Iterator[float]:
    """Every number anywhere in the tool data, including inside strings ("down 3.4%")."""
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, str):
        for match in re.finditer(r"\d[\d,]*(?:\.\d+)?", value):
            yield float(match.group().replace(",", ""))
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from _numbers_in(v)


def _claimed_numbers(text: str) -> list[tuple[float, int]]:
    """(value, decimals written) for each % and $ figure in the text."""
    found = []
    for match in _PCT.finditer(text):
        raw = match.group(1).replace("\u2212", "-").lstrip("+-")
        found.append((float(raw), len(raw.split(".")[1]) if "." in raw else 0))
    for match in _USD.finditer(text):
        if match.group(2):  # "$4.5 trillion": a scale word we can't check against raw data
            continue
        raw = match.group(1).replace(",", "")
        found.append((float(raw), len(raw.split(".")[1]) if "." in raw else 0))
    return found


def _grounded(value: float, decimals: int, sources: list[float]) -> bool:
    """True if some number in the data rounds to the claimed one at the precision it was
    written ("about 19%" matches 19.02; "19.1%" does not). Sign is ignored: "down 4.1%"
    states -4.1 as a positive number."""
    tolerance = 0.5 * 10 ** -decimals + 1e-9
    return any(abs(abs(s) - value) <= tolerance for s in sources)


def written_text(record: dict) -> str:
    """Everything the model wrote that a reader sees: explanation, tiles, hypotheses."""
    parts = [record.get("summary") or ""]
    for tile in record.get("tiles") or []:
        parts += [str(tile.get("summary", "")), str(tile.get("reasoning", ""))]
    for hyp in record.get("hypotheses") or []:
        parts += [str(hyp.get("hypothesis", "")), str(hyp.get("evidence", ""))]
    return "\n".join(parts)


def schema_problems(record: dict) -> list[str]:
    """Ways the final answer breaks the submit_analysis contract. Strict mode and tool
    schemas should make this empty; it is measured, not assumed."""
    problems = []
    tiles, hyps = record.get("tiles") or [], record.get("hypotheses") or []
    if len(tiles) > 4:
        problems.append("too_many_tiles")
    if any(t.get("agent") not in _AGENTS for t in tiles):
        problems.append("bad_tile_agent")
    if not 2 <= len(hyps) <= 3:
        problems.append("hypothesis_count")
    if any(h.get("confidence") not in _CONFIDENCE for h in hyps):
        problems.append("bad_confidence")
    if [h.get("rank") for h in hyps] != list(range(1, len(hyps) + 1)):
        problems.append("ranks_not_1_to_n")
    return problems


def score(record: dict, fixture: dict) -> dict:
    tools = fixture_tools(fixture)
    complete = record.get("status") == "complete"
    usage = record.get("usage") or {}
    picks = [name for rnd in usage.get("tool_rounds") or [] for name in rnd]
    today_level = ((tools["get_price_data"].get("move_assessment") or {}).get("overall"))
    notable = fixture.get("selected_as") in ("move", "top_mover")

    scores = {
        "completed": complete,
        "status": record.get("status"),
        "cost_usd": usage.get("cost_usd"),
        "llm_ms": usage.get("llm_ms"),
        "turns": usage.get("turns"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": usage.get("reasoning_tokens"),
        "n_tools": len(set(picks)),
        "called_news": "get_news" in picks,
        "notable": notable,
        "overall_level": today_level,
    }
    if not complete:
        return scores

    text = written_text(record)
    sources = list(_numbers_in(tools))
    claims = _claimed_numbers(text)
    words = len((record.get("summary") or "").split())
    scores.update({
        "schema_problems": schema_problems(record),
        "quality_flags": record.get("quality_flags") or [],
        "bad_citation_tags": len(_BAD_TAG.findall(record.get("summary") or "")),
        "numbers_claimed": len(claims),
        "numbers_grounded": sum(_grounded(v, d, sources) for v, d in claims),
        "ungrounded_examples": [v for v, d in claims if not _grounded(v, d, sources)][:5],
        "explanation_words": words,
        "length_ok": 40 <= words <= 70,
        "rank1": ((record.get("hypotheses") or [{}])[0] or {}).get("hypothesis", ""),
        "rank1_confidence": ((record.get("hypotheses") or [{}])[0] or {}).get("confidence"),
    })
    return scores


def rank1_agreement(rank1s: list[str]) -> float | None:
    """Mean pairwise word overlap (Jaccard) of the rank-1 hypothesis across repeats of one
    case: 1.0 = the same conclusion every time, near 0 = a different story each run."""
    sets = [set(re.findall(r"[a-z0-9]+", s.lower())) - {"the", "a", "of", "and", "to", "in"}
            for s in rank1s if s]
    pairs = [(a, b) for i, a in enumerate(sets) for b in sets[i + 1:] if a | b]
    if not pairs:
        return None
    return sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)


def dumps(scores: dict) -> str:
    return json.dumps(scores, default=str)
