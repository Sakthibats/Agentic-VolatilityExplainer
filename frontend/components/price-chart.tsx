"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchHistory, type PricePoint } from "@/lib/api";
import { cn } from "@/lib/utils";

const PERIODS = ["1W", "1M", "6M", "YTD", "1Y"] as const;
type Period = (typeof PERIODS)[number];

const H = 200;
const PAD = { top: 12, right: 44, bottom: 22, left: 6 };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* Round y-axis levels to human numbers ($500, $1,000 …), 2-3 of them. */
function niceLevels(min: number, max: number): number[] {
  const span = max - min || 1;
  const rawStep = span / 2.5;
  const mag = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rawStep) ?? mag * 10;
  const levels: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max; v += step) levels.push(v);
  return levels.slice(0, 3);
}

/* Catmull-Rom → cubic bezier for a smooth line through every data point. */
function smoothPath(pts: { x: number; y: number }[]): string {
  if (pts.length < 3) return pts.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join("");
  let d = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[Math.min(pts.length - 1, i + 2)];
    const c1x = p1.x + (p2.x - p0.x) / 10;
    const c1y = p1.y + (p2.y - p0.y) / 10;
    const c2x = p2.x - (p3.x - p1.x) / 10;
    const c2y = p2.y - (p3.y - p1.y) / 10;
    d += `C${c1x.toFixed(1)},${c1y.toFixed(1)},${c2x.toFixed(1)},${c2y.toFixed(1)},${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
  }
  return d;
}

export function PriceChart({ ticker }: { ticker: string }) {
  const [period, setPeriod] = useState<Period>("6M");
  const [points, setPoints] = useState<PricePoint[] | null>(null);
  const [error, setError] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(0);

  // Render the SVG at the container's real pixel width — no scaling, so strokes
  // and text stay crisp on any screen size.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      setW(Math.round(entries[0].contentRect.width));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

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
    if (!points || points.length < 2 || W < 80) return null;
    const closes = points.map((p) => p.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = max - min || 1;
    const x = (i: number) =>
      PAD.left + (i / (points.length - 1)) * (W - PAD.left - PAD.right);
    const y = (v: number) =>
      PAD.top + (1 - (v - min) / span) * (H - PAD.top - PAD.bottom);

    const xy = points.map((p, i) => ({ x: x(i), y: y(p.close) }));
    const line = smoothPath(xy);
    const area = `${line}L${x(points.length - 1).toFixed(1)},${H - PAD.bottom}L${PAD.left},${H - PAD.bottom}Z`;

    const levels = niceLevels(min, max).map((v) => ({ v, y: y(v) }));

    // X ticks: month starts for long ranges, ~3 spaced dates for short ones.
    const monthTicks: { label: string; x: number }[] = [];
    let lastMonth = -1;
    points.forEach((p, i) => {
      const d = new Date(p.date);
      if (d.getMonth() !== lastMonth) {
        lastMonth = d.getMonth();
        if (i > 0) monthTicks.push({ label: MONTHS[d.getMonth()], x: x(i) });
      }
    });
    let xTicks = monthTicks;
    if (monthTicks.length < 2) {
      const idxs = [0.15, 0.5, 0.85].map((f) => Math.round(f * (points.length - 1)));
      xTicks = idxs.map((i) => {
        const d = new Date(points[i].date);
        return { label: `${MONTHS[d.getMonth()]} ${d.getDate()}`, x: x(i) };
      });
    } else if (monthTicks.length > 5) {
      const keep = Math.ceil(monthTicks.length / 5);
      xTicks = monthTicks.filter((_, i) => i % keep === 0);
    }

    return { x, y, line, area, levels, xTicks };
  }, [points, W]);

  const locate = useCallback(
    (clientX: number) => {
      if (!points || !svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      const px = ((clientX - rect.left) / rect.width) * W;
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
  const lineColor = up ? "var(--pos)" : "var(--neg)";
  const changePct =
    points && points.length >= 2
      ? ((points[points.length - 1].close - points[0].close) / points[0].close) * 100
      : null;

  return (
    <section className="space-y-2" aria-label={`${ticker} price chart`}>
      <div className="flex flex-wrap items-center justify-between gap-y-1">
        <h3 className="micro-label">
          {ticker} · Price
          {changePct !== null && (
            <span
              className={cn(
                "numeric ml-2 font-semibold normal-case tracking-normal",
                up ? "text-pos" : "text-neg",
              )}
            >
              {changePct >= 0 ? "+" : ""}
              {changePct.toFixed(1)}%
            </span>
          )}
        </h3>
        <div className="flex gap-0.5" role="group" aria-label="Chart period">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "min-h-8 rounded-lg px-2 py-1 text-xs transition-colors",
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

      <div ref={boxRef}>
        {error && (
          <p className="py-20 text-center text-sm text-muted-foreground">
            Chart unavailable
          </p>
        )}
        {!error && !points && (
          <div className="h-[200px] animate-pulse rounded-xl bg-muted/60" />
        )}
        {!error && points && geom && (
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            width={W}
            height={H}
            className="touch-none"
            onMouseMove={(e) => locate(e.clientX)}
            onTouchMove={(e) => locate(e.touches[0].clientX)}
            onMouseLeave={() => setHover(null)}
            onTouchEnd={() => setHover(null)}
            role="img"
            aria-label={`${ticker} closing prices, ${period}`}
          >
            <defs>
              <linearGradient id="area-fade" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity="0.16" />
                <stop offset="100%" stopColor={lineColor} stopOpacity="0.02" />
              </linearGradient>
            </defs>

            {geom.levels.map((lv) => (
              <g key={lv.v}>
                <line
                  x1={PAD.left}
                  x2={W - PAD.right + 4}
                  y1={lv.y}
                  y2={lv.y}
                  stroke="var(--chart-grid)"
                  strokeWidth="1"
                />
                <text
                  x={W - PAD.right + 8}
                  y={lv.y + 3.5}
                  className="fill-[var(--muted-foreground)] text-[10px] opacity-80"
                >
                  ${lv.v >= 1000 ? `${(lv.v / 1000).toFixed(lv.v % 1000 === 0 ? 0 : 1)}k` : lv.v.toFixed(0)}
                </text>
              </g>
            ))}

            <path key={`a-${ticker}-${period}`} className="fade-late" d={geom.area} fill="url(#area-fade)" />
            <path
              key={`l-${ticker}-${period}`}
              className="draw-line"
              d={geom.line}
              fill="none"
              stroke={lineColor}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {geom.xTicks.map((t) => (
              <text
                key={`${t.label}-${t.x}`}
                x={t.x}
                y={H - 7}
                textAnchor="middle"
                className="fill-[var(--muted-foreground)] text-[10px] opacity-80"
              >
                {t.label}
              </text>
            ))}

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
                  opacity="0.5"
                />
                <circle
                  cx={geom.x(hover)}
                  cy={geom.y(points[hover].close)}
                  r="4"
                  fill={lineColor}
                  stroke="var(--card)"
                  strokeWidth="2"
                />
              </g>
            )}
          </svg>
        )}
        <p className="numeric min-h-5 px-1 pt-1 text-xs text-muted-foreground">
          {!error && points && hover !== null && points[hover]
            ? `${new Date(points[hover].date).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })} — $${points[hover].close.toFixed(2)}`
            : " "}
        </p>
      </div>
    </section>
  );
}
