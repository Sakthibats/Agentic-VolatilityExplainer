import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About — Agentic Market Explainer",
};

const PILLARS = [
  {
    icon: "⚙️",
    title: "Deterministic first",
    body: "Live price, volatility, and a statistical significance check run in plain code before any reasoning happens, so no tokens get spent explaining a routine, unremarkable move.",
  },
  {
    icon: "🧠",
    title: "Agentic when it counts",
    body: "Only once a move actually looks unusual does the reasoning layer switch on, deciding for itself which evidence, news, options, macro, or earnings, is worth pulling next.",
  },
  {
    icon: "🧩",
    title: "Built on MCP",
    body: "Every data source is a discrete, swappable MCP (Model Context Protocol) tool, an open, ever-extendable standard, so new capabilities plug in without redesigning the reasoning loop.",
  },
];

const PIPELINE = [
  {
    icon: "📊",
    title: "1. Pull price & volatility, always, no LLM call",
    body: "Every query starts the same way: latest price, multi-horizon % change, and realized volatility are fetched deterministically in code, before the LLM is ever invoked.",
  },
  {
    icon: "⚡",
    title: "2. Statistical significance gate",
    body: "Only if the move exceeds roughly 2× the stock's own realized volatility does the app fan out further. A normal 1% drift on a high-beta name doesn't trigger the same investigation as a genuine outlier.",
  },
  {
    icon: "🔀",
    title: "3. Parallel evidence fan-out",
    body: "News and options data are fetched in parallel, spliced into the conversation as if the model had called them itself, with zero extra LLM round trips for this step.",
  },
  {
    icon: "🧠",
    title: "4. The LLM decides what else is needed",
    body: "Reasoning is handled by Claude Haiku, chosen for its balance of speed, cost, and quality in this kind of tool-use loop. A tool-use loop (max 7 turns) reasons about whether anything conditional is still missing, macro context, sector comparison, earnings/FOMC proximity, and calls only the tools that are genuinely relevant.",
  },
  {
    icon: "✅",
    title: "5. Synthesize, with a hard grounding rule",
    body: "The model returns a single JSON contract: ranked hypotheses, confidence levels, and citations. Every number must trace back to a real tool result. Missing data says “Data unavailable” instead of being invented.",
  },
];

const TOOLS = [
  {
    icon: "📊",
    name: "get_price_data",
    module: "price.py",
    body: "Latest price, multi-horizon % change, and annualized realized volatility. Finnhub quote first for the live tick, yfinance always for the historical series (and as the price fallback).",
  },
  {
    icon: "📉",
    name: "get_options_data",
    module: "options.py",
    body: "ATM implied volatility, IV rank, put/call ratio, and skew from the nearest options chain.",
  },
  {
    icon: "🎯",
    name: "get_options_positioning",
    module: "options.py",
    body: "Deeper 2–4 week positioning: max pain, call/put open-interest walls, IV term-structure trend, and unusual volume-vs-open-interest activity.",
  },
  {
    icon: "📰",
    name: "get_news",
    module: "news.py",
    body: "Recent headlines for the ticker over a configurable lookback window. Finnhub first, yfinance fallback.",
  },
  {
    icon: "🌐",
    name: "get_macro",
    module: "macro.py",
    body: "Market-wide indicators (VIX, S&P level), fetched once and shared, not duplicated per ticker. FRED first, yfinance VIX fallback.",
  },
  {
    icon: "📅",
    name: "get_events",
    module: "events.py",
    body: "Earnings in both directions — the quarter just reported (with the actual-vs-expected beat or miss) and the next one scheduled (Finnhub, yfinance fallback) — plus recent ex-dividend dates and the next FOMC meeting.",
  },
  {
    icon: "🎯",
    name: "get_analyst_sentiment",
    module: "analyst.py",
    body: "Recent analyst upgrades and downgrades with their price-target changes, plus where the Street stands now: consensus rating, whether it's been improving or deteriorating, and how far apart the price targets are.",
  },
  {
    icon: "🏭",
    name: "get_sector_comparison",
    module: "sector.py",
    body: "Compares the stock's multi-horizon moves against its sector ETF's moves, to separate stock-specific news from a sector-wide drift.",
  },
];

const FAQS = [
  {
    q: "Is this financial advice?",
    a: "No. This is an informational and educational tool that describes recent price action. It does not predict future moves or recommend buying, selling, or holding anything. Always verify important numbers against a primary source and consult a licensed financial advisor before acting.",
  },
  {
    q: "Where does the data come from?",
    a: "Every number comes from a live API call inside one of the MCP tools: Finnhub for live quotes and news (with yfinance fallback), FRED for macro (yfinance ^VIX fallback), and yfinance for history, options chains, analyst consensus, earnings dates, and sector classification. Every tool degrades gracefully — if a source fails, it falls through to the next rather than erroring out the whole query.",
  },
  {
    q: "Why didn't it look at news or options for my query?",
    a: "Because the move didn't clear the significance bar. Every horizon is scored on two axes: a relative ratio against the stock's own realized volatility, and an absolute magnitude floor. A routine 0.5% drift fails both and gets a short, cheap answer — that's a latency and cost optimization, not a coverage gap.",
  },
  {
    q: "Can the AI make up numbers?",
    a: "It's structurally discouraged: the final answer must be delivered through a JSON contract where every number traces back to a real tool result already in the conversation, and price/volatility are computed in plain code before the model is invoked. It can still misread a headline — verify anything you act on.",
  },
  {
    q: "What's the difference between this and a normal chatbot?",
    a: "A general chatbot answers a “why did this stock move” question from stale training data and a confident guess. This app pulls real, current price, volatility, options, and news data before the model reasons about anything, and forces the answer into a contract where every figure is traceable.",
  },
  {
    q: "Does this work for non-US stocks?",
    a: "Best support is US-listed equities and ETFs. Non-US tickers may resolve with sparse or missing data, or not at all — treat results outside US markets as unreliable for now.",
  },
];

const LIMITATIONS = [
  "US-market only. Price, options, news, and macro sources are all oriented around US-listed equities and ETFs; non-US tickers aren't reliably supported and thinly-covered US names may come back with sparse evidence.",
  "No intraday tick data or Level 2 order book. Options positioning and price moves are summarized, not tick-by-tick.",
  "The significance gate means small, “boring” moves intentionally get a shallow investigation. This is a deliberate cost/latency tradeoff, not a coverage gap to fix.",
  "Like any LLM system, outputs can be incomplete, out of date, or simply wrong. Every claim should be checked against a primary source before you act on it.",
];

const ROADMAP = [
  {
    status: "Planned",
    title: "Crypto & FX coverage",
    body: "Extend beyond equities/ETFs to major crypto and FX pairs.",
  },
  {
    status: "Planned",
    title: "Multi-ticker comparisons",
    body: "Ask about two tickers at once (“AAPL vs MSFT this week”) in a single run.",
  },
  {
    status: "In progress",
    title: "Persistent query history",
    body: "Save past investigations across sessions instead of resetting on refresh.",
  },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-primary">
      <span className="size-1.5 rounded-full bg-primary" aria-hidden />
      {children}
    </h2>
  );
}

export default function AboutPage() {
  return (
    <div className="space-y-12">
      {/* ── Under the hood — hero card ─────────────────────────────────── */}
      <section className="elevated rounded-3xl border border-primary/15 bg-gradient-to-br from-accent/60 via-card to-card p-6 sm:p-10">
        <p className="text-xs font-bold uppercase tracking-[0.14em] text-primary">
          Under the Hood
        </p>
        <h1 className="mt-2 text-xl font-bold tracking-tight sm:text-2xl">
          How Agentic Market Explainer works
        </h1>
        <p className="mt-4 max-w-4xl text-[15px] leading-7 text-muted-foreground sm:text-base">
          Every stock move gets a headline. Almost none of them get a real answer. You
          open a chatbot, ask why your position is down 8%, and it gives you a
          plausible-sounding paragraph pulled from training data that&rsquo;s months
          old, with no idea what the price, volume, or news actually did today. We
          built this tool because that isn&rsquo;t good enough for a retail trader
          trying to make a real decision. Agentic Market Explainer pulls the actual
          price, volatility, options activity, and news before it says a single word
          about why a stock moved. It doesn&rsquo;t guess. It looks, and it shows its
          work, so when you read the answer, you know exactly which numbers it came
          from.
        </p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PILLARS.map((p) => (
            <div
              key={p.title}
              className="elevated lift rounded-xl border-0 bg-card p-5"
              style={{ borderTop: "4px solid var(--primary)" }}
            >
              <span className="text-2xl" aria-hidden>
                {p.icon}
              </span>
              <h3 className="mt-3 text-sm font-semibold">{p.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {p.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Pipeline ───────────────────────────────────────────────────── */}
      <section className="space-y-5">
        <SectionLabel>Pipeline</SectionLabel>
        <ol className="space-y-5">
          {PIPELINE.map((step) => (
            <li key={step.title} className="flex gap-4">
              <span className="mt-0.5 text-lg" aria-hidden>
                {step.icon}
              </span>
              <div>
                <h3 className="text-sm font-semibold">{step.title}</h3>
                <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
                  {step.body}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* ── MCP tools ──────────────────────────────────────────────────── */}
      <section className="space-y-5">
        <SectionLabel>MCP Tools</SectionLabel>
        <div className="grid gap-4 sm:grid-cols-2">
          {TOOLS.map((t) => (
            <div key={t.name + t.module} className="elevated lift rounded-xl border-0 bg-card p-5">
              <div className="flex items-center gap-2">
                <span aria-hidden>{t.icon}</span>
                <code className="text-[13px] font-semibold">{t.name}</code>
                <span className="ml-auto rounded-full bg-muted px-2.5 py-0.5 text-[10px] text-muted-foreground">
                  {t.module}
                </span>
              </div>
              <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground">
                {t.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── FAQs ───────────────────────────────────────────────────────── */}
      <section className="space-y-5">
        <SectionLabel>FAQs</SectionLabel>
        <div className="space-y-3">
          {FAQS.map((f) => (
            <details key={f.q} className="group elevated rounded-xl border-0 bg-card px-5 py-4">
              <summary className="cursor-pointer select-none text-sm font-medium marker:text-primary">
                {f.q}
              </summary>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
                {f.a}
              </p>
            </details>
          ))}
        </div>
      </section>

      {/* ── Limitations ────────────────────────────────────────────────── */}
      <section className="space-y-5">
        <SectionLabel>Limitations</SectionLabel>
        <div className="elevated rounded-xl border-0 bg-card p-6">
          <ul className="list-disc space-y-3 pl-5 text-sm leading-relaxed text-muted-foreground">
            {LIMITATIONS.map((l) => (
              <li key={l.slice(0, 24)}>{l}</li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── Roadmap ────────────────────────────────────────────────────── */}
      <section className="space-y-5">
        <SectionLabel>On the Roadmap</SectionLabel>
        <div className="space-y-3">
          {ROADMAP.map((r) => (
            <div key={r.title} className="elevated flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-xl border-0 bg-card px-5 py-4">
              <span
                className={
                  r.status === "In progress"
                    ? "rounded-full border border-primary/30 bg-accent px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-primary"
                    : "rounded-full border bg-muted px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                }
              >
                {r.status}
              </span>
              <h3 className="text-sm font-semibold">{r.title}</h3>
              <p className="w-full pl-0 text-sm text-muted-foreground sm:w-auto sm:flex-1">
                {r.body}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
