"""The pooled httpx client shared by the upstream API clients (finnhub.py, fred.py)."""

from __future__ import annotations

from functools import lru_cache

import httpx


@lru_cache(maxsize=4)
def shared_client(timeout: float) -> httpx.Client:
    """One persistent client per timeout — connection pooling/keep-alive across calls
    instead of a fresh TCP+TLS handshake per request. Never closed; lives for the process.
    """
    return httpx.Client(timeout=timeout)
