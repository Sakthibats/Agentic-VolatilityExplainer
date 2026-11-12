"""Shared test setup.

The backend keeps several per-process caches in module globals (the tool/snapshot memo, the
ticker-resolution caches, the options chain cache). A value cached by one test would be
served to the next, so every test starts with all of them empty.
"""

from __future__ import annotations

import pytest
from volatility_explainer.clients.redis_cache import clear_memoized_tool_data
from volatility_explainer.query import parsing
from volatility_explainer.tools import options


def _clear_process_caches() -> None:
    clear_memoized_tool_data()
    parsing._ticker_cache.clear()
    parsing._llm_ticker_cache.clear()
    parsing._company_names.clear()
    options._cache.clear()


@pytest.fixture(autouse=True)
def _fresh_process_caches():
    _clear_process_caches()
    yield
    _clear_process_caches()
