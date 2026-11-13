"use client";

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";

import { ClaudeIcon, OpenAIIcon } from "@/components/vendor-icons";
import type { LlmProvider, ModelOption } from "@/lib/api";
import {
  DEFAULT_PROVIDER,
  getCatalog,
  getProvider,
  loadCatalog,
  setProvider,
  subscribe,
} from "@/lib/model-choice";
import { cn } from "@/lib/utils";

// Fixed here so the icons render before /v1/models answers; model IDs come from the server.
const VENDORS: { provider: LlmProvider; vendor: string; Icon: typeof OpenAIIcon }[] = [
  { provider: "openai", vendor: "OpenAI", Icon: OpenAIIcon },
  { provider: "anthropic", vendor: "Anthropic", Icon: ClaudeIcon },
];

function reasoningLine(option: ModelOption): string {
  if (!option.available) {
    return option.unavailable_reason === "out_of_credits"
      ? "Out of credits right now"
      : "Not set up on this server";
  }
  return option.reasoning_effort
    ? `Reasoning effort · ${option.reasoning_effort}`
    : "Extended thinking · off";
}

/** The model picker at the left of the query bar: the current vendor's logo opens a menu
 *  listing each vendor with the model this server runs for it. The choice applies to the
 *  next investigation; disabled while one runs, like the input beside it. */
export function ModelPicker({ disabled = false }: { disabled?: boolean }) {
  // The static export renders the default; the saved choice and the server's model list
  // replace it after hydration (useSyncExternalStore does that without a mismatch).
  const provider = useSyncExternalStore(subscribe, getProvider, () => DEFAULT_PROVIDER);
  const catalog = useSyncExternalStore(subscribe, getCatalog, () => null);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => loadCatalog(), []);

  // Close on a click outside or Escape (focus goes back to the trigger).
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const current = VENDORS.find((v) => v.provider === provider) ?? VENDORS[0];
  const currentOption = catalog?.find((o) => o.provider === current.provider);
  const CurrentIcon = current.Icon;
  const menuOpen = open && !disabled;

  return (
    <div ref={rootRef} className="absolute left-1.5 top-1/2 z-10 -translate-y-1/2">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="true"
        aria-expanded={menuOpen}
        aria-controls={menuOpen ? menuId : undefined}
        aria-label={`Reasoning model: ${current.vendor}${currentOption ? ` ${currentOption.model}` : ""}. Change model`}
        title={currentOption ? `${current.vendor} · ${currentOption.model}` : current.vendor}
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 items-center gap-1 rounded-full pl-2.5 pr-1.5 text-primary transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:hover:bg-transparent aria-expanded:bg-accent"
      >
        <CurrentIcon className="size-4" />
        <ChevronDown
          className={cn(
            "size-3.5 text-muted-foreground transition-transform duration-200",
            menuOpen && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {menuOpen && (
        <div
          id={menuId}
          className="absolute left-0 top-full z-30 mt-2.5 w-72 rounded-xl border bg-popover p-1.5 text-popover-foreground shadow-lg"
        >
          <p className="px-2.5 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Reasoning model
          </p>
          <div role="radiogroup" aria-label="Reasoning model for your next investigation">
            {VENDORS.map(({ provider: value, vendor, Icon }) => {
              const option = catalog?.find((o) => o.provider === value);
              const active = value === provider;
              const unavailable = option?.available === false;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  aria-disabled={unavailable || undefined}
                  onClick={() => {
                    if (unavailable) return;
                    setProvider(value);
                    setOpen(false);
                    triggerRef.current?.focus();
                  }}
                  className={cn(
                    "flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none",
                    unavailable && "cursor-not-allowed opacity-50 hover:bg-transparent",
                  )}
                >
                  <Icon
                    className={cn(
                      "mt-0.5 size-4 shrink-0",
                      active ? "text-primary" : "text-muted-foreground",
                    )}
                  />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block text-sm", active ? "font-semibold" : "font-medium")}>
                      {vendor}
                    </span>
                    {option && (
                      <>
                        <span className="block truncate font-mono text-[11px] text-muted-foreground">
                          {option.model}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {reasoningLine(option)}
                        </span>
                      </>
                    )}
                  </span>
                  {active && <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />}
                </button>
              );
            })}
          </div>
          <p className="mx-1 mt-1.5 border-t px-1.5 pb-0.5 pt-1.5 text-[11px] text-muted-foreground">
            Applies to your next investigation.
          </p>
        </div>
      )}
    </div>
  );
}
