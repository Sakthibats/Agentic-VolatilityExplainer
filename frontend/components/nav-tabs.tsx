"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const TABS = [
  { href: "/", label: "Home" },
  { href: "/about", label: "About" },
];

/** Segmented nav whose highlight slides to the active route. The indicator is
 *  measured from the active link rather than assuming equal tab widths, so
 *  labels of any length stay correct. */
export function NavTabs() {
  const pathname = usePathname();
  const activeIndex = Math.max(
    0,
    TABS.findIndex((t) => t.href === pathname),
  );

  const navRef = useRef<HTMLElement>(null);
  const itemRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);
  // Skip the transition on first paint so the pill doesn't slide in from x=0.
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    const el = itemRefs.current[activeIndex];
    if (!el) return;

    const update = () => setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
    update();
    const frame = requestAnimationFrame(() => setAnimate(true));

    const ro = new ResizeObserver(update);
    ro.observe(el);
    if (navRef.current) ro.observe(navRef.current);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
    };
  }, [activeIndex]);

  return (
    <nav
      ref={navRef}
      className="relative ml-auto flex items-center gap-1 rounded-full border bg-card p-1 shadow-sm"
    >
      {indicator && (
        <span
          aria-hidden
          className={cn(
            // A primary-tinted fill plus an inset ring, rather than --accent:
            // in dark, --accent (#1c2b47) sits ~1.03:1 against the nav's --card
            // (#1a2440) and was effectively invisible.
            "absolute bottom-1 top-1 rounded-full bg-primary/12 shadow-sm ring-1 ring-inset ring-primary/25 dark:bg-primary/25 dark:ring-primary/40",
            animate &&
              "transition-[left,width] duration-300 ease-out motion-reduce:transition-none",
          )}
          style={{ left: indicator.left, width: indicator.width }}
        />
      )}
      {TABS.map((tab, i) => (
        <Link
          key={tab.href}
          href={tab.href}
          ref={(el) => {
            itemRefs.current[i] = el;
          }}
          aria-current={i === activeIndex ? "page" : undefined}
          className={cn(
            "relative z-10 rounded-full px-3.5 py-1.5 text-sm transition-colors duration-200",
            i === activeIndex
              ? "font-semibold text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
