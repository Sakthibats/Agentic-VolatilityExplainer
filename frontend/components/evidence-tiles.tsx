"use client";

import {
  BarChart3,
  Building2,
  CalendarClock,
  Globe2,
  LineChart,
  Newspaper,
  TrendingUp,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Md } from "@/components/md";
import type { Tile } from "@/lib/api";

const AGENT_ICONS: Record<string, typeof LineChart> = {
  price: LineChart,
  news: Newspaper,
  options: TrendingUp,
  macro: Globe2,
  events: CalendarClock,
  analyst: Building2,
  sector: BarChart3,
};

/* Muted purple-grey — the findings are the supporting evidence layer beneath the
   summary and causes, so their accent stays deliberately quieter. */
const FINDINGS_EDGE = "var(--evidence-edge)";

export function EvidenceTiles({ tiles }: { tiles: Tile[] }) {
  if (tiles.length === 0) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {tiles.map((tile) => {
        const Icon = AGENT_ICONS[tile.agent] ?? LineChart;
        return (
          <Card
            key={`${tile.agent}-${tile.title}`}
            className="elevated lift rise-in gap-2 border-0 py-4"
            style={{ borderLeft: `4px solid ${FINDINGS_EDGE}` }}
          >
            <CardHeader className="px-4">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Icon className="size-4 text-primary" aria-hidden />
                {tile.title}
                <Badge variant="secondary" className="ml-auto text-[10px] uppercase">
                  {tile.agent}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 px-4">
              <p className="text-sm leading-relaxed"><Md text={tile.summary} /></p>
              {tile.reasoning && (
                <p className="text-xs italic text-muted-foreground"><Md text={tile.reasoning} /></p>
              )}
              {tile.citations.length > 0 && (
                <p className="flex flex-wrap gap-2 text-xs">
                  {tile.citations.map((c) => (
                    <a
                      key={c.number}
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      [{c.number}] {c.source}
                    </a>
                  ))}
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
