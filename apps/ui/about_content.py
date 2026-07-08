"""Editorial content for the About page.

Plain data, no rendering logic. Kept separate so it's easy to update by hand
(or paste in an LLM-drafted revision) without touching `components.py`. Update
this periodically as tools/FAQs/roadmap change; nothing here is auto-derived
from the codebase, so it can drift if a tool is added and this file isn't
updated to match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineStep:
    icon: str
    title: str
    body: str


@dataclass(frozen=True)
class ToolInfo:
    icon: str
    name: str
    module: str
    description: str


@dataclass(frozen=True)
class FaqItem:
    question: str
    answer: str


@dataclass(frozen=True)
class RoadmapItem:
    status: str  # "planned" | "in-progress" | "shipped"
    title: str
    body: str


@dataclass(frozen=True)
class Pillar:
    icon: str
    title: str
    body: str


HERO_EYEBROW = "Under the hood"

HERO_LEAD = (
    "Every stock move gets a headline. Almost none of them get a real answer. You open a "
    "chatbot, ask why your position is down 8%, and it gives you a plausible-sounding "
    "paragraph pulled from training data that's months old, with no idea what the price, "
    "volume, or news actually did today. We built this tool because that isn't good enough "
    "for a retail trader trying to make a real decision. Agentic Market Explainer pulls the "
    "actual price, volatility, options activity, and news before it says a single word about "
    "why a stock moved. It doesn't guess. It looks, and it shows its work, so when you read "
    "the answer, you know exactly which numbers it came from."
)

HERO_PILLARS: list[Pillar] = [
    Pillar(
        icon="⚙️",
        title="Deterministic first",
        body="Live price, volatility, and a statistical significance check run in plain code "
             "before any reasoning happens, so no tokens get spent explaining a routine, "
             "unremarkable move.",
    ),
    Pillar(
        icon="🧠",
        title="Agentic when it counts",
        body="Only once a move actually looks unusual does the reasoning layer switch on, "
             "deciding for itself which evidence, news, options, macro, or earnings, is worth "
             "pulling next.",
    ),
    Pillar(
        icon="🧩",
        title="Built on MCP",
        body="Every data source is a discrete, swappable MCP (Model Context Protocol) tool, "
             "an open, ever-extendable standard, so new capabilities plug in without "
             "redesigning the reasoning loop.",
    ),
]


PIPELINE_STEPS: list[PipelineStep] = [
    PipelineStep(
        icon="📊",
        title="1. Pull price & volatility, always, no LLM call",
        body="Every query starts the same way: latest price, multi-horizon % change, and "
             "realized volatility are fetched deterministically in code, before Claude is "
             "ever invoked.",
    ),
    PipelineStep(
        icon="⚡",
        title="2. Statistical significance gate",
        body="Only if the move exceeds roughly 2× the stock's own realized volatility does "
             "the app fan out further. A normal 1% drift on a high-beta name doesn't "
             "trigger the same investigation as a genuine outlier.",
    ),
    PipelineStep(
        icon="🔀",
        title="3. Parallel evidence fan-out",
        body="News and options data are fetched in parallel via a thread pool, spliced into "
             "the conversation as if the model had called them itself, with zero extra LLM "
             "round trips for this step.",
    ),
    PipelineStep(
        icon="🧠",
        title="4. Claude decides what else is needed",
        body="A tool-use loop (max 7 turns) reasons about whether anything conditional is "
             "still missing, macro context, sector comparison, earnings/FOMC proximity, "
             "and calls only the tools that are genuinely relevant.",
    ),
    PipelineStep(
        icon="✅",
        title="5. Synthesize, with a hard grounding rule",
        body="The model returns a single JSON contract: ranked hypotheses, confidence "
             "levels, and citations. Every number must trace back to a real tool result. "
             "Missing data says \"Data unavailable\" instead of being invented.",
    ),
]


MCP_TOOLS: list[ToolInfo] = [
    ToolInfo(
        icon="📊",
        name="get_price_data",
        module="price.py",
        description="Latest price, multi-horizon % change, and annualized realized volatility. "
                    "Finnhub quote first for the live tick, yfinance always for the "
                    "historical series (and as the price fallback).",
    ),
    ToolInfo(
        icon="📉",
        name="get_options_data",
        module="options.py",
        description="ATM implied volatility, IV rank, put/call ratio, and skew from the "
                    "nearest options chain.",
    ),
    ToolInfo(
        icon="🎯",
        name="get_options_positioning",
        module="options.py",
        description="Deeper 2–4 week positioning: max pain, call/put open-interest walls, IV "
                    "term-structure trend, and unusual volume-vs-open-interest activity.",
    ),
    ToolInfo(
        icon="📰",
        name="get_news",
        module="news.py",
        description="Recent headlines for the ticker over a configurable lookback window. "
                    "Finnhub first, yfinance fallback.",
    ),
    ToolInfo(
        icon="🌐",
        name="get_macro",
        module="macro.py",
        description="Market-wide indicators (VIX, S&P level), fetched once and shared, not "
                    "duplicated per ticker. FRED first, yfinance VIX fallback.",
    ),
    ToolInfo(
        icon="📅",
        name="get_events",
        module="events.py",
        description="Upcoming earnings date (yfinance) and next FOMC meeting date "
                    "(hardcoded calendar), for proximity context.",
    ),
    ToolInfo(
        icon="🎯",
        name="get_analyst_sentiment",
        module="analyst.py",
        description="Wall Street consensus rating and price targets, and how many analysts "
                    "cover the name.",
    ),
    ToolInfo(
        icon="🏭",
        name="get_sector_comparison",
        module="sector.py",
        description="Compares the stock's multi-horizon moves against its sector ETF's moves, "
                    "to separate stock-specific news from a sector-wide drift.",
    ),
]


FAQS: list[FaqItem] = [
    FaqItem(
        question="Is this financial advice?",
        answer="No. This is an informational and educational tool that describes recent "
               "price action. It does not predict future moves or recommend buying, "
               "selling, or holding anything. Always verify important numbers against a "
               "primary source and consult a licensed financial advisor before acting.",
    ),
    FaqItem(
        question="Where does the data come from?",
        answer="Nothing here is scraped by hand or hardcoded; every number comes from a "
               "live API call inside one of the MCP tools. The live quote (price, "
               "previous close) is pulled from Finnhub's REST API when a key is "
               "configured, since it's a single fast call. The historical daily series "
               "used to compute realized volatility and the 1d/1w/2w/1mo/YTD/1y "
               "% changes always comes from `yfinance`, because Finnhub's candle "
               "endpoint needs a paid plan, so `yfinance` is fetched regardless and "
               "also serves as the fallback if Finnhub is unavailable or unconfigured. "
               "News headlines work the same way: Finnhub's company-news endpoint "
               "first, `yfinance` news as the fallback. Macro (VIX) comes from the "
               "St. Louis Fed's FRED API (series `VIXCLS`) when a key is set, or "
               "`yfinance`'s `^VIX` and `^GSPC` histories otherwise. Options chains, "
               "analyst consensus, upcoming earnings dates, and sector-ETF classification "
               "all come straight from `yfinance`'s option-chain and `Ticker.info` "
               "endpoints, since there's no equivalent paid source wired in for those "
               "yet. FOMC meeting dates are the one deliberately static piece: a "
               "hardcoded calendar, since the Fed's schedule doesn't change often "
               "enough to justify an API call. Every tool degrades gracefully; if a "
               "paid key is missing or a call fails, it falls through to the next "
               "source rather than erroring out the whole query.",
    ),
    FaqItem(
        question="Why didn't it look at news or options for my query?",
        answer="Because the move didn't clear the significance bar, and that bar isn't a "
               "single number. `price.py` scores every horizon (1d, 1w, 2w, 1mo, YTD, 1y) "
               "on two independent axes: a relative ratio (how many multiples of the "
               "stock's own expected move, derived from its trailing 20-day annualized "
               "realized volatility scaled by √time, did this move represent?) and an "
               "absolute magnitude floor (is this a big move in plain percentage terms, "
               "regardless of whose stock it is?). Both have to say \"typical\" for a "
               "horizon to get waved through; if either says \"elevated\" or \"unusual,\" "
               "the app fans out to news, options, macro, and whatever else the model "
               "decides is relevant. The two-axis design exists to catch a specific "
               "failure mode: a chronically volatile name (say, 90%+ annualized vol) can "
               "make almost any move look statistically \"normal\" for that one ticker, "
               "even when it's an 18% drop that would matter to any reader. The absolute "
               "floor stops that from getting rubber-stamped away. A routine 0.5% drift on "
               "a calm day fails both axes and gets a short, cheap answer. That's the "
               "point: it's a latency and token-cost optimization, not a coverage gap.",
    ),
    FaqItem(
        question="Can the AI make up numbers?",
        answer="It's structurally discouraged, not just asked nicely not to. Two things do "
               "the work. First, grounding: the system prompt requires the final JSON "
               "contract (ranked hypotheses, confidence levels, citations) to have every "
               "number trace back to a real tool_result block already in the conversation, "
               "not the model's parametric memory. If a source fails or comes back empty, "
               "the model is told to write \"Data unavailable\" rather than fill the gap "
               "with something plausible. Second, the deterministic pre-fetch: price and "
               "volatility are computed in plain Python before Claude is ever invoked, and "
               "spliced into the conversation as synthetic tool_use / tool_result turns, "
               "so the model never sees a blank canvas where it has to recall a number "
               "from training. Claude only decides what else to pull (news, options, "
               "macro, sector, earnings) via a real tool-use loop capped at 7 turns, so "
               "every subsequent fact it cites came from an actual function call it made "
               "in this session. None of that makes the model infallible. Like any LLM, "
               "it can still misread a headline or mischaracterize a trend, so verify "
               "anything you're going to act on.",
    ),
    FaqItem(
        question="What's the difference between this and a normal chatbot?",
        answer="A general-purpose chatbot answers from what it already \"knows,\" which for a "
               "stock move means stale training data and a confident guess. It has no live "
               "price, no idea what happened in the options market this morning, and no way "
               "to check its own answer. That's fine for writing an email. It's not fine for "
               "understanding why your position just moved. This app is grounded: it pulls "
               "real, current price, volatility, options, and news data before the model "
               "reasons about anything, runs several deterministic checks in code first, and "
               "forces the final answer into a contract where every figure has to trace back "
               "to an actual tool result. That's the real difference between a specialized, "
               "grounded tool and a generic model reciting from memory, and it's why we "
               "believe this gives you a materially better answer to \"why did this move\" "
               "than asking ChatGPT or Claude directly. It doesn't eliminate hallucination "
               "risk entirely, but the model is reasoning over real data instead of "
               "recalling from memory.",
    ),
    FaqItem(
        question="Does this work for non-US stocks?",
        answer="Best support is for US-listed equities and ETFs. Price, options, news, and "
               "macro sources are all US-market oriented (Finnhub, FRED, and yfinance's "
               "US coverage), so non-US tickers may resolve with sparse or missing data, or "
               "not resolve at all. Treat results outside US markets as unreliable for now.",
    ),
    FaqItem(
        question="Can I use these tools outside this app?",
        answer="Yes. The same tool functions are also exposed as a standalone MCP "
               "(Model Context Protocol) server, so any MCP-compatible client (e.g. Claude "
               "Desktop) can call them directly.",
    ),
]


LIMITATIONS: list[str] = [
    "US-market only. Price, options, news, and macro sources are all oriented around "
    "US-listed equities and ETFs; non-US tickers aren't reliably supported and thinly-covered "
    "US names may come back with sparse evidence.",
    "No intraday tick data or Level 2 order book. Options positioning and price moves are "
    "summarized, not tick-by-tick.",
    "The significance gate means small, \"boring\" moves intentionally get a shallow "
    "investigation. This is a deliberate cost/latency tradeoff, not a coverage gap to fix.",
    "Like any LLM system, outputs can be incomplete, out of date, or simply wrong. Every "
    "claim should be checked against a primary source before you act on it.",
]


ROADMAP: list[RoadmapItem] = [
    RoadmapItem(
        status="planned",
        title="Crypto & FX coverage",
        body="Extend beyond equities/ETFs to major crypto and FX pairs.",
    ),
    RoadmapItem(
        status="planned",
        title="Multi-ticker comparisons",
        body="Ask about two tickers at once (\"AAPL vs MSFT this week\") in a single run.",
    ),
    RoadmapItem(
        status="in-progress",
        title="Persistent query history",
        body="Save past investigations across sessions instead of resetting on refresh.",
    ),
]
