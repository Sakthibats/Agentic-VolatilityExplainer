"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

import { useFeedbackContext } from "@/components/feedback";
import type { TimelineStep } from "@/components/timeline";
import {
  analyzeStream,
  fetchStats,
  type AnalysisResult,
  type TickerStats,
} from "@/lib/api";

export type Phase = "idle" | "running" | "done" | "guardrail" | "error";

interface Investigation {
  phase: Phase;
  query: string;
  setQuery: (q: string) => void;
  steps: TimelineStep[];
  /** The write-up as it streams in, before `result` lands. Empty once it has. */
  partialSummary: string;
  result: AnalysisResult | null;
  message: string;
  ticker: string | null;
  stats: TickerStats | null;
  runCount: number;
  investigate: (raw: string) => void;
  stop: () => void;
}

const Ctx = createContext<Investigation | null>(null);

/** Lives in the root layout, not in the page, so switching between Home and
 *  About doesn't unmount the investigation. That also keeps an in-flight SSE
 *  stream alive across navigation — the backend finishes-and-caches either way,
 *  so a run you navigate away from is still waiting when you come back. */
export function InvestigationProvider({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [query, setQuery] = useState("");
  const [steps, setSteps] = useState<TimelineStep[]>([]);
  const [partialSummary, setPartialSummary] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [message, setMessage] = useState("");
  const [ticker, setTicker] = useState<string | null>(null);
  const [stats, setStats] = useState<TickerStats | null>(null);
  const [runCount, setRunCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const { setContext: setFeedbackContext } = useFeedbackContext();

  const investigate = useCallback(
    (raw: string) => {
      setQuery(raw); // keep the search field in sync when a chip triggers the run
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setPhase("running");
      setSteps([]);
      setPartialSummary("");
      setResult(null);
      setStats(null);
      setTicker(null);
      setMessage("");

      analyzeStream(
        raw,
        {
          onStarted: (t, sessionId) => {
            setFeedbackContext({ ticker: t || null, sessionId });
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
          // Cumulative text — replace the buffer rather than appending, so a dropped
          // or reordered event can't corrupt it.
          onSummary: (text) => setPartialSummary(text),
          onResult: (r) => {
            setSteps((prev) => prev.map((s) => ({ ...s, done: true })));
            setPartialSummary(""); // the result's summary is authoritative from here
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
    },
    [setFeedbackContext],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setPhase("idle");
    setSteps([]);
    setPartialSummary("");
    setResult(null);
    setTicker(null);
    setStats(null);
    setFeedbackContext({});
  }, [setFeedbackContext]);

  const value = useMemo(
    () => ({
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
    }),
    [phase, query, steps, partialSummary, result, message, ticker, stats, runCount, investigate, stop],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useInvestigation(): Investigation {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useInvestigation must be used within an InvestigationProvider");
  return ctx;
}
