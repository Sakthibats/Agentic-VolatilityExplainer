"use client";

import type { Stat } from "@/lib/api";
import { cn } from "@/lib/utils";

/* Stat tiles: small muted label, prominent tabular value, signed delta in status
   color (sign + color together — never color alone). */
function StatTile({ stat }: { stat: Stat }) {
  const negative = stat.delta?.trim().startsWith("-");
  return (
    <div className="elevated lift rounded-xl border-0 bg-card px-3.5 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{stat.label}</p>
      <p className="numeric text-base font-semibold">
        {stat.value}
        {stat.delta && (
          <span className={cn("numeric ml-2 text-xs font-medium", negative ? "text-neg" : "text-pos")}>
            {stat.delta}
          </span>
        )}
      </p>
    </div>
  );
}

export function StatsPanel({ title, stats }: { title: string; stats: Stat[] }) {
  const real = stats.filter((s) => s.value !== "Unavailable");
  if (real.length === 0) return null;
  return (
    <section aria-label={title} className="space-y-2">
      <h3 className="micro-label">{title}</h3>
      <div className="grid grid-cols-2 gap-2">
        {real.map((s) => (
          <StatTile key={s.label} stat={s} />
        ))}
      </div>
    </section>
  );
}
