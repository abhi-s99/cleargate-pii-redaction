"""PiiSafeFilter and structured logging (TR-SEC-03)."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest

from cleargate.core.errors import ErrorCode, ExtractionError
from cleargate.core.logging import PiiSafeFilter, configure_logging, pii_filter

NEEDLE = "Ottoline Varga-Brandeis"  # invented


@pytest.fixture
def captured() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = configure_logging(logging.DEBUG, stream)
    yield stream
    pii_filter().clear("job-1")
    pii_filter().clear("job-2")
    logging.getLogger().removeHandler(handler)


def lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def test_structured_json_with_extras(captured: io.StringIO) -> None:
    logging.getLogger("cleargate.test").info(
        "stage done", extra={"job_id": "job-1", "count": 3, "entity_type": "US_SSN"}
    )
    (rec,) = lines(captured)
    assert rec["event"] == "stage done"
    assert rec["job_id"] == "job-1"
    assert rec["count"] == 3
    assert rec["level"] == "INFO"
    assert rec["logger"] == "cleargate.test"


def test_record_with_active_needle_is_dropped(captured: io.StringIO) -> None:
    pii_filter().register("job-1", [NEEDLE])
    before = pii_filter().suppressed
    log = logging.getLogger("cleargate.test")
    log.info("found %s in cell", NEEDLE)
    log.info("found %s in cell", NEEDLE.upper())  # case-insensitive
    log.info("ok", extra={"detail": f"x {NEEDLE.lower()} y"})  # needle in extras
    log.info("clean message", extra={"count": 1})
    assert [r["event"] for r in lines(captured)] == ["clean message"]
    assert pii_filter().suppressed == before + 3
    assert NEEDLE.casefold() not in captured.getvalue().casefold()


def test_needles_from_third_party_loggers_are_dropped(captured: io.StringIO) -> None:
    pii_filter().register("job-1", [NEEDLE])
    logging.getLogger("presidio-analyzer").warning("entity %s", NEEDLE)
    assert lines(captured) == []


def test_clearing_a_job_releases_its_needles(captured: io.StringIO) -> None:
    pii_filter().register("job-1", [NEEDLE])
    pii_filter().register("job-2", ["Invented Other"])
    pii_filter().clear("job-1")
    logging.getLogger("t").info("mention %s", NEEDLE)
    logging.getLogger("t").info("mention Invented Other")
    assert [r["event"] for r in lines(captured)] == [f"mention {NEEDLE}"]


def test_short_needles_are_ignored() -> None:
    f = PiiSafeFilter()
    f.register("j", ["ab", "  ", "abc"])
    assert f.active_needle_count() == 1


def test_exception_args_and_traceback_are_stripped(captured: io.StringIO) -> None:
    try:
        raise ValueError(f"cannot parse {NEEDLE}")  # third-party style message with content
    except ValueError:
        logging.getLogger("t").exception("parse failed", extra={"part": "word/document.xml"})
    (rec,) = lines(captured)
    assert rec["exc_summary"] == "ValueError"
    assert NEEDLE not in captured.getvalue()
    assert "Traceback" not in captured.getvalue()


def test_cleargate_error_keeps_code_only(captured: io.StringIO) -> None:
    try:
        raise ExtractionError(part="word/media/image3.png")
    except ExtractionError:
        logging.getLogger("t").exception("extract failed")
    (rec,) = lines(captured)
    assert rec["exc_summary"] == f"ExtractionError:{ErrorCode.EXTRACTION_FAILED.value}"


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    h1 = configure_logging(stream=io.StringIO())
    h2 = configure_logging(stream=io.StringIO())
    try:
        assert h1 not in root.handlers
        assert sum(1 for h in root.handlers if h.get_name() == "cleargate-json") == 1
    finally:
        root.removeHandler(h2)
