"use client";

import {
  AlertTriangle,
  LineChart as LineChartIcon,
  Search as SearchIcon,
  ShieldAlert,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { EvidenceTiles } from "@/components/evidence-tiles";
import { Md } from "@/components/md";
import { Hypotheses } from "@/components/hypotheses";
import { PriceChart } from "@/components/price-chart";
import { QueryBar } from "@/components/query-bar";
import { StatsPanel } from "@/components/stats-panel";
import { InvestigationLog, type TimelineStep } from "@/components/timeline";
import {
  analyzeStream,
  fetchStats,
  type AnalysisResult,
  type TickerStats,
} from "@/lib/api";

type Phase = "idle" | "running" | "done" | "guardrail" | "error";

const EXAMPLES = [
  "why did TSLA drop today?",
  "what happened to gold?",
  "is NVDA overvalued?",
  "why is the market down?",
];

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [query, setQuery] = useState("");
  const [steps, setSteps] = useState<TimelineStep[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [message, setMessage] = useState("");
  const [ticker, setTicker] = useState<string | null>(null);
  const [stats, setStats] = useState<TickerStats | null>(null);
  const [runCount, setRunCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const investigate = useCallback((raw: string) => {
    setQuery(raw); // keep the search field in sync when a chip triggers the run
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setPhase("running");
    setSteps([]);
    setResult(null);
    setStats(null);
    setTicker(null);
    setMessage("");

    analyzeStream(
      raw,
      {
        onStarted: (t) => {
          if (t) {
            setTicker(t);
            fetchStats(t).then(setStats).catch(() => {});
          }
        },
        onStep: (label) =>
          setSteps((prev) => [
            ...prev.map((s) => ({ ...s, done: true })),
            { label, done: false },
          ]),
        onResult: (r) => {
          setSteps((prev) => prev.map((s) => ({ ...s, done: true })));
          setResult(r);
          setPhase("done");
          setRunCount((n) => n + 1);
        },
        onGuardrail: (msg) => {
          setMessage(msg.replace(/\*\*/g, "").replace(/\*/g, ""));
          setPhase("guardrail");
        },
        onError: (msg) => {
          setMessage(msg);
          setPhase("error");
        },
      },
      controller.signal,
    ).catch((err) => {
      if (controller.signal.aborted) return;
      setMessage(String(err));
      setPhase("error");
    });
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setPhase("idle");
    setSteps([]);
    setResult(null);
    setTicker(null);
    setStats(null);
  }, []);

  return (
    <div className="space-y-6">
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
            {result && (
              <>
                {result.summary && (
                  <section className="rise-in space-y-2">
                    <h2 className="micro-label">Overall Summary</h2>
                    <div className="elevated rounded-xl border-0 bg-card p-5 sm:p-6" style={{ borderLeft: "4px solid var(--primary)" }}>
                      <h3 className="mb-2 text-sm font-semibold tracking-tight">
                        {ticker ? `${ticker} — Price Movement Analysis` : "Price Movement Analysis"}
                      </h3>
                      <p className="text-[15px] leading-7 sm:text-base">
                        <Md text={result.summary} />
                      </p>
                    </div>
                  </section>
                )}
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
        <div className="grid gap-6 lg:grid-cols-[1fr_400px]">
          <section className="space-y-2">
            <h2 className="micro-label">Analysis</h2>
            <div className="elevated flex min-h-[380px] flex-col items-center justify-center gap-3 rounded-2xl border-0 bg-card p-8 text-center">
              <div className="flex size-14 items-center justify-center rounded-full bg-accent">
                <SearchIcon className="size-6 text-primary/60" aria-hidden />
              </div>
              <p className="text-sm font-medium text-muted-foreground">
                Start an investigation
              </p>
              <p className="max-w-sm text-sm text-muted-foreground/80">
                Enter a ticker, company name, or ask a question — the agent pulls real
                price and volatility data first, then investigates what the evidence
                warrants.
              </p>
              <div className="mt-2 flex flex-wrap justify-center gap-2">
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
          <section className="space-y-2">
            <h2 className="micro-label">Price</h2>
            <div className="elevated flex min-h-[380px] flex-col items-center justify-center gap-3 rounded-2xl border-0 bg-card p-8 text-center">
              <div className="flex size-14 items-center justify-center rounded-full bg-accent">
                <LineChartIcon className="size-6 text-primary/60" aria-hidden />
              </div>
              <p className="text-sm font-medium text-muted-foreground">Price chart</p>
              <p className="max-w-[220px] text-sm text-muted-foreground/80">
                Chart and stats will appear once you analyze a ticker.
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
