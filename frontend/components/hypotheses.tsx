"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Md } from "@/components/md";
import type { Hypothesis } from "@/lib/api";
import { cn } from "@/lib/utils";

/* Confidence is never color-alone: the badge carries the word itself. Badge and
   card edge draw from the same token so they always agree. */
const CONFIDENCE_STYLES: Record<Hypothesis["confidence"], string> = {
  high: "bg-conf-high/15 text-conf-high border-conf-high/35",
  medium: "bg-conf-medium/15 text-conf-medium border-conf-medium/35",
  low: "bg-conf-low/15 text-conf-low border-conf-low/35",
};

const CONFIDENCE_EDGE: Record<Hypothesis["confidence"], string> = {
  high: "var(--conf-high)",
  medium: "var(--conf-medium)",
  low: "var(--conf-low)",
};

export function Hypotheses({ hypotheses }: { hypotheses: Hypothesis[] }) {
  if (hypotheses.length === 0) return null;
  return (
    <div className="space-y-2.5" aria-label="Ranked hypotheses">
      {[...hypotheses]
        .sort((a, b) => a.rank - b.rank)
        .map((h) => (
          <Card key={h.rank} className="elevated rise-in border-0 py-3.5" style={{ borderLeft: `4px solid ${CONFIDENCE_EDGE[h.confidence]}` }}>
            <CardContent className="flex items-start gap-3 px-4">
              <span className="numeric mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
                {h.rank}
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 text-sm font-medium">
                    <Md text={h.hypothesis} />
                  </p>
                  <Badge
                    variant="outline"
                    className={cn(
                      "mt-0.5 shrink-0 whitespace-nowrap text-[10px] capitalize",
                      CONFIDENCE_STYLES[h.confidence],
                    )}
                  >
                    {h.confidence} confidence
                  </Badge>
                </div>
                {h.evidence && (
                  <p className="text-xs text-muted-foreground"><Md text={h.evidence} /></p>
                )}
                {h.caveat && h.caveat !== "N/A" && (
                  <p className="text-xs italic text-muted-foreground">Caveat: <Md text={h.caveat} /></p>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
    </div>
  );
}
