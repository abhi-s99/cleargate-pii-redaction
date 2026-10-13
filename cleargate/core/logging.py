"""Structured logging with a PII-safe filter (TR-SEC-03, ADR-11).

``configure_logging`` installs one JSON handler on the root logger with a
``PiiSafeFilter``. Because the filter sits on the handler, it applies to every
record that reaches it, including records from third-party libraries.

The filter is defence in depth, not the primary control (the primary control
is that code only logs ids, counts, types and locators):

* a record whose rendered message or ``extra`` fields contain a needle of an
  active job (case-insensitive) is dropped and counted;
* exception information is reduced to the exception type and, for
  ``ClearGateError``, its code. Exception ``args`` and tracebacks are never
  emitted, because ``args`` of third-party exceptions may quote content.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, TextIO

from cleargate.core.errors import ClearGateError

_STD_ATTRS = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)).keys()
    | {"message", "asctime"}
)
MIN_NEEDLE_LEN = 3


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in vars(record).items() if k not in _STD_ATTRS}


class PiiSafeFilter(logging.Filter):
    """Drops records that contain active needles and strips exception content."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._needles: dict[str, frozenset[str]] = {}
        self.suppressed = 0

    def register(self, job_id: str, values: Iterable[str]) -> None:
        cleaned = frozenset(v.casefold() for v in values if len(v.strip()) >= MIN_NEEDLE_LEN)
        with self._lock:
            self._needles[job_id] = self._needles.get(job_id, frozenset()) | cleaned

    def clear(self, job_id: str) -> None:
        with self._lock:
            self._needles.pop(job_id, None)

    def active_needle_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._needles.values())

    def _contains_needle(self, text: str) -> bool:
        folded = text.casefold()
        with self._lock:
            return any(n in folded for needles in self._needles.values() for n in needles)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc = record.exc_info[1]
            if isinstance(exc, ClearGateError):
                record.exc_summary = f"{type(exc).__name__}:{exc.code.value}"
            elif exc is not None:
                record.exc_summary = type(exc).__name__
            record.exc_info = None
            record.exc_text = None
        record.stack_info = None
        try:
            rendered = record.getMessage()
        except (TypeError, ValueError):
            rendered = str(record.msg)
        haystack = rendered + " " + " ".join(str(v) for v in _extras(record).values())
        if self._contains_needle(haystack):
            with self._lock:
                self.suppressed += 1
            return False
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(_extras(record))
        return json.dumps(payload, default=str, ensure_ascii=False)


_FILTER = PiiSafeFilter()
_HANDLER_NAME = "cleargate-json"


def pii_filter() -> PiiSafeFilter:
    """The process-wide filter instance used by the configured handler."""
    return _FILTER


def configure_logging(level: int = logging.INFO, stream: TextIO | None = None) -> logging.Handler:
    """Install (or replace) the ClearGate JSON handler on the root logger."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_FILTER)
    root.addHandler(handler)
    root.setLevel(level)
    return handler


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
