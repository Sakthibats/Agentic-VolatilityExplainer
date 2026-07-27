import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About — Agentic Market Explainer",
};

const PIPELINE = [
  {
    title: "1. Pull price & volatility — always, no LLM call",
    body: "Every query starts the same way: latest price, multi-horizon % change, and realized volatility are fetched deterministically in code, before the LLM is ever invoked.",
  },
  {
    title: "2. Statistical significance gate",
    body: "Only if the move exceeds roughly 2× the stock's own realized volatility does the app fan out further. A normal 1% drift on a high-beta name doesn't trigger the same investigation as a genuine outlier.",
  },
  {
    title: "3. Parallel evidence fan-out",
    body: "News and options data are fetched in parallel and spliced into the conversation as if the model had called them itself — zero extra LLM round trips for this step.",
  },
  {
    title: "4. The LLM decides what else is needed",
    body: "A tool-use loop (Claude Haiku, max 7 turns) reasons about whether anything conditional is still missing — macro context, sector comparison, earnings/FOMC proximity — and calls only the tools that are genuinely relevant.",
  },
  {
    title: "5. Synthesize, with a hard grounding rule",
    body: "The model returns a single JSON contract: ranked hypotheses, confidence levels, and citations. Every number must trace back to a real tool result. Missing data says “Data unavailable” instead of being invented.",
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

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-10">
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          An investigation, not a <span className="text-primary">chatbot guess</span>
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Ask &ldquo;why is TSLA down today&rdquo; and the agent pulls real price and
          volatility numbers first, decides for itself whether the move is statistically
          unusual, then fans out to news, options, macro, or upcoming catalysts only when
          the evidence warrants it — returning ranked hypotheses with confidence levels,
          every number traceable to a real source.
        </p>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">How a query flows</h2>
        <ol className="space-y-4">
          {PIPELINE.map((step) => (
            <li key={step.title} className="rounded-lg border bg-card p-4">
              <h3 className="text-sm font-semibold text-primary">{step.title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                {step.body}
              </p>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">FAQ</h2>
        <div className="space-y-4">
          {FAQS.map((f) => (
            <details key={f.q} className="group rounded-lg border bg-card p-4">
              <summary className="cursor-pointer text-sm font-medium marker:text-primary">
                {f.q}
              </summary>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Known limitations</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>US-market only — non-US tickers aren&apos;t reliably supported.</li>
          <li>No intraday tick data or Level 2 order book.</li>
          <li>Small, &ldquo;boring&rdquo; moves intentionally get a shallow investigation.</li>
          <li>Like any LLM system, outputs can be incomplete or wrong — verify before acting.</li>
        </ul>
      </section>
    </div>
  );
}
