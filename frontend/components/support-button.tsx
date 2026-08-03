"use client";

import { Heart } from "lucide-react";

import { SUPPORT_URL } from "@/components/feedback";

/** Nav icon button: outline heart at rest in the same muted tone as the theme
 *  toggle, filling with the brand accent on hover/focus. CSS tooltip rather
 *  than a tooltip library — no new dependency. */
export function SupportButton() {
  return (
    <a
      href={SUPPORT_URL}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Support this project"
      className="group relative flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-accent hover:text-primary focus-visible:text-primary"
    >
      <Heart className="size-4 transition-all duration-150 group-hover:fill-current group-focus-visible:fill-current" />
      <span
        role="tooltip"
        className="pointer-events-none absolute right-0 top-full z-20 mt-1.5 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs text-popover-foreground opacity-0 shadow-md transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100"
      >
        Support this project
      </span>
    </a>
  );
}
