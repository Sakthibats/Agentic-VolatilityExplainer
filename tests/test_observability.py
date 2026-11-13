"""observability.py: the log line format, the config, and the keys-out-of-logs guard."""

from __future__ import annotations

import asyncio
import io
import json
import logging

import httpx
import pytest
from volatility_explainer import observability
from volatility_explainer.clients.fred import FredClient
from volatility_explainer.observability import JsonFormatter, bind_run_id, configure_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    token = observability._run_id.set(None)
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    observability._run_id.reset(token)


def _record(message: str, level: int = logging.INFO, **extra) -> logging.LogRecord:
    record = logging.LogRecord("volatility_explainer.x", level, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_a_json_line_is_one_cloud_logging_entry_with_its_fields():
    line = json.loads(JsonFormatter().format(_record("[run:AAPL] complete", fields={"cost_usd": 0.0014})))
    assert line == {
        "severity": "INFO", "message": "[run:AAPL] complete",
        "logger": "volatility_explainer.x", "cost_usd": 0.0014,
    }


def test_fields_cannot_overwrite_severity_or_message():
    line = json.loads(JsonFormatter().format(
        _record("real", logging.ERROR, fields={"severity": "INFO", "message": "fake"})
    ))
    assert (line["severity"], line["message"]) == ("ERROR", "real")


def test_every_line_in_a_run_carries_its_run_id_even_on_worker_threads():
    async def run() -> tuple[str, dict]:
        run_id = bind_run_id()
        line = await asyncio.to_thread(lambda: JsonFormatter().format(_record("tool")))
        return run_id, json.loads(line)

    run_id, line = asyncio.run(run())
    assert line["run_id"] == run_id


def test_an_exception_is_kept_in_the_message():
    try:
        raise RuntimeError("upstream down")
    except RuntimeError:
        import sys

        record = _record("failed", logging.ERROR, exc_info=sys.exc_info())
    message = json.loads(JsonFormatter().format(record))["message"]
    assert message.startswith("failed\nTraceback") and "upstream down" in message


@pytest.mark.parametrize(("env", "expect_json"), [
    ({}, False),
    ({"K_SERVICE": "volx-api"}, True),               # Cloud Run sets K_SERVICE
    ({"K_SERVICE": "volx-api", "LOG_FORMAT": "text"}, False),
    ({"LOG_FORMAT": "json"}, True),
])
def test_format_is_json_on_cloud_run_and_text_elsewhere(monkeypatch, env, expect_json):
    for key in ("K_SERVICE", "LOG_FORMAT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    out = io.StringIO()
    configure_logging(stream=out)
    logging.getLogger("volatility_explainer.test").info("hello")
    text = out.getvalue().strip()
    assert text.startswith("{") is expect_json
    assert "hello" in text


def test_configuring_twice_leaves_one_handler_and_keeps_other_handlers():
    other = logging.NullHandler()
    logging.getLogger().addHandler(other)
    configure_logging(stream=io.StringIO())
    configure_logging(stream=io.StringIO())
    ours = [h for h in logging.getLogger().handlers if getattr(h, observability._HANDLER_MARK, False)]
    assert len(ours) == 1
    assert other in logging.getLogger().handlers


def test_a_fred_api_key_never_reaches_the_log_even_at_debug():
    # httpx logs each request URL at INFO, and FRED takes its key in the query string.
    out = io.StringIO()
    configure_logging(stream=out, json_format=True, level="DEBUG")
    settings = type("S", (), {"fred_api_key": type("K", (), {"get_secret_value": lambda self: "FREDSECRET"})()})()
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"observations": []})
    ))
    FredClient(settings, client=client).get_series_observations("VIXCLS", limit=1)
    assert "FREDSECRET" not in out.getvalue()
