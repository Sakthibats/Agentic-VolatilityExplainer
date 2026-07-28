"use client";

import { ArrowRight, Search, Square } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

export function QueryBar({
  onSubmit,
  onStop,
  busy,
}: {
  onSubmit: (query: string) => void;
  onStop: () => void;
  busy: boolean;
}) {
  const [value, setValue] = useState("");

  const submit = (q: string) => {
    const trimmed = q.trim();
    if (!trimmed || busy) return;
    setValue(trimmed);
    onSubmit(trimmed);
  };

  return (
    <form
      className="flex flex-col gap-2 sm:flex-row"
      onSubmit={(e) => {
        e.preventDefault();
        submit(value);
      }}
    >
      <div className="relative flex-1">
        <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Try: TSLA · why did Tesla dip? · what happened to gold? · market down?"
          className="h-12 w-full rounded-full border bg-card pl-10 pr-3 text-base shadow-sm outline-none ring-ring/40 transition-shadow placeholder:text-muted-foreground/70 focus:ring-2 sm:text-sm"
          disabled={busy}
          aria-label="Market question"
          enterKeyHint="search"
        />
      </div>
      {busy ? (
        <Button
          type="button"
          onClick={(e) => {
            // React reuses this DOM node when the ternary swaps Stop→Analyze,
            // flipping it to type=submit before the browser runs the default
            // action — preventDefault stops that phantom form submission.
            e.preventDefault();
            onStop();
          }}
          variant="outline"
          className="h-12 gap-2 rounded-full border-neg/40 px-6 text-base font-medium text-neg transition-all hover:bg-neg/10 hover:text-neg sm:text-sm"
        >
          <Square className="size-3.5 fill-current" aria-hidden />
          Stop
        </Button>
      ) : (
        <Button
          type="submit"
          className="btn-primary-gradient h-12 gap-1.5 rounded-full px-6 text-base font-medium transition-all sm:text-sm"
          disabled={!value.trim()}
        >
          Analyze
          <ArrowRight className="size-4" aria-hidden />
        </Button>
      )}
    </form>
  );
}
