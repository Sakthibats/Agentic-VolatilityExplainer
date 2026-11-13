"""Logging setup: one JSON object per line on Cloud Run, readable text everywhere else.

Cloud Logging parses a JSON line into a structured entry: `severity` becomes the entry's level
and every other key a searchable `jsonPayload` field, so a filter such as
`jsonPayload.event="run" AND jsonPayload.cost_usd > 0.01` works with no agent or SDK. Locally
the same records print as plain text, so terminal output reads the way the old `print` lines did.

Extra fields go in `extra={"fields": {...}}`. Every line logged while an investigation runs
also carries its `run_id` (bind_run_id), including lines from tool worker threads:
asyncio.to_thread copies the context into the thread.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import uuid
from typing import IO

_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)

# Loggers that would leak or flood at INFO. httpx logs every request's full URL, and FRED
# only accepts its API key as a query parameter (AGENTS.md: keys stay out of logs).
_QUIET_LOGGERS = ("httpx", "httpcore", "urllib3", "hpack", "yfinance", "peewee")

_HANDLER_MARK = "_volx_handler"


def bind_run_id() -> str:
    """Start a run: a new ID that every log line in this context will carry."""
    run_id = uuid.uuid4().hex[:12]
    _run_id.set(run_id)
    return run_id


def _fields(record: logging.LogRecord) -> dict:
    fields = getattr(record, "fields", None)
    return fields if isinstance(fields, dict) else {}


class JsonFormatter(logging.Formatter):
    """One Cloud Logging entry per record. Field names match Cloud Logging's special keys."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        entry = {
            **_fields(record),
            "severity": record.levelname,
            "message": message,
            "logger": record.name,
        }
        run_id = _run_id.get()
        if run_id:
            entry["run_id"] = run_id
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """The message as written, then any extra fields as compact JSON."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        fields = _fields(record)
        return f"{text}  {json.dumps(fields, default=str)}" if fields else text


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout is when a record is emitted, not when the handler was
    built, so contextlib.redirect_stdout and pytest's output capture still see the lines."""

    @property
    def stream(self) -> IO[str]:
        return sys.stdout

    @stream.setter
    def stream(self, _value: IO[str]) -> None:
        pass


def configure_logging(
    *, stream: IO[str] | None = None, json_format: bool | None = None, level: str | None = None
) -> None:
    """Install the app's handler on the root logger. Safe to call more than once.

    json_format defaults to LOG_FORMAT ("json" | "text") when set, otherwise JSON on Cloud
    Run (detected by its K_SERVICE variable) and text elsewhere. level defaults to LOG_LEVEL,
    then INFO. Handlers installed by others (pytest's caplog, uvicorn's own loggers) are left
    alone.
    """
    if json_format is None:
        chosen = os.environ.get("LOG_FORMAT", "").lower()
        json_format = chosen == "json" if chosen else "K_SERVICE" in os.environ

    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream) if stream is not None else _StdoutHandler()
    handler.setFormatter(JsonFormatter() if json_format else TextFormatter("%(message)s"))
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel((level or os.environ.get("LOG_LEVEL") or "INFO").upper())

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
