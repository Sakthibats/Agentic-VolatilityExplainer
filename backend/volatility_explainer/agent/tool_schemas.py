"""Tool definitions the model sees — JSON schemas plus the "when to call this" guidance.

Per-tool selection criteria live in each `description` below (the model reads them at
tool-selection time), so they are deliberately not repeated in prompts.py. Implementations
live in volatility_explainer.tools and are wired to these names by the orchestrator's
_TOOL_DISPATCH — keep both name sets (and clients/redis_cache.py's TTL table) in sync.

Order matters: submit_analysis stays LAST, since its cache_control marks the prompt-cache
breakpoint for the whole tool list, and `explanation` stays its LAST property (see
eager_input_streaming at the bottom).
"""

from __future__ import annotations

# The only two ways the model may end a turn. Free text is never a valid ending.
TERMINAL_TOOLS = frozenset({"submit_analysis", "flag_out_of_scope"})

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_price_data",
        "description": (
            "Fetch current price, daily % change, and 20-day realized volatility for a ticker, "
            "plus move_assessment — a deterministic significance verdict (overall level plus "
            "one plain-English flag per non-typical horizon). "
            "ALREADY CALLED FOR YOU — check the conversation above for its result before calling this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_news",
        "description": (
            "Fetch recent news headlines for a ticker (last 7 days). Not pre-fetched — decide "
            "whether to call it based on price_data (already given) and the question. Almost "
            "always worth calling when the horizon relevant to the question has a flag in "
            "move_assessment (especially an 'unusual' one) and the question is (or implies) "
            "'why did this move' — that's the catalyst check. Skip it for questions that "
            "aren't about causation (e.g. pure valuation/analyst-opinion questions) or for an "
            "unflagged, plainly typical move."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_options_data",
        "description": (
            "Quick snapshot of how the options market is pricing the next 2-4 weeks for this "
            "stock (implied volatility, put/call ratio, skew) — a general hint of market mood, "
            "not a deep dive. Not pre-fetched — worth calling alongside get_news as a brief "
            "secondary signal for a significant move, or whenever the question touches on what "
            "the market expects next. Skip it if the question doesn't relate to market "
            "positioning/expectations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_options_positioning",
        "description": (
            "A deeper look at how the options market is positioned for this stock over the "
            "next 2-4 weeks: max pain (the strike price options traders are effectively "
            "betting the stock settles near), call/put open-interest walls (support/resistance "
            "levels), IV term structure across the horizon, and unusual volume vs. open "
            "interest (signals fresh positioning being put on today, not stale interest). "
            "This is NOT called in the first tool-selection pass — only call it, in a later "
            "turn, when the question specifically needs this depth (\"where are options "
            "traders positioned\", \"what's the max pain level\", \"is there unusual options "
            "activity\") or when get_options_data's quick snapshot showed something — like an "
            "unusually high put/call ratio or IV — that warrants investigating further. Skip "
            "this for routine questions; it is a deliberate, deeper second-layer step, not a "
            "default check."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_analyst_sentiment",
        "description": (
            "The Wall Street analyst view, in two parts. recent_actions: DATED rating "
            "changes from the last 30 days — which firm upgraded or downgraded the stock, "
            "and whether they raised or cut their price target. consensus and price_target: "
            "where the Street stands now — rating, a plain-English verdict, whether that "
            "consensus has been improving or deteriorating over recent months, and the mean/"
            "median/high/low targets with how dispersed they are. Never pre-fetched. "
            "Call it when the question is about valuation or sentiment (\"is this "
            "overvalued\", \"what does the Street think\", \"should I be worried\"), AND "
            "also as a catalyst check on a flagged move: a downgrade with a price-target cut "
            "a few days ago is a genuine, datable cause of a drop, so a non-empty "
            "recent_actions is real evidence for a \"why did it move\" answer. The standing "
            "consensus on its own is NOT — that is a medium-term view, not a live reaction, "
            "so do not offer it as the cause of a single day's move. "
            "analyst_coverage of 'none' means the ticker genuinely has no analysts (an ETF "
            "or fund) — a valid, expected result, not a failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_sector_comparison",
        "description": (
            "Compares this stock's % move over the same horizons (today, 1 week, 2 weeks, "
            "1 month, 1 year) against its own sector's ETF (e.g. Technology stocks vs. XLK). "
            "Never pre-fetched — call this when you need a MORE PRECISE stock-specific-vs-"
            "industry-wide check than get_macro provides. get_macro only tells you if the "
            "whole market moved (S&P 500 / VIX); this tells you if the stock's SECTOR moved "
            "with it, which is the better test when the news or the user's question points to "
            "an industry-wide theme (e.g. \"did all bank stocks drop\", \"is this a tech "
            "selloff or just this stock\", chip-sector news, sector-wide regulation). Prefer "
            "get_macro first for a broad market check; reach for this when the question is "
            "specifically about sector/peer behavior or get_macro doesn't fully explain the move."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_macro",
        "description": (
            "Fetch macro indicators: VIX level and S&P 500 daily change. "
            "Call this to determine if a move is stock-specific or part of a broader market move. "
            "If VIX spiked and SPX dropped broadly, that is market context — not a stock catalyst."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_events",
        "description": (
            "ALREADY CALLED FOR YOU — check the conversation above for its result before "
            "calling this. "
            "Fetches this ticker's event calendar in BOTH directions: recent_events (already "
            "happened — earnings it just reported, with the actual-vs-expected EPS beat/miss, "
            "and any ex-dividend date it just passed) and events (still ahead — next earnings "
            "date and next FOMC meeting). "
            "Use the backward-looking half whenever the question is \"why did this move\" and "
            "a horizon is flagged in move_assessment: a quarter reported in the last few days "
            "is one of the most common explanations there is, and an ex-dividend date makes a "
            "price drop MECHANICAL rather than a catalyst — do not invent a news explanation "
            "for a move that lands on one. Use the forward-looking half when pre-event "
            "positioning might be driving options activity, or when earnings proximity might "
            "explain a volatility spike. "
            "earnings_status of 'none' means this ticker genuinely has no earnings (an ETF or "
            "fund) — a valid answer, not a failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "flag_out_of_scope",
        "description": (
            "Call this INSTEAD of any data tool, and before calling anything else, if the "
            "request is not about a stock/ETF/market price movement. This is the only way "
            "to end the investigation as out-of-scope — do not write an error as plain text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Plain sentence telling the user this tool only investigates stock and ETF price movements.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "submit_analysis",
        "description": (
            "Call this to deliver your final write-up once the investigation is complete — "
            "this is the ONLY way to finish; never write the final answer as plain text. "
            "Call it exactly once, after you've gathered all the evidence you need."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tiles": {
                    "type": "array",
                    "description": (
                        "One tile per tool result that MEANINGFULLY informed the answer — not "
                        "one per tool merely called. Skip a tile for any tool whose result "
                        "turned out uninformative or redundant with another tile (e.g. macro "
                        "showed nothing unusual and sector already covers the same ground). "
                        "get_price_data almost always earns a tile; news/options usually do too "
                        "when you called them. Curate like an analyst presenting findings, not a "
                        "log of every data source touched. Hard cap of 4 — if you have more "
                        "candidates, drop the least informative ones rather than including all."
                    ),
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent": {
                                "type": "string",
                                "enum": ["price", "news", "options", "macro", "events", "analyst", "sector"],
                            },
                            "title": {"type": "string", "description": "e.g. Price Action"},
                            "summary": {
                                "type": "string",
                                "description": "1-2 plain sentences (<=35 words) with a real number — easy for a beginner to read",
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "ONE short sentence (<=18 words): why this data mattered",
                            },
                        },
                        "required": ["agent", "title", "summary", "reasoning"],
                    },
                },
                "hypotheses": {
                    "type": "array",
                    "description": (
                        "At least TWO plausible drivers, ranked by confidence (rank 1 = most "
                        "likely). Even when one cause clearly dominates, include a genuinely "
                        "distinct second (or third) explanation — e.g. a broader sector/macro "
                        "contributor, a secondary catalyst, or 'no unusual driver found, within "
                        "normal noise' — rather than manufacturing a redundant near-duplicate of "
                        "the top hypothesis."
                    ),
                    "minItems": 2,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "rank": {"type": "integer"},
                            "hypothesis": {"type": "string", "description": "short phrase, max 10 words"},
                            "evidence": {"type": "string", "description": "one plain fact or number, or Limited"},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "caveat": {"type": "string", "description": "one clause or N/A"},
                        },
                        "required": ["rank", "hypothesis", "evidence", "confidence", "caveat"],
                    },
                },
                "explanation": {
                    "type": "string",
                    "description": (
                        "40-70 words, 2-3 short sentences. Written LAST, as the conclusion of the "
                        "tiles and ranked hypotheses above: it must agree with your rank-1 "
                        "hypothesis and its confidence. The reader has already read the factual "
                        "overview quoted in the first user message, so never repeat its numbers "
                        "(price, today's %, the usual daily range, the horizons it mentions). "
                        "Shape: (1) Answer the user's question with the most likely cause and how "
                        "sure the evidence lets you be, in plain words ('most likely', 'possibly', "
                        "'no clear cause found'). If the overview calls the move normal for this "
                        "stock, say it needs no special explanation unless you found a dated "
                        "catalyst. If they asked about a horizon the overview doesn't mention, "
                        "give that horizon's real number. (2) The single strongest piece of "
                        "evidence, with its date. If it came from a news headline, cite it as [n] "
                        "using that headline's `ref` from get_news — never write a link, and never "
                        "a number get_news didn't give. (3) Only if you called get_macro or "
                        "get_sector_comparison: whether the market or sector moved the same way, "
                        "which is what makes the cause stock-specific or not."
                    ),
                },
            },
            "required": ["tiles", "hypotheses", "explanation"],
        },
        "cache_control": {"type": "ephemeral"},
        # Stream this tool's input in fine-grained chunks rather than a few large ones, so
        # `explanation` can be surfaced to the reader as it is written. It is the LAST
        # property in the schema above and must stay there — the model emits properties in
        # schema order, and the why-paragraph is only worth reading once the model has
        # already committed to its tiles and ranked hypotheses. (It used to come first,
        # which rendered sooner but meant the model concluded before it had reasoned.) The
        # reader isn't left waiting meanwhile: the deterministic overview from
        # tools/price.describe_move is on screen from the end of the pre-fetch. Named so no
        # nested property shares it — the partial-JSON reader matches the first occurrence.
        # Not a beta feature.
        "eager_input_streaming": True,
    },
]
