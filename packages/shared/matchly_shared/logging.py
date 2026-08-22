"""Structured logging.

JSON in containers, human-readable in a terminal. A `contextvars`-backed context
carries the request id (API) or job id (worker) into every log line emitted while
handling that unit of work, which is what makes a failed match traceable across
three processes.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import sys
from typing import Any

# Default is None rather than {}: a mutable default would be shared by every
# context, so one request's fields could leak into another's log lines.
_log_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "matchly_log_context", default=None
)


def _current() -> dict[str, Any]:
    return _log_context.get() or {}


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def bind_log_context(**values: Any) -> contextvars.Token:
    """Add key/values to every log line in this task/request. Returns a reset token."""
    merged = {**_current(), **{k: v for k, v in values.items() if v is not None}}
    return _log_context.set(merged)


def reset_log_context(token: contextvars.Token) -> None:
    _log_context.reset(token)


def get_log_context() -> dict[str, Any]:
    return dict(_current())


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "message": record.getMessage(),
        }
        payload.update(_current())
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = _current()
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
        }
        suffix = {**context, **extras}
        if suffix:
            base += "  " + " ".join(f"{k}={v}" for k, v in suffix.items())
        return base


def configure_logging(*, level: str = "INFO", fmt: str = "json", service: str = "matchly") -> None:
    """Idempotent root-logger configuration. Safe to call from any entrypoint."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service) if fmt == "json" else ConsoleFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn duplicates access logs through its own handlers; route them here.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
