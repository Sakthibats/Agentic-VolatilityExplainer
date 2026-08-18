"use client";

import {
  AlertTriangle,
  LineChart as LineChartIcon,
  Search as SearchIcon,
  ShieldAlert,
} from "lucide-react";
import { EvidenceTiles } from "@/components/evidence-tiles";
import { Md } from "@/components/md";
import { Hypotheses } from "@/components/hypotheses";
import { useInvestigation } from "@/components/investigation-provider";
import { PriceChart } from "@/components/price-chart";
import { QueryBar } from "@/components/query-bar";
import { StatsPanel } from "@/components/stats-panel";
import { InvestigationLog } from "@/components/timeline";

const EXAMPLES = [
  "why did TSLA drop today?",
  "what happened to gold?",
  "is NVDA overvalued?",
  "why is the market down?",
];

export default function Home() {
  // State lives in the root layout so navigating to /about and back doesn't
  // discard the investigation — see components/investigation-provider.tsx.
  const {
    phase,
    query,
    setQuery,
    steps,
    partialSummary,
    result,
    message,
    ticker,
    stats,
    runCount,
    investigate,
    stop,
  } = useInvestigation();

  const liveStatus =
    phase === "running"
      ? `Investigating${ticker ? ` ${ticker}` : ""}…`
      : phase === "done"
        ? `Investigation complete. ${result?.hypotheses.length ?? 0} likely causes found.`
        : phase === "guardrail"
          ? "Query out of scope."
          : phase === "error"
            ? "Investigation failed."
            : "";

  return (
    <div className="space-y-6">
      <p className="sr-only" role="status" aria-live="polite">
        {liveStatus}
      </p>
      <QueryBar
        value={query}
        onChange={setQuery}
        onSubmit={investigate}
        onStop={stop}
        busy={phase === "running"}
      />

      {phase === "guardrail" && (
        <div className="flex items-start gap-3 rounded-lg border bg-accent p-4 text-sm text-accent-foreground">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>{message}</p>
        </div>
      )}

      {phase === "error" && (
        <div className="flex items-start gap-3 rounded-lg border border-neg/40 bg-neg/5 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-neg" aria-hidden />
          <p>Something went wrong: {message}</p>
        </div>
      )}

      {(phase === "running" || phase === "done") && (
        <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
          <div className="stagger space-y-6">
            <div className="flex items-start gap-3">
              {ticker && (
                <span className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-primary/25 bg-accent px-3.5 text-xs font-semibold text-primary">
                  ▲ {ticker}
                </span>
              )}
              <div className="min-w-0 flex-1">
                <InvestigationLog steps={steps} finished={phase === "done"} />
              </div>
            </div>
            {/* One card for both states, so the streaming text is replaced in place by
                the final summary rather than the card unmounting and remounting. */}
            {(result?.summary || partialSummary) && (
              <section className="rise-in space-y-2">
                <h2 className="micro-label">Overall Summary</h2>
                <div className="elevated rounded-xl border-0 bg-card p-5 sm:p-6" style={{ borderLeft: "4px solid var(--primary)" }}>
                  <h3 className="mb-2 text-sm font-semibold tracking-tight">
                    {ticker ? `${ticker} — Price Movement Analysis` : "Price Movement Analysis"}
                  </h3>
                  <p className="text-[15px] leading-7 sm:text-base">
                    {result?.summary ? (
                      <Md text={result.summary} />
                    ) : (
                      <>
                        {/* Plain text while streaming — mid-sentence markdown has
                            unbalanced ** and would render as literal asterisks. */}
                        {partialSummary}
                        <span
                          className="ml-0.5 inline-block h-4 w-px animate-pulse bg-primary align-middle"
                          aria-hidden
                        />
                      </>
                    )}
                  </p>
                </div>
              </section>
            )}
            {result && (
              <>
                {result.status === "incomplete" && (
                  <p className="text-xs text-muted-foreground">
                    The investigation hit its turn limit before a full write-up —
                    the evidence gathered so far is shown below.
                  </p>
                )}
                {result.hypotheses.length > 0 && (
                  <section className="space-y-2">
                    <h2 className="micro-label">Most Likely Causes</h2>
                    <Hypotheses hypotheses={result.hypotheses} />
                  </section>
                )}
                {result.tiles.length > 0 && (
                  <section className="space-y-2">
                    <h2 className="micro-label">Agent Findings</h2>
                    <EvidenceTiles tiles={result.tiles} />
                  </section>
                )}
              </>
            )}
          </div>
          <aside className="stagger space-y-5">
            {ticker && <PriceChart ticker={ticker} />}
            {stats && <StatsPanel title="Snapshot" stats={stats.quick} />}
            {stats && <StatsPanel title="Analyst targets" stats={stats.analyst} />}
          </aside>
        </div>
      )}

      {phase === "idle" && (
        <div className="grid items-stretch gap-6 lg:grid-cols-[1fr_400px]">
          <section className="flex flex-col space-y-2">
            <h2 className="micro-label">Analysis</h2>
            <div className="elevated flex min-h-[210px] flex-1 flex-col items-center justify-center gap-2.5 rounded-2xl border-0 bg-card p-6 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-accent">
                <SearchIcon className="size-5 text-primary/70" aria-hidden />
              </div>
              <p className="text-sm font-medium text-muted-foreground">
                Start an investigation
              </p>
              <p className="max-w-sm text-sm text-muted-foreground">
                The agent pulls real price and volatility data first, then investigates
                what the evidence warrants.
              </p>
              <div className="mt-1 grid w-full max-w-md grid-cols-1 gap-2 sm:grid-cols-2">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => investigate(ex)}
                    className="min-h-9 rounded-full border bg-background px-3.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary active:bg-accent"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </section>
          <section className="flex flex-col space-y-2">
            <h2 className="micro-label">Price</h2>
            <div className="elevated flex min-h-[210px] flex-1 flex-col items-center justify-center gap-2.5 rounded-2xl border-0 bg-card p-6 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-accent">
                <LineChartIcon className="size-5 text-primary/70" aria-hidden />
              </div>
              <p className="text-sm font-medium text-muted-foreground">Price chart</p>
              <p className="max-w-[220px] text-sm text-muted-foreground">
                Chart and stats appear once you analyze a ticker.
              </p>
            </div>
          </section>
        </div>
      )}

      {runCount > 0 && (
        <p className="text-right text-[11px] text-muted-foreground">
          {runCount} {runCount === 1 ? "analysis" : "analyses"} this session
        </p>
      )}
    </div>
  );
}
