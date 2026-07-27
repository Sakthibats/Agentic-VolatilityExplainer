"use client";

import { AlertTriangle, ShieldAlert } from "lucide-react";
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

export default function Home() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [steps, setSteps] = useState<TimelineStep[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [message, setMessage] = useState("");
  const [ticker, setTicker] = useState<string | null>(null);
  const [stats, setStats] = useState<TickerStats | null>(null);
  const [runCount, setRunCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const investigate = useCallback((query: string) => {
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
      query,
      {
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
          if (r.ticker) {
            setTicker(r.ticker);
            fetchStats(r.ticker).then(setStats).catch(() => {});
          }
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

  return (
    <div className="space-y-6">
      <QueryBar onSubmit={investigate} busy={phase === "running"} />

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
        <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
          <div className="space-y-6">
            <InvestigationLog steps={steps} finished={phase === "done"} />
            {result && (
              <>
                {result.summary && (
                  <section className="rise-in space-y-2">
                    <h2 className="text-sm font-semibold tracking-tight">Overall summary</h2>
                    <p className="elevated rounded-xl border-0 bg-card p-4 text-sm leading-relaxed sm:p-5">
                      <Md text={result.summary} />
                    </p>
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
                    <h2 className="text-sm font-semibold tracking-tight">Most likely causes</h2>
                    <Hypotheses hypotheses={result.hypotheses} />
                  </section>
                )}
                {result.tiles.length > 0 && (
                  <section className="space-y-2">
                    <h2 className="text-sm font-semibold tracking-tight">Agent findings</h2>
                    <EvidenceTiles tiles={result.tiles} />
                  </section>
                )}
              </>
            )}
          </div>
          <aside className="space-y-5">
            {ticker && <PriceChart ticker={ticker} />}
            {stats && <StatsPanel title="Snapshot" stats={stats.quick} />}
            {stats && <StatsPanel title="Analyst targets" stats={stats.analyst} />}
          </aside>
        </div>
      )}

      {phase === "idle" && (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          Ask why a stock, ETF, or asset moved — the agent pulls real price and
          volatility data first, then investigates only what the evidence warrants.
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
