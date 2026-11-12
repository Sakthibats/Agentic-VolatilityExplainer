"""Query parsing, ticker resolution, and the financial-scope guardrail.

Backend business logic: the API resolves tickers and enforces scope so no frontend ever
re-implements it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryDecision:
    """Outcome of the scope gate for one submitted query.

    When in_scope is False, ticker is always None and message holds the
    guardrail text — nothing downstream (ticker resolution, charts, agents)
    should run for that query.

    question is "" when the query only names the ticker ("TSLA", "why did tesla
    move today"); see _specific_question.
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

# The one out-of-scope reply, shown whether the scope gate below or the agent's
# flag_out_of_scope tool rejects a query: the model never writes its own refusal text.
OUT_OF_SCOPE_MESSAGE = (
    "This tool investigates **stock and ETF price movements** only. "
    "Ask about a company (*why did Apple dip?*), a ticker (*TSLA*), "
    "or a market/asset (*what happened to gold?*, *why is the market down?*)."
)

# Per-process resolution caches. Keys come from user text, so each is bounded
# (_MAX_CACHE_ENTRIES, oldest entry evicted first). Only real answers are cached, "no
# ticker" included; a failed lookup (Yahoo throttling, an LLM timeout) is not, or one
# upstream blip would leave that name unresolvable until the process restarts.
_MAX_CACHE_ENTRIES = 2048
_ticker_cache: dict[str, str | None] = {}
_llm_ticker_cache: dict[str, str | None] = {}
# Lower-cased company name of each symbol _resolve_ticker accepted, so the scope gate can tell
# "coca cola" (both words are the name) from "my mom scold me" ("mom" matched Momentus).
_company_names: dict[str, str] = {}


def _remember(cache: dict, key: str, value) -> None:
    if key not in cache and len(cache) >= _MAX_CACHE_ENTRIES:
        cache.pop(next(iter(cache)))  # dicts keep insertion order: this is the oldest
    cache[key] = value


_CODE_FENCE = re.compile(r"^\s*```(?:json)?|```\s*$", re.IGNORECASE)


def _resolve_ticker_llm(query: str) -> str | None:
    """Ask the configured LLM to map a free-form query to the most relevant US ticker.
    Result is cached per unique query string. Returns None for anything that isn't
    clearly a financial/company/sector reference — this is a last-resort fallback,
    so it must be conservative rather than guessing a plausible-looking ticker.
    """
    key = query.strip().lower()
    if key in _llm_ticker_cache:
        return _llm_ticker_cache[key]
    try:
        from volatility_explainer.config import get_settings
        from volatility_explainer.llm import get_provider

        text = get_provider(get_settings()).complete(
            max_tokens=30,
            prompt=(
                f'Does this text clearly refer to a specific US-listed stock, company, sector, '
                f'or asset (not a generic word, unrelated topic, or full sentence about something '
                f'else)? Text: "{query}"\n'
                'Reply ONLY with JSON: {"ticker": "SYMBOL"} if clearly yes, or {"ticker": null} '
                'if there is any doubt, ambiguity, or the text isn\'t about a financial instrument.\n'
                'Company name → primary US ticker. Sector/theme → most liquid ETF.\n'
                'Examples: "sandisk"→SNDK, "apple"→AAPL, "chip sector"→SOXX, '
                '"gold"→GLD, "market"→SPY, "nasdaq"→QQQ, "crypto"→IBIT, '
                '"bake a cake"→null, "how do I learn python"→null, "weather today"→null'
            ),
        )
    except Exception as exc:  # no answer: not cached, so the next ask retries
        print(f"[resolve] LLM ticker fallback FAILED — {type(exc).__name__}: {exc}")
        return None

    result = None
    try:
        # Models often wrap a JSON-only reply in a ```json fence; json.loads rejects that,
        # and the except below used to turn every such reply into "no ticker" silently.
        data = json.loads(_CODE_FENCE.sub("", text).strip())
        t = str(data.get("ticker") or "").strip().upper()
        if re.match(r"^[A-Z]{1,5}$", t):
            result = t
    except (ValueError, AttributeError):
        pass  # an unreadable reply is the model's answer: no ticker
    _remember(_llm_ticker_cache, key, result)
    return result


def _words(text: str) -> str:
    """Lower-cased words joined by single spaces: "Coca-Cola, Inc." → "coca cola inc"."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


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
    query = search_query or term
    try:
        import yfinance as yf

        hits = yf.Search(query, max_results=10).quotes
    except Exception as exc:  # no answer: not cached, so the next ask retries
        print(f"[resolve] yfinance search {query!r} FAILED — {type(exc).__name__}: {exc}")
        return None

    result = None
    try:
        for h in hits:
            sym = h.get("symbol", "")
            # Accept only clean 1-5 letter tickers (no dots, hyphens — those are usually foreign or preferred)
            if not re.match(r"^[A-Z]{1,5}$", sym):
                continue
            name = (h.get("shortname") or h.get("longname") or "").strip().lower()
            # Punctuation-blind, so "coca cola" matches "Coca-Cola Company".
            if require_name_match and not _words(name).startswith(_words(query)):
                continue
            if name:
                _remember(_company_names, sym, name)
            result = sym
            break
    except (AttributeError, TypeError):
        pass  # a malformed result list is an answer: nothing usable
    _remember(_ticker_cache, cache_key, result)
    return result


def _is_name_lookup(raw: str, ticker: str, matched: str) -> bool:
    """True when a query is just the matched company name plus filler words.

    Every other word must be a stop word, a financial word, the ticker, a number, or part
    of the company's own name ("coca cola" → "The Coca-Cola Company"). "my mom scold me"
    fails: "mom" matched Momentus (MNTS), and "scold" is none of those.
    """
    rest = re.sub(re.escape(matched), " ", raw, count=1, flags=re.IGNORECASE).lower()
    name_words = set(re.findall(r"[a-z0-9]+", _company_names.get(ticker, "")))
    allowed = (_STOP_WORDS | _GENERIC_ASK_WORDS | _FINANCIAL_KEYWORDS | _FINANCIAL_INTENT_WORDS
               | name_words | {ticker.lower()})
    return all(w in allowed or w.isdigit() for w in re.findall(r"[a-z0-9]+", rest))


def validate_financial_query(
    raw: str, ticker: str | None, source: str | None = None, matched: str | None = None,
) -> tuple[bool, str]:
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

    `matched` is the word that resolved a company_name ticker. When given, a short query
    counts as a lookup only if its other words add nothing (_is_name_lookup): "my mom scold
    me" is four words, but it's a sentence, not a search for Momentus.
    """
    if ticker and source in ("concept", "ticker_symbol"):
        return True, ""
    short_lookup = ticker and source in ("company_name", "llm") and len(raw.split()) <= 4
    if short_lookup and (source == "llm" or matched is None or _is_name_lookup(raw, ticker, matched)):
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

    return False, OUT_OF_SCOPE_MESSAGE


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
    ticker, text, source, _matched = _parse_search_input(raw)
    return ticker, text, source


def _parse_search_input(raw: str) -> tuple[str | None, str, str | None, str | None]:
    """parse_search_input, plus the text that resolved the ticker (the concept phrase,
    ticker token or company word) so evaluate_query can tell what else was asked.
    None when nothing resolved or the LLM fallback did (it matches the whole query).
    """
    text = raw.strip()
    if not text:
        return None, "", None, None

    text_lower = text.lower()

    # 1. Concept phrases first — catches "gold price", "market", "s&p 500", etc.
    for pattern, search_query in _CONCEPT_HINTS:
        if match := re.search(pattern, text_lower):
            ticker = _resolve_ticker(search_query, search_query)
            if ticker:
                return ticker, text, "concept", match.group(0)

    # {1,6} was a bug — company names like "sandisk" (7 chars) were silently dropped
    tokens = re.findall(r"\b[a-zA-Z]{1,20}\b", text)

    # 2. Uppercase tokens ≥2 chars — likely ticker symbols; single letters are usually pronouns
    upper_candidates = [t for t in tokens if re.match(r"^[A-Z]{2,5}$", t) and t not in _STOP_WORDS]
    for candidate in upper_candidates:
        ticker = _resolve_ticker(candidate)
        if ticker:
            return ticker, text, "ticker_symbol", candidate

    # An explicit all-caps token (e.g. "MU", "TSLA") is already unambiguous ticker
    # shorthand — trust it directly rather than discarding it when the yfinance
    # lookup above returns nothing (e.g. rate-limited or offline).
    if upper_candidates:
        return upper_candidates[0], text, "ticker_symbol", upper_candidates[0]

    # 3. Other candidates — company names etc. Require the matched company's name to
    # actually start with the candidate word, so an incidental substring match
    # (e.g. "cake" inside "Cheesecake Factory") doesn't get treated as a real hit.
    other_candidates = [t for t in tokens if t.lower() not in _STOP_WORDS and not re.match(r"^[A-Z]{1,5}$", t)]
    # The whole name first when it's several words in a row: word by word, "general motors"
    # matched "general" → General Mills (GIS).
    phrase = " ".join(other_candidates)
    if len(other_candidates) > 1 and phrase.lower() in " ".join(tokens).lower():
        ticker = _resolve_ticker(phrase, require_name_match=True)
        if ticker:
            return ticker, text, "company_name", phrase
    for candidate in other_candidates:
        ticker = _resolve_ticker(candidate, require_name_match=True)
        if ticker:
            return ticker, text, "company_name", candidate

    # 4. Full-query LLM fallback — handles sector/theme queries that elude word-by-word lookup
    ticker = _resolve_ticker_llm(text)
    if ticker:
        return ticker, text, "llm", None

    return None, text, None, None


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


# Words that add nothing beyond "explain this ticker's recent move". Narrower than
# _STOP_WORDS on purpose: buy/sell, puts/calls, iv, week/month and numbers all
# make a question specific. Direction words (drop, rally, crash) count as generic:
# the code-built overview states the real direction and size either way.
_GENERIC_ASK_WORDS: frozenset[str] = frozenset({
    "why", "what", "whats", "s", "how", "did", "does", "do", "is", "are", "was",
    "the", "a", "an", "with", "to", "of", "on", "in", "for", "at", "about", "me",
    "stock", "stocks", "share", "shares", "price", "ticker", "company",
    "move", "moved", "moving", "moves", "movement", "happened", "happening",
    "happen", "going", "go", "up", "down", "drop", "dropped", "dropping", "fall",
    "fell", "falling", "rise", "rose", "rising", "jump", "jumped", "spike",
    "spiked", "surge", "surged", "crash", "crashed", "dip", "dipped", "rally",
    "rallied", "today", "now", "recently", "lately", "just", "explain", "tell", "so",
})


def _specific_question(text: str, ticker: str | None, matched: str | None) -> str:
    """The question to send the model, or "" when the query only names a ticker.

    "" sends the run down the generic "explain the recent price action" path, the only
    one whose answer is cached (api/service.py). Without this, a bare "TSLA" counted
    as a question and the final-answer cache never served a request. When unsure,
    for example when the LLM fallback resolved the ticker, it keeps the full text.
    """
    if not ticker or not matched:
        return text
    rest = re.sub(re.escape(matched), " ", text, count=1, flags=re.IGNORECASE).lower()
    subject = set(re.findall(r"[a-z0-9]+", ticker.lower()))
    words = [w for w in re.findall(r"[a-z0-9]+", rest) if w not in subject]
    return "" if all(w in _GENERIC_ASK_WORDS for w in words) else text


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
        return QueryDecision(False, None, "", None, OUT_OF_SCOPE_MESSAGE)

    if len(text.split()) > 4 and not _has_cheap_financial_signal(text):
        return QueryDecision(False, None, text, None, OUT_OF_SCOPE_MESSAGE)

    ticker, question, source, matched = _parse_search_input(text)
    is_valid, message = validate_financial_query(text, ticker, source, matched)
    if not is_valid:
        return QueryDecision(False, None, question, None, message)
    return QueryDecision(True, ticker, _specific_question(question, ticker, matched), source)
