"""Best-effort usage logging to Supabase — fire-and-forget, never blocks or breaks
a request. Requires SUPABASE_URL and SUPABASE_KEY in the environment/.env; if either
is missing, logging is silently a no-op (analytics is optional, the app must not
depend on it).

Writes go through a single background worker fed by a bounded queue, so a burst of
concurrent queries can't spawn unbounded threads or hammer Supabase in parallel.
Rows that fail to insert are appended to a local fallback file and opportunistically
replayed on the next successful write, so a transient outage self-heals instead of
losing rows for good.
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volatility_explainer.config import get_settings

_TABLE = "query_log"
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.5
_CLIENT_RETRY_COOLDOWN_SECONDS = 60
_QUEUE_MAXSIZE = 500
_ATEXIT_FLUSH_SECONDS = 2.0
_FALLBACK_LOG_PATH = Path(__file__).parents[3] / "data" / "failed_query_log.jsonl"

_logger = logging.getLogger(__name__)

_client: Any = None
_client_init_failed_at: float | None = None

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)
_worker_started = False
_worker_lock = threading.Lock()
_fallback_lock = threading.Lock()


def _creds() -> tuple[str, str] | None:
    settings = get_settings()
    url = settings.supabase_url.get_secret_value()
    key = settings.supabase_key.get_secret_value()
    return (url, key) if url and key else None


def _get_client(url: str, key: str) -> Any:
    """Create (or reuse) the Supabase client. A failed construction is retried
    after a cooldown rather than disabling analytics for the rest of the
    process's life — a transient DNS/network hiccup at cold start shouldn't
    silently kill logging forever.
    """
    global _client, _client_init_failed_at
    if _client is not None:
        return _client
    if (
        _client_init_failed_at is not None
        and time.monotonic() - _client_init_failed_at < _CLIENT_RETRY_COOLDOWN_SECONDS
    ):
        return None
    try:
        from supabase import create_client

        _client = create_client(url, key)
        _client_init_failed_at = None
    except Exception:
        _client_init_failed_at = time.monotonic()
        _logger.exception(
            "[analytics] Failed to create Supabase client, will retry in %ss",
            _CLIENT_RETRY_COOLDOWN_SECONDS,
        )
    return _client


def _read_fallback() -> list[dict]:
    if not _FALLBACK_LOG_PATH.exists():
        return []
    records = []
    with _FALLBACK_LOG_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records


def _rewrite_fallback(records: list[dict]) -> None:
    if not records:
        _FALLBACK_LOG_PATH.unlink(missing_ok=True)
        return
    tmp_path = _FALLBACK_LOG_PATH.with_suffix(".tmp")
    with tmp_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    tmp_path.replace(_FALLBACK_LOG_PATH)


def _append_fallback(payload: dict) -> None:
    """Last-resort durability: append the payload locally so a failed row can be
    replayed later instead of silently vanishing. Note this lives in the container's
    filesystem, so it only survives restarts if the data/ dir is volume-mounted.
    """
    try:
        _FALLBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {"logged_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        with _fallback_lock, _FALLBACK_LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        _logger.exception("[analytics] Also failed to write local fallback log")


def _insert(client: Any, payload: dict, *, attempts: int = _MAX_ATTEMPTS) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            client.table(_TABLE).insert(payload).execute()
            return True
        except Exception:
            if attempt == attempts:
                _logger.exception(
                    "[analytics] Supabase write failed after %d attempt(s), payload=%r",
                    attempts,
                    payload,
                )
            else:
                time.sleep(_RETRY_DELAY_SECONDS * attempt)
    return False


def _replay_fallback(client: Any) -> None:
    """Opportunistically flush previously-failed rows before writing the new one,
    so a transient Supabase outage self-heals instead of leaving rows stuck in the
    local file forever (as long as the process survives long enough to retry).
    """
    with _fallback_lock:
        pending = _read_fallback()
        if not pending:
            return
        still_failed = [r for r in pending if not _insert(client, r["payload"])]
        _rewrite_fallback(still_failed)


def _worker_loop() -> None:
    while True:
        payload = _queue.get()
        try:
            creds = _creds()
            if creds is None:
                continue  # analytics not configured — intentional no-op, no fallback
            client = _get_client(*creds)
            if client is None:
                _append_fallback(payload)
                continue
            _replay_fallback(client)
            if not _insert(client, payload):
                _append_fallback(payload)
        except Exception:
            _logger.exception("[analytics] Worker failed on payload=%r", payload)
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, daemon=True, name="supabase-analytics").start()
        _worker_started = True
        atexit.register(_flush_on_exit)


def _flush_on_exit() -> None:
    """Best-effort, bounded flush on graceful shutdown (e.g. SIGTERM) so queued
    rows aren't lost to the process exiting before the worker gets to them. Skips
    retries — a single fast attempt per row is all the time budget allows.
    """
    creds = _creds()
    if creds is None:
        return
    client = _get_client(*creds)
    if client is None:
        return
    deadline = time.monotonic() + _ATEXIT_FLUSH_SECONDS
    while time.monotonic() < deadline:
        try:
            payload = _queue.get_nowait()
        except queue.Empty:
            return
        if not _insert(client, payload, attempts=1):
            _append_fallback(payload)


def log_query_background(
    *,
    anonymous_id: str,
    ticker: str,
    query: str,
    result: dict,
    elapsed_ms: float,
) -> None:
    """Log one investigation run via the background worker so a slow/unavailable
    Supabase never adds latency to the user-facing analysis.
    """
    price_data = (result.get("data") or {}).get("get_price_data") or {}
    citations = [c for tile in result.get("tiles", []) for c in tile.get("citations", [])]

    cache_hits = set(result.get("cache_hits") or [])
    tools_called = sorted(
        f"{name}:redis" if name in cache_hits else f"{name}:live"
        for name in (result.get("data") or {}).keys()
    )

    payload = {
        "anonymous_id": anonymous_id,
        "ticker": ticker,
        "query": query or None,
        "status": result.get("status", "complete"),
        "move_assessment": price_data.get("move_assessment") or None,
        "tools_called": tools_called or None,
        "hypotheses": result.get("hypotheses") or None,
        "citations": citations or None,
        "elapsed_ms": round(elapsed_ms),
    }

    _ensure_worker()
    try:
        _queue.put_nowait(payload)
    except queue.Full:
        _logger.warning("[analytics] Queue full (%d), writing straight to fallback log", _QUEUE_MAXSIZE)
        _append_fallback(payload)
