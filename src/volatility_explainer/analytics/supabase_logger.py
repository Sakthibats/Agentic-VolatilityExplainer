"""Best-effort usage logging to Supabase — fire-and-forget, never blocks or breaks
a request. Requires SUPABASE_URL and SUPABASE_KEY in the environment/.env; if either
is missing, logging is silently a no-op (analytics is optional, the app must not
depend on it).
"""

from __future__ import annotations

import threading
from typing import Any

from volatility_explainer.config import get_settings

_TABLE = "query_log"

_client_lock = threading.Lock()
_client: Any = None
_client_checked = False


def _get_client() -> Any:
    global _client, _client_checked
    if _client_checked:
        return _client
    with _client_lock:
        if _client_checked:
            return _client
        _client_checked = True
        settings = get_settings()
        url = settings.supabase_url.get_secret_value()
        key = settings.supabase_key.get_secret_value()
        if url and key:
            from supabase import create_client

            _client = create_client(url, key)
        return _client


def _write(payload: dict) -> None:
    try:
        client = _get_client()
        if client is None:
            return
        client.table(_TABLE).insert(payload).execute()
    except Exception as exc:
        print(f"[analytics] Supabase write FAILED — {exc}")


def log_query_background(
    *,
    anonymous_id: str,
    ticker: str,
    query: str,
    result: dict,
    elapsed_ms: float,
) -> None:
    """Log one investigation run on a background thread so a slow/unavailable
    Supabase never adds latency to the user-facing analysis.
    """
    price_data = (result.get("data") or {}).get("get_price_data") or {}
    citations = [c for tile in result.get("tiles", []) for c in tile.get("citations", [])]

    payload = {
        "anonymous_id": anonymous_id,
        "ticker": ticker,
        "query": query or None,
        "status": result.get("status", "complete"),
        "move_assessment": price_data.get("move_assessment") or None,
        "tools_called": sorted((result.get("data") or {}).keys()) or None,
        "hypotheses": result.get("hypotheses") or None,
        "citations": citations or None,
        "elapsed_ms": round(elapsed_ms),
    }
    threading.Thread(target=_write, args=(payload,), daemon=True).start()
