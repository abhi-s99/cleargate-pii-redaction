"""Typed errors carry content-free messages (TR-SEC-02/03, TRD section 10 error schema)."""

from __future__ import annotations

import pytest

from cleargate.core.errors import (
    REDACTED,
    ClearGateError,
    ErrorCode,
    IllegalTransition,
    IngestError,
    OcrError,
    safe_detail,
)


def test_every_code_has_a_template() -> None:
    for code in ErrorCode:
        err = ClearGateError(code)
        assert err.message
        assert "{" not in err.message


def test_message_uses_template_and_safe_details() -> None:
    err = OcrError(ErrorCode.OCR_TIMEOUT, job_id="job-7", page=18, timeout_s=120)
    assert err.message == "Page 18 could not be OCR'd within 120 s"
    assert str(err) == "OCR_TIMEOUT: Page 18 could not be OCR'd within 120 s"
    assert err.to_dict() == {
        "error": {"code": "OCR_TIMEOUT", "message": err.message, "job_id": "job-7"}
    }


@pytest.mark.parametrize(
    "unsafe",
    [
        "Elspeth Moorcroft-Vane",  # spaces: free text
        "900-12-3456 in table",
        "a" * 65,  # too long to be an identifier
        "name<script>",
        "line\nbreak",
    ],
)
def test_content_like_details_are_redacted(unsafe: str) -> None:
    err = IngestError(ErrorCode.MALFORMED, stage=unsafe)
    assert unsafe not in str(err)
    assert unsafe not in repr(err)
    assert err.details["stage"] == REDACTED
    assert unsafe not in str(err.to_dict())


@pytest.mark.parametrize("safe", ["word/document.xml", "ppt/slides/slide3.xml", "G3", "job-1:42"])
def test_identifier_details_are_kept(safe: str) -> None:
    assert safe_detail(safe) == safe


def test_args_hold_only_the_code() -> None:
    err = IllegalTransition(from_state="RECEIVED", to_state="VALIDATED_SAFE")
    assert err.args == ("ILLEGAL_TRANSITION",)
    assert err.code is ErrorCode.ILLEGAL_TRANSITION
    assert "RECEIVED -> VALIDATED_SAFE" in err.message


def test_unsafe_job_id_is_dropped() -> None:
    err = ClearGateError(job_id="not a job id")
    assert err.job_id is None
    assert "job_id" not in err.to_dict()["error"]  # type: ignore[operator]


def test_missing_template_field_does_not_raise() -> None:
    assert ClearGateError(ErrorCode.OCR_TIMEOUT).message == "Page ? could not be OCR'd within ? s"
