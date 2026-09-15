"""Deterministic checks on the model's explanation — the "why" paragraph.

tool_schemas.py and prompts.py tell the model how to write it; this module checks what it
actually wrote, in plain code, against the same run's data. The flags are a measurement:
they are logged and returned with the run, never used to rewrite the text. The regression
cases in tests/agent/test_quality.py, and scripts/quality_report.py over runs saved with
VOLX_SAVE_RUNS, are the start of an eval set for the write-up.

Every check is a cheap heuristic tuned for precision — a flag should almost always be a
real problem, at the cost of missing some. Each docstring says what it looks for.
"""

from __future__ import annotations

import re

from volatility_explainer.tools.price import _SEVERITY, _horizon_levels

TOO_LONG = "too_long"
REPEATS_OVERVIEW = "repeats_overview_numbers"
OVERSTATES_SIZE = "overstates_move_size"
CONSENSUS_AS_CAUSE = "consensus_as_cause"
UNMEASURED_CLAIM = "unmeasured_claim"
UNCITED_CATALYST = "uncited_catalyst"
INVALID_CITATION = "invalid_citation"

# The schema asks for 40-70 words; flag only once it is clearly past that.
MAX_WORDS = 80
# One matching figure can be coincidence (a sector also up 4%); two is restating the overview.
_MAX_REPEATED_FIGURES = 1

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_FIGURE = re.compile(r"(\$)?(\d[\d,]*(?:\.\d+)?)(%)?")
_CITATION_MARKER = re.compile(r"\[\d+\]")

_STRONG_SIZE = re.compile(
    r"\b(unusual(?:ly)?|extraordinar(?:y|ily)|exceptional(?:ly)?|massive|huge"
    r"|dramatic(?:ally)?|outsized|extreme(?:ly)?)\b",
    re.IGNORECASE,
)
_NEGATIONS = {"no", "not", "nothing", "without", "isn't", "wasn't"}
# Nouns that "unusual" can describe without saying anything about the move's size.
_NOT_ABOUT_SIZE = {
    "driver", "drivers", "catalyst", "catalysts", "news", "activity", "volume", "options", "trading",
}

_CONSENSUS = re.compile(
    r"\b(consensus|price targets?|upside|buy ratings?|buy or strong buy|\d+% (?:strong )?buy)\b",
    re.IGNORECASE,
)
_DATED_ACTION = re.compile(
    r"\b(upgrad\w*|downgrad\w*|initiat\w*|raised|cut|lowered|lifted)\b", re.IGNORECASE
)
_VALUATION_QUESTION = re.compile(
    r"\b(overvalued|undervalued|valuation|analysts?|price target|rating|worth|should i|buy|sell"
    r"|street)\b",
    re.IGNORECASE,
)

_UNMEASURED = re.compile(
    r"\b(momentum|institutional|conviction|speculat\w*|profit[- ]taking|fomo|risk appetite"
    r"|smart money|(?:investor|market) (?:sentiment|enthusiasm))\b",
    re.IGNORECASE,
)

_CAUSAL = re.compile(
    r"\b(driven by|due to|because of|triggered by|sparked by|fuell?ed by|in response to"
    r"|on the back of|thanks to)\b",
    re.IGNORECASE,
)


def check_explanation(
    explanation: str,
    *,
    ticker: str,
    query: str,
    overview: str,
    tool_data: dict,
    tiles: list,
    removed_citations: int = 0,
) -> list[str]:
    """Return the flags this explanation trips, in a stable order — [] when clean.

    `explanation` is the text after citation resolution; `removed_citations` is how many
    [n] markers that step had to drop because they matched no headline.
    """
    if not explanation.strip():
        return []
    sentences = _SENTENCE_END.split(explanation.strip())
    price_data = tool_data.get("get_price_data") or {}
    checks = [
        (TOO_LONG, len(explanation.split()) > MAX_WORDS),
        (REPEATS_OVERVIEW, _repeats_overview(explanation, overview)),
        (OVERSTATES_SIZE, _overstates_size(sentences, ticker, price_data)),
        (CONSENSUS_AS_CAUSE, _consensus_as_cause(sentences, query)),
        (UNMEASURED_CLAIM, bool(_UNMEASURED.search(explanation))),
        (UNCITED_CATALYST, _uncited_catalyst(explanation, tool_data, tiles)),
        (INVALID_CITATION, removed_citations > 0),
    ]
    return [flag for flag, tripped in checks if tripped]


def _figures(text: str) -> list[tuple[str, float, int]]:
    """Dollar amounts and percentages as (kind, value, decimals). Bare numbers — dates,
    counts, [n] citation markers — are ignored."""
    found = []
    for dollar, number, percent in _FIGURE.findall(text):
        if not (dollar or percent):
            continue
        decimals = len(number.split(".")[1]) if "." in number else 0
        found.append(("$" if dollar else "%", float(number.replace(",", "")), decimals))
    return found


def _repeats_overview(explanation: str, overview: str) -> bool:
    """The explanation restates figures the reader has just seen in the overview. Matching
    allows for rounding to the explanation's precision ("4%" repeats "4.0%", "65%" repeats
    "65.3%", "$230" repeats "$230.05")."""
    shown = _figures(overview)
    repeated = {
        (kind, value)
        for kind, value, decimals in _figures(explanation)
        if any(k == kind and round(v, decimals) == value for k, v, _ in shown)
    }
    return len(repeated) > _MAX_REPEATED_FIGURES


def _relative_frame(ticker: str) -> re.Pattern[str]:
    """Wording that judges size against this stock's own history ("for DDOG", "DDOG's
    typical volatility") rather than in plain terms."""
    alternatives = [
        r"\bfor (?:this stock|it)\b",
        r"\bits (?:own|typical|normal|usual)\b",
        r"\bvolatil\w*",
        r"\b(?:normal|usual) range\b",
    ]
    if ticker:
        name = re.escape(ticker)
        alternatives += [
            rf"\bfor {name}\b",
            rf"\b{name}" + r"['\N{RIGHT SINGLE QUOTATION MARK}]s\b",  # straight or curly apostrophe
        ]
    return re.compile("|".join(alternatives), re.IGNORECASE)


def _is_size_claim(sentence: str, match: re.Match[str]) -> bool:
    before = [w.strip(",;:") for w in sentence[: match.start()].lower().split()[-2:]]
    after = [w.strip(",.;:") for w in sentence[match.end() :].lower().split()[:1]]
    if any(word in _NEGATIONS for word in before):
        return False  # "no unusual driver"
    return not (after and after[0] in _NOT_ABOUT_SIZE)  # "unusual options activity"


def _overstates_size(sentences: list[str], ticker: str, price_data: dict) -> bool:
    """A size word stronger than the code's verdict. A sentence that frames size against
    the stock itself ("unusual relative to DDOG's typical volatility") is held to the most
    severe *relative* level across horizons; any other strong size word is held to the
    overall level. Negated and non-size uses are ignored."""
    levels = _horizon_levels(
        price_data.get("changes_pct") or {}, price_data.get("realized_vol_annualized_pct")
    )
    if not levels:
        return False  # no verdict to compare against
    worst_relative = max((v[1] for v in levels.values()), key=_SEVERITY.get)
    worst_overall = max((v[0] for v in levels.values()), key=_SEVERITY.get)
    relative_frame = _relative_frame(ticker)

    for sentence in sentences:
        for match in _STRONG_SIZE.finditer(sentence):
            if not _is_size_claim(sentence, match):
                continue
            ceiling = worst_relative if relative_frame.search(sentence) else worst_overall
            if ceiling != "unusual":
                return True
    return False


def _consensus_as_cause(sentences: list[str], query: str) -> bool:
    """Standing analyst consensus, the ratings mix or price-target upside offered in a
    write-up about a move. Skipped when the user asked about valuation or analysts — then
    it IS the answer — and a sentence naming a dated rating change is allowed."""
    if _VALUATION_QUESTION.search(query or ""):
        return False
    return any(_CONSENSUS.search(s) and not _DATED_ACTION.search(s) for s in sentences)


def _uncited_catalyst(explanation: str, tool_data: dict, tiles: list) -> bool:
    """A causal claim with no [n] citation, in a run where there were numbered headlines to
    cite and the model itself put a news tile in front of the reader — the news informed the
    answer, so the cause it names should link to the headline it came from."""
    headlines = (tool_data.get("get_news") or {}).get("headlines") or []
    has_refs = any(isinstance(h, dict) and h.get("ref") for h in headlines)
    has_news_tile = any(isinstance(t, dict) and t.get("agent") == "news" for t in tiles)
    return (
        has_refs
        and has_news_tile
        and bool(_CAUSAL.search(explanation))
        and not _CITATION_MARKER.search(explanation)
    )
