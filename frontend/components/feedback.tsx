"use client";

import { createContext, useContext, useMemo, useState } from "react";

export const SUPPORT_URL = "https://buymeacoffee.com/sakthibats";
const FEEDBACK_EMAIL = "hello@market-explainer.com";

export interface FeedbackContext {
  ticker?: string | null;
  sessionId?: string | null;
}

const Ctx = createContext<{
  context: FeedbackContext;
  setContext: (c: FeedbackContext) => void;
}>({ context: {}, setContext: () => {} });

/** Lets the page publish what it's currently showing so the footer's feedback
 *  link can attach it — without threading props through the layout. */
export function FeedbackProvider({ children }: { children: React.ReactNode }) {
  const [context, setContext] = useState<FeedbackContext>({});
  const value = useMemo(() => ({ context, setContext }), [context]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFeedbackContext() {
  return useContext(Ctx);
}

function buildMailto(
  { ticker, sessionId }: FeedbackContext,
  timestamp: string | null,
): string {
  const body = [
    "Hi MarketExplainer Team,",
    "",
    "Type (bug / feedback / suggestion / other): ",
    "",
    "What happened or what would you like to see?: ",
    "",
    "Thanks!",
    "",
    "---",
    ticker ? `Ticker: ${ticker}` : null,
    sessionId ? `Session: ${sessionId}` : null,
    timestamp ? `Time: ${timestamp}` : null,
  ]
    .filter((line) => line !== null)
    .join("\n");

  return `mailto:${FEEDBACK_EMAIL}?subject=${encodeURIComponent(
    "Agentic Market Explainer — Feedback",
  )}&body=${encodeURIComponent(body)}`;
}

/** Plain text link — deliberately no button/pill treatment so it sits quietly
 *  alongside the disclaimer copy. */
export function FeedbackLink() {
  const { context } = useFeedbackContext();

  return (
    <a
      // Rendered href carries no timestamp so server and client markup match.
      // The stamp is applied on click — which is also the moment worth recording.
      href={buildMailto(context, null)}
      onClick={(e) => {
        e.currentTarget.href = buildMailto(context, new Date().toISOString());
      }}
      className="underline-offset-2 transition-colors hover:text-foreground hover:underline"
    >
      Feedback
    </a>
  );
}
