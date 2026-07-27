"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Md } from "@/components/md";
import type { Hypothesis } from "@/lib/api";
import { cn } from "@/lib/utils";

/* Confidence is never color-alone: the badge carries the word itself. */
const CONFIDENCE_STYLES: Record<Hypothesis["confidence"], string> = {
  high: "bg-pos/15 text-pos border-pos/30",
  medium: "bg-primary/10 text-primary border-primary/30",
  low: "bg-muted text-muted-foreground border-border",
};

export function Hypotheses({ hypotheses }: { hypotheses: Hypothesis[] }) {
  if (hypotheses.length === 0) return null;
  return (
    <div className="space-y-2.5" aria-label="Ranked hypotheses">
      {[...hypotheses]
        .sort((a, b) => a.rank - b.rank)
        .map((h) => (
          <Card key={h.rank} className="elevated rise-in border-0 py-3.5">
            <CardContent className="flex items-start gap-3 px-4">
              <span className="numeric mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
                {h.rank}
              </span>
              <div className="min-w-0 space-y-1">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                  <Md text={h.hypothesis} />
                  <Badge
                    variant="outline"
                    className={cn("text-[10px] capitalize", CONFIDENCE_STYLES[h.confidence])}
                  >
                    {h.confidence} confidence
                  </Badge>
                </p>
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
