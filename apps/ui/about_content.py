"""Editorial content for the About page.

Plain data, no rendering logic — kept separate so it's easy to update by hand
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
    "Every price move gets a headline. Almost none of them get an actual investigation — "
    "usually it's a generic recap, or a chatbot guessing from memory instead of looking "
    "anything up. Agentic Market Explainer closes that gap: it behaves like a quick, "
    "tireless analyst who pulls the real numbers before saying anything, so \"why did this "
    "move\" gets an answer traceable to real data instead of a plausible-sounding guess."
)

HERO_PILLARS: list[Pillar] = [
    Pillar(
        icon="⚙️",
        title="Deterministic first",
        body="Live price, volatility, and a statistical significance check run in plain code, "
             "before any reasoning happens — no tokens spent on a routine, unremarkable move.",
    ),
    Pillar(
        icon="🧠",
        title="Agentic when it counts",
        body="Only once a move actually looks unusual does the reasoning layer switch on, "
             "deciding for itself which evidence — news, options, macro, earnings — is worth "
             "pulling next.",
    ),
    Pillar(
        icon="🧩",
        title="Built on MCP",
        body="Every data source is a discrete, swappable MCP (Model Context Protocol) tool — "
             "an open, ever-extendable standard, so new capabilities plug in without "
             "redesigning the reasoning loop.",
    ),
]


PIPELINE_STEPS: list[PipelineStep] = [
    PipelineStep(
        icon="📊",
        title="1. Pull price & volatility — always, no LLM call",
        body="Every query starts the same way: latest price, multi-horizon % change, and "
             "realized volatility are fetched deterministically in code, before Claude is "
             "ever invoked.",
    ),
    PipelineStep(
        icon="⚡",
        title="2. Statistical significance gate",
        body="Only if the move exceeds roughly 2× the stock's own realized volatility does "
             "the app fan out further — a normal 1% drift on a high-beta name doesn't "
             "trigger the same investigation as a genuine outlier.",
    ),
    PipelineStep(
        icon="🔀",
        title="3. Parallel evidence fan-out",
        body="News and options data are fetched in parallel via a thread pool, spliced into "
             "the conversation as if the model had called them itself — zero extra LLM "
             "round trips for this step.",
    ),
    PipelineStep(
        icon="🧠",
        title="4. Claude decides what else is needed",
        body="A tool-use loop (max 7 turns) reasons about whether anything conditional is "
             "still missing — macro context, sector comparison, earnings/FOMC proximity — "
             "and calls only the tools that are genuinely relevant.",
    ),
    PipelineStep(
        icon="✅",
        title="5. Synthesize, with a hard grounding rule",
        body="The model returns a single JSON contract: ranked hypotheses, confidence "
             "levels, and citations. Every number must trace back to a real tool result — "
             "missing data says \"Data unavailable\" instead of being invented.",
    ),
]


MCP_TOOLS: list[ToolInfo] = [
    ToolInfo(
        icon="📊",
        name="get_price_data",
        module="price.py",
        description="Latest price, multi-horizon % change, and annualized realized volatility. "
                    "Alpaca first, yfinance fallback.",
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
        description="Market-wide indicators (VIX, S&P level) — one shared fetch, not "
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
               "price action — it does not predict future moves or recommend buying, "
               "selling, or holding anything. Always verify important numbers against a "
               "primary source and consult a licensed financial advisor before acting.",
    ),
    FaqItem(
        question="Where does the data come from?",
        answer="Price data from Alpaca, news from Finnhub, and macro indicators from FRED — "
               "each with a `yfinance` fallback if the primary source fails or a key is "
               "missing. Options data comes directly from yfinance option chains.",
    ),
    FaqItem(
        question="Why didn't it look at news or options for my query?",
        answer="The app only pays for the expensive news/options fan-out when the move is "
               "statistically significant (roughly 2× the stock's normal daily volatility). "
               "A routine 0.5% drift on a calm day doesn't get the full investigation — "
               "that's by design, not a bug.",
    ),
    FaqItem(
        question="Can the AI make up numbers?",
        answer="The system prompt hard-requires every number in the output to trace back to "
               "a real tool result. If a data source fails or has nothing, the app is told "
               "to say \"Data unavailable\" rather than invent a figure — but like any LLM "
               "system, it can still misinterpret or misstate something, so verify anything "
               "important.",
    ),
    FaqItem(
        question="What's the difference between this and a normal chatbot?",
        answer="A prompt-wrapped chatbot answers from what it already \"knows\" — no live "
               "numbers, no way to check itself. This app is grounded: it pulls real, "
               "current price, volatility, options, and news data on request, runs several "
               "deterministic checks in code before the model ever reasons, and forces the "
               "final answer into a contract where every figure must trace back to an actual "
               "tool result. That multi-step, code-verified grounding is what cuts "
               "hallucination risk far below a plain \"ask an LLM\" answer — it doesn't "
               "eliminate it, but the model is reasoning over real data instead of recalling "
               "from memory.",
    ),
    FaqItem(
        question="Does this work for non-US stocks?",
        answer="Best support is for US-listed equities and ETFs. Price, options, news, and "
               "macro sources are all US-market oriented (Alpaca, Finnhub, FRED, yfinance's "
               "US coverage), so non-US tickers may resolve with sparse or missing data, or "
               "not resolve at all. Treat results outside US markets as unreliable for now.",
    ),
    FaqItem(
        question="Can I use these tools outside this app?",
        answer="Yes — the same tool functions are also exposed as a standalone MCP "
               "(Model Context Protocol) server, so any MCP-compatible client (e.g. Claude "
               "Desktop) can call them directly.",
    ),
]


LIMITATIONS: list[str] = [
    "US-market only — price, options, news, and macro sources are all oriented around "
    "US-listed equities and ETFs; non-US tickers aren't reliably supported and thinly-covered "
    "US names may come back with sparse evidence.",
    "No intraday tick data or Level 2 order book — options positioning and price moves are "
    "summarized, not tick-by-tick.",
    "The significance gate means small, \"boring\" moves intentionally get a shallow "
    "investigation — this is a deliberate cost/latency tradeoff, not a coverage gap to fix.",
    "Like any LLM system, outputs can be incomplete, out of date, or simply wrong — every "
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
