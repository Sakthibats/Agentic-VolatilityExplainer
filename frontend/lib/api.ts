/* API client for the FastAPI backend — mirrors backend/volatility_explainer/api/schemas.py.
   That file is the source of truth; keep these types in sync with it. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export interface Citation {
  number: number;
  source: string;
  url: string;
}

export interface Tile {
  agent: string;
  title: string;
  summary: string;
  reasoning: string;
  citations: Citation[];
}

export interface Hypothesis {
  rank: number;
  hypothesis: string;
  evidence: string;
  confidence: "high" | "medium" | "low";
  caveat: string;
}

export interface AnalysisResult {
  ticker: string | null;
  query: string;
  status: "complete" | "incomplete" | "guardrail" | "error";
  /** "What happened" — computed in code from the price data. */
  overview: string;
  /** "Why" — the model's explanation, written after its hypotheses. */
  summary: string;
  /** Sources cited in `summary`: a `[n]` marker there is the citation with that number. */
  citations: Citation[];
  tiles: Tile[];
  hypotheses: Hypothesis[];
  cache_hits: string[];
  error_message: string;
}

export interface PricePoint {
  date: string;
  close: number;
}

export interface PriceHistory {
  ticker: string;
  period: string;
  points: PricePoint[];
}

export interface Stat {
  label: string;
  value: string;
  delta: string | null;
}

export interface TickerStats {
  ticker: string;
  quick: Stat[];
  analyst: Stat[];
}

export interface AnalyzeCallbacks {
  onStarted?: (ticker: string, sessionId: string) => void;
  onStep?: (label: string) => void;
  /** The deterministic "what happened" paragraph, sent once right after the price fetch. */
  onOverview?: (text: string) => void;
  /** The "why" paragraph as written so far. CUMULATIVE, not a delta — replace, don't append.
   *  Always superseded by the `summary` on the final result. */
  onSummary?: (text: string) => void;
  onResult?: (result: AnalysisResult) => void;
  onGuardrail?: (message: string) => void;
  onError?: (message: string) => void;
}

function sessionId(): string {
  const key = "volx_session_id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}

/* POST /v1/analyze streams SSE; EventSource can't POST, so parse the fetch body stream. */
export async function analyzeStream(
  query: string,
  cb: AnalyzeCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/v1/analyze`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-session-id": sessionId(),
    },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!res.ok || !res.body) {
    cb.onError?.(`Request failed (${res.status})`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "";
  let terminated = false;

  const dispatch = (name: string, data: string) => {
    const payload = JSON.parse(data);
    if (name === "result" || name === "guardrail" || name === "error") terminated = true;
    if (name === "investigation_started") cb.onStarted?.(payload.ticker, payload.session_id);
    else if (name === "step") cb.onStep?.(payload.label);
    else if (name === "overview") cb.onOverview?.(payload.text);
    else if (name === "summary") cb.onSummary?.(payload.text);
    else if (name === "result") cb.onResult?.(payload as AnalysisResult);
    else if (name === "guardrail") cb.onGuardrail?.(payload.message);
    else if (name === "error") cb.onError?.(payload.message);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).trimEnd();
      buffer = buffer.slice(idx + 1);
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      else if (line.startsWith("data:") && eventName) {
        dispatch(eventName, line.slice(5).trim());
        eventName = "";
      }
    }
  }

  // The stream can close cleanly with no terminal event — a backend restart (uvicorn
  // --reload) or crash mid-run. Without this the caller never leaves its running state
  // and the query bar stays locked.
  if (!terminated && !signal?.aborted) {
    cb.onError?.("The connection closed before the investigation finished. Please try again.");
  }
}

export async function fetchHistory(
  ticker: string,
  period: string,
): Promise<PriceHistory> {
  const res = await fetch(
    `${API_BASE}/v1/tickers/${encodeURIComponent(ticker)}/history?period=${period}`,
  );
  if (!res.ok) throw new Error(`history ${res.status}`);
  return res.json();
}

export async function fetchStats(ticker: string): Promise<TickerStats> {
  const res = await fetch(
    `${API_BASE}/v1/tickers/${encodeURIComponent(ticker)}/stats`,
  );
  if (!res.ok) throw new Error(`stats ${res.status}`);
  return res.json();
}
