"""The usage-log payload — only what is queued for Supabase, never a real write."""

from __future__ import annotations

from pathlib import Path

from volatility_explainer.analytics import supabase_logger


def _logged(monkeypatch, result: dict) -> dict:
    queued: list[dict] = []
    monkeypatch.setattr(supabase_logger, "_ensure_worker", lambda: None)
    monkeypatch.setattr(supabase_logger._queue, "put_nowait", queued.append)
    supabase_logger.log_query_background(
        anonymous_id="anon", ticker="AAPL", query="", result=result, elapsed_ms=12.3,
    )
    return queued[0]


def test_quality_flags_are_logged_for_a_checked_explanation(monkeypatch):
    payload = _logged(monkeypatch, {"summary": "Why.", "quality_flags": ["too_long"]})
    assert payload["quality_flags"] == ["too_long"]


def test_a_clean_explanation_logs_an_empty_list_not_null(monkeypatch):
    """[] (checked, clean) and None (nothing checked) must stay distinguishable in SQL."""
    payload = _logged(monkeypatch, {"summary": "Why.", "quality_flags": []})
    assert payload["quality_flags"] == []


def test_no_explanation_logs_null_flags(monkeypatch):
    assert _logged(monkeypatch, {"status": "error", "data": {}})["quality_flags"] is None
    assert _logged(monkeypatch, {"summary": "", "quality_flags": []})["quality_flags"] is None


def test_the_model_that_answered_is_logged(monkeypatch):
    queued: list[dict] = []
    monkeypatch.setattr(supabase_logger, "_ensure_worker", lambda: None)
    monkeypatch.setattr(supabase_logger._queue, "put_nowait", queued.append)
    supabase_logger.log_query_background(
        anonymous_id="anon", ticker="AAPL", query="", result={"summary": "Why."},
        elapsed_ms=1.0, llm_provider="openai", llm_model="gpt-6-luna",
    )

    assert (queued[0]["llm_provider"], queued[0]["llm_model"]) == ("openai", "gpt-6-luna")


def test_fallback_log_is_not_written_inside_the_installed_package():
    # Installed in the Docker image the package sits in site-packages, which the non-root
    # user can't write to; the fallback lives under the working directory (/app/data there).
    package_dir = Path(supabase_logger.__file__).resolve().parents[1]
    assert package_dir not in supabase_logger._FALLBACK_LOG_PATH.resolve().parents
    assert supabase_logger._FALLBACK_LOG_PATH.parent.name == "data"
