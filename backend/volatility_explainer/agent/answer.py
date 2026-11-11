"""From the model's answer to what the reader sees, in plain code.

Two guarantees live here, so the loop in orchestrator.py doesn't have to carry them:

- **Links never come from the model.** get_news's headlines are numbered before the model
  sees them (number_headlines); the model may only cite [n]; the server resolves each number
  to the headline's real link or removes it (resolve_citations), and gives the news tile its
  citations straight from the same headlines (attach_news_citations).
- **The answer contract holds even when the model breaks it.** submit_analysis's tiles and
  hypotheses are re-checked against the schema, and every repair is reported so the model's
  own compliance stays measurable (normalize_answer).
"""

from __future__ import annotations

import re

# submit_analysis's caps (tool_schemas.py: tiles maxItems, hypotheses maxItems). Enforced here
# as well because Claude doesn't validate a tool call it streams: Haiku 5.5 sent 5-6 tiles on
# 23% of eval runs.
_MAX_TILES = 4
_MAX_HYPOTHESES = 3

_CITATION_MARKER = re.compile(r"\s*\[(\d+)\]")


def number_headlines(name: str, result: dict) -> dict:
    """Number get_news's linked headlines 1..n as `ref`, so the model can cite one as [n]
    and the server can map that number back to the real link (see resolve_citations).

    Returns a copy — `result` may be the very object held in the in-process memo. Applied to
    cache hits too, and idempotent.
    """
    if name != "get_news" or not result.get("headlines"):
        return result
    numbered, ref = [], 0
    for original in result["headlines"]:
        headline = {k: v for k, v in original.items() if k != "ref"}
        if headline.get("url"):
            ref += 1
            headline["ref"] = ref
        numbered.append(headline)
    return {**result, "headlines": numbered}


def normalize_answer(final_input: dict) -> tuple[list[dict], list[dict], list[str]]:
    """submit_analysis's tiles and hypotheses, held to the contract in plain code.

    Malformed entries are dropped first, so they never take a slot. Then tiles and
    hypotheses are capped in the order the model wrote them, and hypotheses are ranked by
    that order: the model writes them most likely first, but Haiku 5.5 often numbers only the
    first ([1, None, None] on 38% of eval runs). Position is the rank; the field is overwritten.

    Also returns what had to be repaired, so the model's own schema compliance stays
    measurable (logged per run, scored by the eval) now that the reader never sees a break.
    """
    raw_tiles = final_input.get("tiles")
    raw_hyps = final_input.get("hypotheses")
    raw_tiles = raw_tiles if isinstance(raw_tiles, list) else []
    raw_hyps = raw_hyps if isinstance(raw_hyps, list) else []
    valid_tiles = [t for t in raw_tiles if isinstance(t, dict) and t.get("summary")]
    valid_hyps = [h for h in raw_hyps if isinstance(h, dict) and h.get("hypothesis")]
    tiles, hyps = valid_tiles[:_MAX_TILES], valid_hyps[:_MAX_HYPOTHESES]

    repairs = []
    if len(valid_tiles) < len(raw_tiles):
        repairs.append("malformed_tile_dropped")
    if len(tiles) < len(valid_tiles):
        repairs.append("too_many_tiles")
    if len(valid_hyps) < len(raw_hyps):
        repairs.append("malformed_hypothesis_dropped")
    if len(hyps) < len(valid_hyps):
        repairs.append("too_many_hypotheses")
    if [h.get("rank") for h in hyps] != list(range(1, len(hyps) + 1)):
        repairs.append("ranks_rewritten")
    return tiles, [{**h, "rank": i} for i, h in enumerate(hyps, start=1)], repairs


def attach_news_citations(tiles: list[dict], tool_data: dict) -> list[dict]:
    """Attach numbered {number, source, url} citations to the news tile, sourced directly
    from get_news's headlines — not from the LLM — so links are always real, never
    hallucinated. Up to the first 3 linked headlines, numbered by their `ref`, so a [2] in
    the explanation and [2] on the tile are the same article.
    """
    headlines = (tool_data.get("get_news") or {}).get("headlines") or []
    linked = [h for h in headlines if h.get("ref")][:3]
    citations = [
        {"number": h["ref"], "source": h.get("source") or "Source", "url": h["url"]}
        for h in linked
    ]
    if not citations:
        return tiles
    for tile in tiles:
        if isinstance(tile, dict) and tile.get("agent") == "news":
            tile["citations"] = citations
            break
    return tiles


def resolve_citations(explanation: str, tool_data: dict) -> tuple[str, list[dict], int]:
    """Turn the explanation's [n] markers into real citations.

    The model writes only a number. Each is looked up among this run's numbered get_news
    headlines (see number_headlines): a match keeps its marker and yields a citation carrying
    the headline's real link; a number that matches nothing is removed from the text rather
    than shown. Returns (text, citations in number order, count of markers removed).
    """
    refs = {
        h["ref"]: h
        for h in (tool_data.get("get_news") or {}).get("headlines") or []
        if isinstance(h, dict) and h.get("ref")
    }
    cited: dict[int, dict] = {}
    removed = 0

    def resolve(match: re.Match[str]) -> str:
        nonlocal removed
        number = int(match.group(1))
        headline = refs.get(number)
        if headline is None:
            removed += 1
            return ""
        cited[number] = {
            "number": number, "source": headline.get("source") or "Source", "url": headline["url"],
        }
        return match.group(0)

    text = _CITATION_MARKER.sub(resolve, explanation)
    return text, [cited[n] for n in sorted(cited)], removed
