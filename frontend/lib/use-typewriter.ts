"use client";

import { useEffect, useRef, useState } from "react";

/** Characters per second when the reveal is keeping up with the text. */
const BASE_CPS = 120;
/** When further behind, reveal this fraction of the backlog per second on top — so a burst
 *  from the stream (or a whole cached answer) is swept in quickly instead of lagging. */
const CATCH_UP_PER_SEC = 1.5;

/** Reveal `target` progressively, like text being written, and return the visible part.
 *
 *  The server's text arrives unevenly: the overview as one event, the explanation in bursts
 *  of partial JSON, a cached answer all at once. Pacing the reveal on the client makes all
 *  three read the same way. `target` is expected to grow by extension (cumulative SSE text);
 *  any other change restarts the reveal from the beginning.
 *
 *  Text already present on mount is shown in full — coming back from /about shouldn't replay
 *  a finished write-up. `paused` holds the reveal where it is (e.g. until a preceding
 *  paragraph has finished). Users who prefer reduced motion get the text immediately.
 */
export function useTypewriter(target: string, { paused = false }: { paused?: boolean } = {}) {
  const [shown, setShown] = useState(target);
  const visible = target.startsWith(shown) ? shown : "";
  const lastFrame = useRef<number | null>(null);

  useEffect(() => {
    if (paused || visible.length >= target.length) {
      lastFrame.current = null;
      return;
    }
    // One frame per effect run: each reveal step changes `visible`, which schedules the next.
    const id = requestAnimationFrame((now) => {
      const elapsed = lastFrame.current === null ? 16 : Math.min(now - lastFrame.current, 100);
      lastFrame.current = now;
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setShown(target);
        return;
      }
      const backlog = target.length - visible.length;
      const rate = Math.max(BASE_CPS, backlog * CATCH_UP_PER_SEC);
      const step = Math.max(1, Math.round((rate * elapsed) / 1000));
      setShown(target.slice(0, visible.length + step));
    });
    return () => cancelAnimationFrame(id);
  }, [target, visible, paused]);

  return visible;
}
