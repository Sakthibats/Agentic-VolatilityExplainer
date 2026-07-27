"use client";

import { Search } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

const EXAMPLES = [
  "why did TSLA drop today?",
  "what happened to gold?",
  "is NVDA overvalued?",
  "why is the market down?",
];

export function QueryBar({
  onSubmit,
  busy,
}: {
  onSubmit: (query: string) => void;
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
    <div className="space-y-3">
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
            placeholder='Ask about any stock, ETF, or asset…'
            className="h-12 w-full rounded-xl border bg-card pl-10 pr-3 text-base shadow-sm outline-none ring-ring/40 transition-shadow placeholder:text-muted-foreground focus:ring-2 sm:text-sm"
            disabled={busy}
            aria-label="Market question"
            enterKeyHint="search"
          />
        </div>
        <Button
          type="submit"
          className="h-12 rounded-xl px-6 text-base font-medium shadow-sm transition-all sm:text-sm"
          disabled={busy || !value.trim()}
        >
          {busy ? "Investigating…" : "Investigate"}
        </Button>
      </form>
      <div className="flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => submit(ex)}
            disabled={busy}
            className="min-h-9 shrink-0 rounded-full border bg-accent px-3.5 py-1.5 text-xs text-accent-foreground transition-colors hover:border-primary active:bg-primary active:text-primary-foreground disabled:opacity-50"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
