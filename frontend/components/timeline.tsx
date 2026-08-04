"use client";

import { Check, ChevronDown, Loader2 } from "lucide-react";

export interface TimelineStep {
  label: string;
  done: boolean;
}

function Steps({ steps }: { steps: TimelineStep[] }) {
  return (
    <ol className="space-y-2.5" aria-label="Investigation progress">
      {steps.map((step, i) => (
        <li key={i} className="rise-in flex items-center gap-2.5 text-sm">
          {step.done ? (
            <Check className="size-4 shrink-0 text-pos" aria-hidden />
          ) : (
            <Loader2 className="size-4 shrink-0 animate-spin text-primary" aria-hidden />
          )}
          <span className={step.done ? "text-muted-foreground" : "text-foreground"}>
            {step.label}
          </span>
        </li>
      ))}
    </ol>
  );
}

/* Live: steps render in the open. Finished: the log collapses into a summary row
   so the results own the page — expandable for anyone curious about the trail. */
export function InvestigationLog({
  steps,
  finished,
}: {
  steps: TimelineStep[];
  finished: boolean;
}) {
  if (steps.length === 0) return null;

  if (!finished) {
    return (
      <div className="elevated rounded-xl border bg-card p-4">
        <Steps steps={steps} />
      </div>
    );
  }

  return (
    <details className="group rounded-xl border bg-muted/50 transition-colors open:bg-card">
      <summary className="flex min-h-11 cursor-pointer select-none items-center gap-2 px-4 py-2.5 text-xs text-muted-foreground [&::-webkit-details-marker]:hidden">
        <Check className="size-3.5 text-pos" aria-hidden />
        Investigation complete · {steps.length} steps
        <ChevronDown
          className="ml-auto size-3.5 transition-transform group-open:rotate-180"
          aria-hidden
        />
      </summary>
      <div className="px-4 pb-3">
        <Steps steps={steps} />
      </div>
    </details>
  );
}
