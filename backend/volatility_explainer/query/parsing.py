"""Query parsing, ticker resolution, and the financial-scope guardrail.

Rescued from the retired Streamlit app (apps/ui/placeholders.py) — this is
backend business logic: the API resolves tickers and enforces scope so no
frontend ever re-implements it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryDecision:
    """Outcome of the scope gate for one submitted query.

    When in_scope is False, ticker is always None and message holds the
    guardrail text — nothing downstream (ticker resolution, charts, agents)
    should run for that query.
    """
    in_scope: bool
    ticker: str | None
    question: str
    source: str | None
    message: str = ""


# ---------------------------------------------------------------------------
# Input parsing — handles tickers, company names, natural language, concepts
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    "why", "did", "does", "is", "are", "was", "were", "the", "a", "an",
    "how", "what", "when", "where", "who", "which", "that", "this", "these",
    "those", "can", "could", "has", "have", "had", "will", "would", "should",
    "dip", "drop", "fall", "fell", "rise", "rose", "up", "down", "spike",
    "crash", "surge", "move", "moved", "going", "go", "gone", "happened",
    "happening", "happen", "stock", "share", "price", "market", "ticker",
    "company", "so", "it", "do", "of", "in", "on", "at", "to", "for", "by",
    "with", "my", "me", "you", "we", "he", "she", "they", "his", "her",
    "their", "and", "or", "but", "not", "no", "yes", "iv", "vol", "be",
    "been", "today", "yesterday", "week", "month", "year", "recently",
    "just", "now", "huge", "big", "bad", "good", "much", "lot", "any",
    "all", "some", "get", "got", "buy", "sell", "hold", "long", "short",
    "put", "call", "explain", "tell", "show", "showing", "trading", "trade",
    "perform", "performing", "doing", "look", "looking", "think", "about",
    "around", "over", "under", "since", "after", "before", "during",
    "between", "into", "through", "across", "against", "because", "from",
    "there", "here", "then", "than", "like", "if", "too",
    "please", "help", "know", "feel", "way", "time",
    "day", "last", "next", "recent", "past", "future", "current", "latest",
})

# Financial concepts mapped to yfinance-friendly fund name search queries.
# We use specific fund names (not tickers) so yfinance resolves the most
# liquid representative ETF — no hardcoded ticker mappings here.
_CONCEPT_HINTS: list[tuple[str, str]] = [
    (r"\bgold\b",                                "iShares gold trust"),
    (r"\bsilver\b",                              "iShares silver trust"),
    (r"\bcopper\b",                              "United States copper"),
    (r"\boil\b|\bcrude\b|\bpetroleum\b",         "United States Oil Fund"),
    (r"\bnatural\s+gas\b",                       "United States natural gas"),
    (r"\bbitcoin\b|\bbtc\b|\bcrypto\b",          "iShares bitcoin trust"),
    (r"\bethereum\b|\beth\b",                    "iShares ethereum trust"),
    (r"\bs[&\s]?p\s*500\b|\bsp500\b|\bsnp\b",   "SPDR S&P 500"),
    (r"\bnasdaq\b|\bqq\b",                       "Invesco QQQ trust"),
    (r"\bdow\s+jones\b|\bdjia\b|\bdow\b",        "SPDR dow jones"),
    (r"\btotal\s+market\b|\bstock\s+market\b|\bmarkets?\b", "Vanguard total stock"),
    (r"\brussell\b|\bsmall[\s-]?cap\b",          "iShares russell 2000"),
    (r"\bbond\b|\btreasury\b|\bfixed\s+income\b","iShares 20 year treasury"),
    (r"\bemerging\s+market\b|\bem\s+market\b",   "iShares MSCI emerging markets"),
    (r"\breal\s+estate\b|\breit\b",              "Vanguard real estate"),
    (r"\benergy\s+sector\b|\benergy\s+stock\b",  "XLE energy"),
    (r"\btech\s+sector\b|\btechnology\s+sector\b","XLK technology"),
    (r"\bfinancial\s+sector\b|\bbank\s+sector\b","XLF financial"),
    (r"\bhealthcare\s+sector\b|\bpharma\s+sector\b","XLV healthcare"),
]

_FINANCIAL_KEYWORDS: frozenset[str] = frozenset({
    "stock", "stocks", "share", "shares", "equity", "equities",
    "price", "prices", "etf", "fund", "index", "indices",
    "crypto", "bitcoin", "ethereum", "coin", "token",
    "gold", "oil", "silver", "copper", "commodity", "commodities",
    "earnings", "revenue", "profit", "loss", "dividend", "buyback",
    "analyst", "rating", "upgrade", "downgrade", "target", "forecast",
    "ipo", "spac", "merger", "acquisition", "deal", "spinoff",
    "fed", "fomc", "rate", "inflation", "cpi", "gdp", "recession",
    "vix", "volatility", "options", "calls", "puts",
    "nasdaq", "nyse", "dow", "russell",
    "bond", "bonds", "treasury", "yield", "sector",
    "bull", "bear", "rally", "correction", "crash", "dip", "surge",
    "invest", "investing", "portfolio", "position", "hedge",
    "quarter", "guidance", "outlook", "report", "market", "ticker",
    "short", "squeeze", "momentum", "breakout",
})

# Price/movement intent words — used to detect financial inquiry even when
# explicit financial nouns are absent (e.g. "why did apple dip?")
_FINANCIAL_INTENT_WORDS: frozenset[str] = frozenset({
    "dip", "drop", "fall", "fell", "rise", "rose", "spike", "crash",
    "surge", "jump", "tumble", "rally", "plunge", "soar", "tank",
    "gain", "decline", "climb", "slide", "bounce", "pump", "dump",
    "happened", "happen", "moved", "move", "performing", "explain",
    "investigate", "analyze", "volatile", "lower", "higher", "up", "down",
})

_OUT_OF_SCOPE_MESSAGE = (
    "This tool investigates **stock and ETF price movements** only. "
    "Ask about a company (*why did Apple dip?*), a ticker (*TSLA*), "
    "or a market/asset (*what happened to gold?*, *why is the market down?*)."
)

_ticker_cache: dict[str, str | None] = {}
_llm_ticker_cache: dict[str, str | None] = {}


def _resolve_ticker_llm(query: str) -> str | None:
    """Call Claude Haiku to map a free-form query to the most relevant US ticker.
    Result is cached per unique query string. Returns None for anything that isn't
    clearly a financial/company/sector reference — this is a last-resort fallback,
    so it must be conservative rather than guessing a plausible-looking ticker.
    """
    key = query.strip().lower()
    if key in _llm_ticker_cache:
        return _llm_ticker_cache[key]
    result = None
    try:
        import json as _json

        import anthropic

        from volatility_explainer.config import get_settings

        api_key = get_settings().anthropic_api_key.get_secret_value() or None
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{"role": "user", "content": (
                f'Does this text clearly refer to a specific US-listed stock, company, sector, '
                f'or asset (not a generic word, unrelated topic, or full sentence about something '
                f'else)? Text: "{query}"\n'
                'Reply ONLY with JSON: {"ticker": "SYMBOL"} if clearly yes, or {"ticker": null} '
                'if there is any doubt, ambiguity, or the text isn\'t about a financial instrument.\n'
                'Company name → primary US ticker. Sector/theme → most liquid ETF.\n'
                'Examples: "sandisk"→SNDK, "apple"→AAPL, "chip sector"→SOXX, '
                '"gold"→GLD, "market"→SPY, "nasdaq"→QQQ, "crypto"→IBIT, '
                '"bake a cake"→null, "how do I learn python"→null, "weather today"→null'
            )}],
        )
        data = _json.loads(msg.content[0].text.strip())
        t = str(data.get("ticker") or "").strip().upper()
        if re.match(r"^[A-Z]{1,5}$", t):
            result = t
    except Exception:
        pass
    _llm_ticker_cache[key] = result
    return result


def _resolve_ticker(term: str, search_query: str | None = None, *, require_name_match: bool = False) -> str | None:
    """Resolve a word/phrase to a valid US equity ticker via yfinance search.
    If search_query is given it overrides the search text (but term is still the cache key).

    require_name_match: when True (used for loose company-name guesses from arbitrary
    words), only accept a hit whose company name actually starts with the search term —
    this rejects accidental substring matches like "cake" -> "Cheesecake Factory" (CAKE),
    which would otherwise let an unrelated sentence slip past the topic guardrail.
    """
    cache_key = f"{(search_query or term).upper()}|{require_name_match}"
    if cache_key in _ticker_cache:
        return _ticker_cache[cache_key]
    result = None
    try:
        import yfinance as yf
        query = search_query or term
        hits = yf.Search(query, max_results=10).quotes
        for h in hits:
            sym = h.get("symbol", "")
            # Accept only clean 1-5 letter tickers (no dots, hyphens — those are usually foreign or preferred)
            if not re.match(r"^[A-Z]{1,5}$", sym):
                continue
            if require_name_match:
                name = (h.get("shortname") or h.get("longname") or "").strip().lower()
                if not name.startswith(query.strip().lower()):
                    continue
            result = sym
            break
    except Exception:
        pass
    _ticker_cache[cache_key] = result
    return result


def validate_financial_query(raw: str, ticker: str | None, source: str | None = None) -> tuple[bool, str]:
    """Return (is_valid, error_message).

    A ticker resolved from an explicit symbol or a recognized concept phrase (gold,
    market, nasdaq, ...) is strong, unambiguous evidence of financial intent — pass
    immediately. A ticker resolved from a loose company-name guess or the LLM fallback
    is weaker (those paths can mis-fire on an ordinary word, e.g. "cake" -> CAKE).

    For those weaker sources, a short query (≤4 words) is treated as a direct
    ticker/company-name lookup — the dominant use of this search bar — and trusted.
    A longer, sentence-like query instead falls through to the keyword/intent check
    below, so an unrelated sentence can't slip past the guardrail just because one of
    its words happens to match some ticker's company name (e.g. "I want to bake a
    cake today" matching CAKE).
    """
    if ticker and source in ("concept", "ticker_symbol"):
        return True, ""
    if ticker and source in ("company_name", "llm") and len(raw.split()) <= 4:
        return True, ""

    text_lower = raw.lower()
    words = set(re.findall(r"\b\w+\b", text_lower))

    # Concept phrases (gold, market, nasdaq, s&p 500, …)
    for pattern, _ in _CONCEPT_HINTS:
        if re.search(pattern, text_lower):
            return True, ""

    # Financial noun or intent keyword present
    if words & (_FINANCIAL_KEYWORDS | _FINANCIAL_INTENT_WORDS):
        return True, ""

    return False, _OUT_OF_SCOPE_MESSAGE


def parse_search_input(raw: str) -> tuple[str | None, str, str | None]:
    """Extract a ticker from free-form input.

    Priority order:
    1. Concept phrases (gold → GLD/IAU, market → VTI, S&P 500 → VOO) — source "concept"
    2. Uppercase tokens that look like tickers (TSLA, AAPL) — source "ticker_symbol"
    3. Other words tried as company name searches (tesla → TSLA) — source "company_name"
    4. Full-query LLM fallback — source "llm"

    Returns (ticker, query_text, source). Sources "concept" and "ticker_symbol" are
    unambiguous evidence of financial intent; "company_name" and "llm" are weaker
    guesses that the guardrail should still sanity-check against query keywords
    (see validate_financial_query) since a loose word match can mis-fire (e.g. the
    word "cake" resolving to the ticker CAKE).
    """
    text = raw.strip()
    if not text:
        return None, "", None

    text_lower = text.lower()

    # 1. Concept phrases first — catches "gold price", "market", "s&p 500", etc.
    for pattern, search_query in _CONCEPT_HINTS:
        if re.search(pattern, text_lower):
            ticker = _resolve_ticker(search_query, search_query)
            if ticker:
                return ticker, text, "concept"

    # {1,6} was a bug — company names like "sandisk" (7 chars) were silently dropped
    tokens = re.findall(r"\b[a-zA-Z]{1,20}\b", text)

    # 2. Uppercase tokens ≥2 chars — likely ticker symbols; single letters are usually pronouns
    upper_candidates = [t for t in tokens if re.match(r"^[A-Z]{2,5}$", t) and t not in _STOP_WORDS]
    for candidate in upper_candidates:
        ticker = _resolve_ticker(candidate)
        if ticker:
            return ticker, text, "ticker_symbol"

    # An explicit all-caps token (e.g. "MU", "TSLA") is already unambiguous ticker
    # shorthand — trust it directly rather than discarding it when the yfinance
    # lookup above returns nothing (e.g. rate-limited or offline).
    if upper_candidates:
        return upper_candidates[0], text, "ticker_symbol"

    # 3. Other candidates — company names etc. Require the matched company's name to
    # actually start with the candidate word, so an incidental substring match
    # (e.g. "cake" inside "Cheesecake Factory") doesn't get treated as a real hit.
    other_candidates = [t for t in tokens if t.lower() not in _STOP_WORDS and not re.match(r"^[A-Z]{1,5}$", t)]
    for candidate in other_candidates:
        ticker = _resolve_ticker(candidate, require_name_match=True)
        if ticker:
            return ticker, text, "company_name"

    # 4. Full-query LLM fallback — handles sector/theme queries that elude word-by-word lookup
    ticker = _resolve_ticker_llm(text)
    if ticker:
        return ticker, text, "llm"

    return None, text, None


def _has_cheap_financial_signal(text: str) -> bool:
    """Purely local (no network, no LLM) check for evidence of financial intent:
    a concept phrase, a financial noun/intent word, or an explicit uppercase
    ticker-like token. Used to reject unrelated sentences before spending any
    yfinance search or LLM call on them.
    """
    text_lower = text.lower()
    if any(re.search(pattern, text_lower) for pattern, _ in _CONCEPT_HINTS):
        return True
    words = set(re.findall(r"\b\w+\b", text_lower))
    if words & (_FINANCIAL_KEYWORDS | _FINANCIAL_INTENT_WORDS):
        return True
    tokens = re.findall(r"\b[a-zA-Z]{1,20}\b", text)
    return any(re.match(r"^[A-Z]{2,5}$", t) and t not in _STOP_WORDS for t in tokens)


def evaluate_query(raw: str) -> QueryDecision:
    """Single entry point for a submitted query: decide scope FIRST, then resolve.

    Order matters for cost: a long sentence with no local financial signal is
    rejected here without touching yfinance or the LLM ticker fallback — the
    only queries that reach network-based resolution are ones that either show
    financial intent locally or are short enough (≤4 words) to plausibly be a
    direct ticker/company-name lookup (e.g. "sandisk").

    Out-of-scope decisions always carry ticker=None so callers can't
    accidentally chart or analyze a ticker that leaked out of a rejected query.
    """
    text = raw.strip()
    if not text:
        return QueryDecision(False, None, "", None, _OUT_OF_SCOPE_MESSAGE)

    if len(text.split()) > 4 and not _has_cheap_financial_signal(text):
        return QueryDecision(False, None, text, None, _OUT_OF_SCOPE_MESSAGE)

    ticker, question, source = parse_search_input(text)
    is_valid, message = validate_financial_query(text, ticker, source)
    if not is_valid:
        return QueryDecision(False, None, question, None, message)
    return QueryDecision(True, ticker, question, source)
