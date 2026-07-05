"""Best-effort usage logging to Supabase — fire-and-forget, never blocks or breaks
a request. Requires SUPABASE_URL and SUPABASE_KEY in the environment/.env; if either
is missing, logging is silently a no-op (analytics is optional, the app must not
depend on it).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volatility_explainer.config import get_settings

_TABLE = "query_log"
_RETRY_DELAY_SECONDS = 1.5
_FALLBACK_LOG_PATH = Path(__file__).parents[3] / "data" / "failed_query_log.jsonl"

_logger = logging.getLogger(__name__)

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


def _fallback_write(payload: dict) -> None:
    """Last-resort durability: append the payload locally so a failed row can be
    replayed later instead of silently vanishing. Note this lives in the container's
    filesystem, so it only survives restarts if the data/ dir is volume-mounted.
    """
    try:
        _FALLBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {"logged_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        with _FALLBACK_LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        _logger.exception("[analytics] Also failed to write local fallback log")


def _write(payload: dict) -> None:
    client = _get_client()
    if client is None:
        return

    for attempt in (1, 2):
        try:
            client.table(_TABLE).insert(payload).execute()
            return
        except Exception:
            if attempt == 1:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            _logger.exception("[analytics] Supabase write failed after retry, payload=%r", payload)
            _fallback_write(payload)


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
