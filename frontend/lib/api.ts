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
  summary: string;
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

  const dispatch = (name: string, data: string) => {
    const payload = JSON.parse(data);
    if (name === "investigation_started") cb.onStarted?.(payload.ticker, payload.session_id);
    else if (name === "step") cb.onStep?.(payload.label);
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
