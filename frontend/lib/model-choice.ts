/* Which LLM vendor runs the next investigation. The query-bar picker writes it; investigate()
   reads it when a run starts. Remembered per browser. Only the vendor is chosen here: the
   backend decides which model each vendor runs, and reports it through GET /v1/models. */

import { fetchModels, type LlmProvider, type ModelOption } from "@/lib/api";

export const DEFAULT_PROVIDER: LlmProvider = "openai";

const KEY = "volx_llm_provider";
const listeners = new Set<() => void>();
let catalog: ModelOption[] | null = null;
let catalogRequested = false;

function notify(): void {
  listeners.forEach((listener) => listener());
}

/** The saved choice, or the default. If the server reports that vendor as unavailable (no
 *  API key), the other one instead. That fallback isn't saved, so the saved choice comes
 *  back once the server is configured. */
export function getProvider(): LlmProvider {
  const saved = localStorage.getItem(KEY);
  const chosen = saved === "openai" || saved === "anthropic" ? saved : DEFAULT_PROVIDER;
  if (catalog?.some((o) => o.provider === chosen && !o.available)) {
    return catalog.find((o) => o.available)?.provider ?? chosen;
  }
  return chosen;
}

export function setProvider(provider: LlmProvider): void {
  localStorage.setItem(KEY, provider);
  notify();
}

/** The server's model list, or null until it loads (or forever, from a backend older than
 *  /v1/models; the picker then works without model names). */
export function getCatalog(): ModelOption[] | null {
  return catalog;
}

/** Fetches the model list once per page load, however many pickers are mounted. */
export function loadCatalog(): void {
  if (catalogRequested) return;
  catalogRequested = true;
  fetchModels()
    .then((options) => {
      catalog = options;
      notify();
    })
    .catch(() => {});
}

/** For useSyncExternalStore: every mounted picker re-renders on a change. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
