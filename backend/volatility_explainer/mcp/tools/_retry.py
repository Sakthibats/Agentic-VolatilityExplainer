"""Small stdlib-only retry helper for flaky, unofficial data-source calls (e.g. yfinance)."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_retry(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 0.3) -> T:
    """Retry a sync callable with exponential backoff. Re-raises the last exception."""
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if i < attempts - 1:
                time.sleep(base_delay * (2**i))
    assert last_exc is not None
    raise last_exc
