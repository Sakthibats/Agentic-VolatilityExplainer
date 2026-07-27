"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchHistory, type PricePoint } from "@/lib/api";
import { cn } from "@/lib/utils";

const PERIODS = ["1W", "1M", "6M", "YTD", "1Y"] as const;
type Period = (typeof PERIODS)[number];

const W = 640;
const H = 240;
const PAD = { top: 12, right: 8, bottom: 22, left: 46 };

/* Single-series price line per the dataviz specs: 2px line, recessive dotted grid,
   crosshair + tooltip on hover, no legend (the title names the one series). */
export function PriceChart({ ticker }: { ticker: string }) {
  const [period, setPeriod] = useState<Period>("6M");
  const [points, setPoints] = useState<PricePoint[] | null>(null);
  const [error, setError] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    let cancelled = false;
    setPoints(null);
    setError(false);
    fetchHistory(ticker, period)
      .then((h) => !cancelled && setPoints(h.points))
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [ticker, period]);

  const geom = useMemo(() => {
    if (!points || points.length < 2) return null;
    const closes = points.map((p) => p.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = max - min || 1;
    const x = (i: number) =>
      PAD.left + (i / (points.length - 1)) * (W - PAD.left - PAD.right);
    const y = (v: number) =>
      PAD.top + (1 - (v - min) / span) * (H - PAD.top - PAD.bottom);
    const path = points
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`)
      .join("");
    const area = `${path}L${x(points.length - 1).toFixed(1)},${H - PAD.bottom}L${PAD.left},${H - PAD.bottom}Z`;
    const gridYs = [0.25, 0.5, 0.75].map(
      (f) => PAD.top + f * (H - PAD.top - PAD.bottom),
    );
    const gridVals = [0.25, 0.5, 0.75].map((f) => max - f * span);
    return { x, y, path, area, min, max, gridYs, gridVals };
  }, [points]);

  const onMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!points || !svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * W;
      const frac = (px - PAD.left) / (W - PAD.left - PAD.right);
      const i = Math.round(frac * (points.length - 1));
      setHover(i >= 0 && i < points.length ? i : null);
    },
    [points],
  );

  const up =
    points && points.length >= 2
      ? points[points.length - 1].close >= points[0].close
      : true;
  const changePct =
    points && points.length >= 2
      ? ((points[points.length - 1].close - points[0].close) / points[0].close) * 100
      : null;

  return (
    <section className="space-y-2" aria-label={`${ticker} price chart`}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">
          {ticker} · close price
          {changePct !== null && (
            <span className={cn("numeric ml-2", up ? "text-pos" : "text-neg")}>
              {changePct >= 0 ? "+" : ""}
              {changePct.toFixed(1)}% ({period})
            </span>
          )}
        </h3>
        <div className="flex gap-1" role="group" aria-label="Chart period">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "min-h-8 rounded-lg px-2.5 py-1 text-xs transition-colors",
                p === period
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent active:bg-accent",
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div className="elevated rounded-xl border-0 bg-card p-2">
        {error && (
          <p className="py-16 text-center text-sm text-muted-foreground">
            Chart unavailable
          </p>
        )}
        {!error && !points && (
          <div className="h-[240px] animate-pulse rounded bg-muted" />
        )}
        {!error && points && geom && (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="w-full"
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
            role="img"
            aria-label={`${ticker} closing prices, ${period}`}
          >
            {geom.gridYs.map((gy, i) => (
              <g key={gy}>
                <line
                  x1={PAD.left}
                  x2={W - PAD.right}
                  y1={gy}
                  y2={gy}
                  stroke="var(--chart-grid)"
                  strokeDasharray="2 4"
                />
                <text
                  x={PAD.left - 6}
                  y={gy + 3}
                  textAnchor="end"
                  className="fill-[var(--muted-foreground)] text-[9px]"
                >
                  {geom.gridVals[i].toFixed(0)}
                </text>
              </g>
            ))}
            <path d={geom.area} fill="var(--chart-fill)" />
            <path
              d={geom.path}
              fill="none"
              stroke="var(--chart-line)"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            {hover !== null && points[hover] && (
              <g>
                <line
                  x1={geom.x(hover)}
                  x2={geom.x(hover)}
                  y1={PAD.top}
                  y2={H - PAD.bottom}
                  stroke="var(--muted-foreground)"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                />
                <circle
                  cx={geom.x(hover)}
                  cy={geom.y(points[hover].close)}
                  r="4"
                  fill="var(--chart-line)"
                  stroke="var(--card)"
                  strokeWidth="2"
                />
              </g>
            )}
            <text
              x={PAD.left}
              y={H - 6}
              className="fill-[var(--muted-foreground)] text-[9px]"
            >
              {points[0].date.slice(0, 10)}
            </text>
            <text
              x={W - PAD.right}
              y={H - 6}
              textAnchor="end"
              className="fill-[var(--muted-foreground)] text-[9px]"
            >
              {points[points.length - 1].date.slice(0, 10)}
            </text>
          </svg>
        )}
        {!error && points && hover !== null && points[hover] && (
          <p className="numeric px-2 pb-1 text-xs text-muted-foreground">
            {points[hover].date.replace("T", " ").slice(0, 16)} — $
            {points[hover].close.toFixed(2)}
          </p>
        )}
      </div>
    </section>
  );
}
