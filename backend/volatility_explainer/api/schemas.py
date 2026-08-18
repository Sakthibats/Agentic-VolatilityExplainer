"""The /v1 API contract — request bodies, the analysis result, and SSE event payloads.

This module is the source of truth for what clients receive. The SSE stream from
POST /v1/analyze emits, in order:

    investigation_started  → InvestigationStarted
    step (0..n times)      → Step
    summary (0..n times)   → SummaryProgress               (interleaved with the last step)
    result | guardrail     → AnalysisResult | Guardrail   (exactly one, terminal)
    error                  → ApiError                      (terminal, on failure)

The non-streaming variant (?stream=false) returns AnalysisResult directly, with
status "guardrail" carrying the guardrail message in error_message.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="Free-form question or ticker")


class Citation(BaseModel):
    number: int
    source: str
    url: str


class Tile(BaseModel):
    agent: str
    title: str
    summary: str
    reasoning: str = ""
    citations: list[Citation] = []


class Hypothesis(BaseModel):
    rank: int
    hypothesis: str
    evidence: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    caveat: str = ""


class AnalysisResult(BaseModel):
    ticker: str | None
    query: str
    status: Literal["complete", "incomplete", "guardrail", "error"]
    summary: str = ""
    tiles: list[Tile] = []
    hypotheses: list[Hypothesis] = []
    cache_hits: list[str] = []
    error_message: str = ""


# ── SSE event payloads ───────────────────────────────────────────────────────


class InvestigationStarted(BaseModel):
    ticker: str
    query: str
    session_id: str


class Step(BaseModel):
    label: str


class SummaryProgress(BaseModel):
    """The analysis summary as generated so far, emitted while the model writes it.

    `text` is CUMULATIVE, not a delta — each event carries the whole summary up to that
    point, so a client replaces its buffer rather than appending. That makes a dropped or
    out-of-order event harmless. Always superseded by the `summary` on the final
    AnalysisResult, which is the authoritative text.
    """

    text: str


class Guardrail(BaseModel):
    message: str


class ApiError(BaseModel):
    message: str
    retryable: bool = True


# ── Ticker snapshot endpoints ────────────────────────────────────────────────


class PricePoint(BaseModel):
    date: str  # ISO 8601
    close: float


class PriceHistory(BaseModel):
    ticker: str
    period: str
    points: list[PricePoint]


class Stat(BaseModel):
    label: str
    value: str
    delta: str | None = None


class TickerStats(BaseModel):
    ticker: str
    quick: list[Stat]
    analyst: list[Stat]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
