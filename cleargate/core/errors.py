"""Typed errors with content-free messages (TR-SEC-02/03, ADR-11).

Every error carries a stable ``code`` and a message rendered from a fixed
template. Detail values are restricted to numbers, booleans and short
identifier-like strings, so an exception can never quote document content.
Anything else is replaced by ``<redacted>`` before it reaches the message.
``Exception.args`` holds only the code, so tracebacks and ``repr`` stay clean.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import ClassVar

_SAFE_STR = re.compile(r"^[A-Za-z0-9_.:/\-]{0,64}$")
REDACTED = "<redacted>"

DetailValue = int | float | bool | str | None


class ErrorCode(StrEnum):
    # configuration and environment
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    KEY_MISSING = "KEY_MISSING"
    KEY_INVALID = "KEY_INVALID"
    # ingestion (TR-IN-01..06)
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    EXTENSION_MISMATCH = "EXTENSION_MISMATCH"
    ENCRYPTED = "ENCRYPTED"
    MACRO_ENABLED = "MACRO_ENABLED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOO_MANY_PAGES = "TOO_MANY_PAGES"
    ZIP_BOMB = "ZIP_BOMB"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    MALFORMED = "MALFORMED"
    # processing
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    REDACTION_FAILED = "REDACTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VAULT_UNAVAILABLE = "VAULT_UNAVAILABLE"
    # gate
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    HANDLE_INVALID = "HANDLE_INVALID"
    HANDOFF_REFUSED = "HANDOFF_REFUSED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    INTERNAL = "INTERNAL"


_TEMPLATES: dict[ErrorCode, str] = {
    ErrorCode.CONFIG_INVALID: "Policy configuration is invalid ({field})",
    ErrorCode.CONFIG_NOT_FOUND: "Policy file not found ({name})",
    ErrorCode.KEY_MISSING: "Required key {name} is not set",
    ErrorCode.KEY_INVALID: "Key {name} is not valid",
    ErrorCode.UNSUPPORTED_FORMAT: "File type is not supported ({ext})",
    ErrorCode.EXTENSION_MISMATCH: "Extension {ext} does not match detected type {detected}",
    ErrorCode.ENCRYPTED: "File is encrypted or password protected",
    ErrorCode.MACRO_ENABLED: "Macro-enabled files are rejected",
    ErrorCode.FILE_TOO_LARGE: "File is {size_bytes} bytes, limit is {limit_bytes}",
    ErrorCode.TOO_MANY_PAGES: "Document has {pages} pages, limit is {limit}",
    ErrorCode.ZIP_BOMB: "Archive expands beyond the allowed size or ratio",
    ErrorCode.IMAGE_TOO_LARGE: "Image has {megapixels} MP, limit is {limit}",
    ErrorCode.MALFORMED: "File structure could not be parsed ({stage})",
    ErrorCode.EXTRACTION_FAILED: "Extraction failed for part {part}",
    ErrorCode.OCR_UNAVAILABLE: "OCR engine is not available",
    ErrorCode.OCR_TIMEOUT: "Page {page} could not be OCR'd within {timeout_s} s",
    ErrorCode.MODEL_UNAVAILABLE: "NER model {model} could not be loaded",
    ErrorCode.REDACTION_FAILED: "Redaction could not be applied ({count} actions)",
    ErrorCode.VERIFICATION_FAILED: "Verification check {check} failed to run",
    ErrorCode.VAULT_UNAVAILABLE: "Pseudonym vault is unavailable",
    ErrorCode.ILLEGAL_TRANSITION: "Transition {from_state} -> {to_state} is not allowed",
    ErrorCode.HANDLE_INVALID: "SafeHandle verification failed ({reason})",
    ErrorCode.HANDOFF_REFUSED: "Handoff refused ({reason})",
    ErrorCode.JOB_NOT_FOUND: "Job not found",
    ErrorCode.INTERNAL: "Internal error in stage {stage}",
}


def safe_detail(value: DetailValue) -> DetailValue:
    """Return ``value`` if it cannot carry document content, else ``<redacted>``."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str) and _SAFE_STR.match(value):
        return value
    return REDACTED


class _SafeDict(dict[str, DetailValue]):
    def __missing__(self, key: str) -> str:
        return "?"


class ClearGateError(Exception):
    """Base error. Subclasses fix a default code; callers pass safe details only."""

    default_code: ClassVar[ErrorCode] = ErrorCode.INTERNAL

    def __init__(
        self,
        code: ErrorCode | None = None,
        *,
        job_id: str | None = None,
        **details: DetailValue,
    ) -> None:
        self.code: ErrorCode = code or self.default_code
        self.job_id: str | None = job_id if job_id and _SAFE_STR.match(job_id) else None
        self.details: dict[str, DetailValue] = {k: safe_detail(v) for k, v in details.items()}
        self.message: str = _TEMPLATES[self.code].format_map(_SafeDict(self.details))
        super().__init__(self.code.value)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    def to_dict(self) -> dict[str, object]:
        """API error body (TRD section 10)."""
        body: dict[str, object] = {"code": self.code.value, "message": self.message}
        if self.job_id:
            body["job_id"] = self.job_id
        return {"error": body}


class ConfigError(ClearGateError):
    default_code = ErrorCode.CONFIG_INVALID


class IngestError(ClearGateError):
    default_code = ErrorCode.MALFORMED


class ExtractionError(ClearGateError):
    default_code = ErrorCode.EXTRACTION_FAILED


class OcrError(ClearGateError):
    default_code = ErrorCode.OCR_UNAVAILABLE


class RedactionError(ClearGateError):
    default_code = ErrorCode.REDACTION_FAILED


class VerificationError(ClearGateError):
    default_code = ErrorCode.VERIFICATION_FAILED


class VaultError(ClearGateError):
    default_code = ErrorCode.VAULT_UNAVAILABLE


class IllegalTransition(ClearGateError):
    default_code = ErrorCode.ILLEGAL_TRANSITION


class HandleError(ClearGateError):
    default_code = ErrorCode.HANDLE_INVALID


class HandoffRefused(ClearGateError):
    default_code = ErrorCode.HANDOFF_REFUSED
