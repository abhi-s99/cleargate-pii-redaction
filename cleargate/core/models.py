"""Canonical Document Model and findings (TRD section 4, ADR-02).

Fields that hold raw content (marked [RAW] in the TRD) are declared with
``raw_field()``: they are excluded from every serialisation (``model_dump``,
``model_dump_json``) and from ``repr``/``str``, so they can only travel in
process memory (including pickling to worker processes) and, encrypted, in the
vault (TR-SEC-02). ``RAW_FIELDS`` lists them so tests can assert the property.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def raw_field(**kwargs: Any) -> Any:
    """A field holding raw document content: never serialised, never in repr."""
    return Field(exclude=True, repr=False, **kwargs)


class FileFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"
    XLSX = "xlsx"


class EntityType(StrEnum):
    PERSON = "PERSON"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    EMPLOYEE_ID = "EMPLOYEE_ID"
    US_SSN = "US_SSN"
    IN_PAN = "IN_PAN"
    PL_PESEL = "PL_PESEL"
    PASSPORT = "PASSPORT"
    TAX_ID = "TAX_ID"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    HOME_ADDRESS = "HOME_ADDRESS"
    FINANCIAL_PARTIAL = "FINANCIAL_PARTIAL"
    PAYMENT_CARD = "PAYMENT_CARD"
    PHOTO = "PHOTO"
    UNREADABLE_IMAGE_REGION = "UNREADABLE_IMAGE_REGION"


Risk = Literal["HIGH", "MEDIUM", "LOW"]
Tier = Literal["DETERMINISTIC", "CORROBORATED", "SINGLE_SIGNAL", "LOW"]
Layer = Literal["L1", "L2", "L3", "L4", "L5", "REGION"]
Decision = Literal["auto_redact", "review", "suppressed", "discarded"]
SegmentKind = Literal[
    "heading",
    "paragraph",
    "list_item",
    "table_cell",
    "shape_text",
    "notes",
    "header",
    "footer",
    "textbox",
    "alt_text",
    "metadata",
    "ocr_line",
    "caption",
]

# TRD section 4.1: default risk and token label per type. HIGH-risk identifiers
# use un-numbered tokens; region types are masked, not tokenised.
DEFAULT_RISK: dict[EntityType, Risk] = {
    EntityType.PERSON: "MEDIUM",
    EntityType.EMAIL_ADDRESS: "MEDIUM",
    EntityType.PHONE_NUMBER: "MEDIUM",
    EntityType.EMPLOYEE_ID: "MEDIUM",
    EntityType.US_SSN: "HIGH",
    EntityType.IN_PAN: "HIGH",
    EntityType.PL_PESEL: "HIGH",
    EntityType.PASSPORT: "HIGH",
    EntityType.TAX_ID: "HIGH",
    EntityType.DATE_OF_BIRTH: "HIGH",
    EntityType.HOME_ADDRESS: "HIGH",
    EntityType.FINANCIAL_PARTIAL: "HIGH",
    EntityType.PAYMENT_CARD: "HIGH",
    EntityType.PHOTO: "HIGH",
    EntityType.UNREADABLE_IMAGE_REGION: "HIGH",
}

TOKEN_LABEL: dict[EntityType, str | None] = {
    EntityType.PERSON: "PERSON",
    EntityType.EMAIL_ADDRESS: "EMAIL",
    EntityType.PHONE_NUMBER: "PHONE",
    EntityType.EMPLOYEE_ID: "EMPLOYEE_ID",
    EntityType.US_SSN: "SSN",
    EntityType.IN_PAN: "NATIONAL_ID",
    EntityType.PL_PESEL: "NATIONAL_ID",
    EntityType.PASSPORT: "PASSPORT",
    EntityType.TAX_ID: "TAX_ID",
    EntityType.DATE_OF_BIRTH: "DOB",
    EntityType.HOME_ADDRESS: "HOME_ADDRESS",
    EntityType.FINANCIAL_PARTIAL: "ACCOUNT_REF",
    EntityType.PAYMENT_CARD: "CARD",
    EntityType.PHOTO: None,
    EntityType.UNREADABLE_IMAGE_REGION: None,
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Locator(_Model):
    model_config = ConfigDict(extra="forbid", frozen=True)

    part: str
    page: int | None = None
    slide: int | None = None
    shape_id: int | None = None
    paragraph_index: int | None = None
    run_range: tuple[int, int] | None = None
    table: int | None = None
    row: int | None = None
    col: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    image_ref: str | None = None
    xpath: str | None = None


class Segment(_Model):
    segment_id: str
    kind: SegmentKind
    text: str = raw_field()  # [RAW]
    order_index: int
    heading_level: int | None = None
    locator: Locator
    method: Literal["native", "ocr"]
    ocr_word_conf: list[float] | None = None
    parent_id: str | None = None


class Coverage(_Model):
    parts_total: int = 0
    parts_inspected: int = 0
    parts_masked: int = 0
    uninspected: list[Locator] = Field(default_factory=list)


class Document(_Model):
    doc_id: str
    filename: str
    sha256: str
    fmt: FileFormat
    size_bytes: int
    units: dict[str, int] = Field(default_factory=dict)
    segments: list[Segment] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)


class Evidence(_Model):
    detector: str
    layer: Layer
    rule_id: str
    raw_score: float | None = None
    context_terms: list[str] = Field(default_factory=list)


class Finding(_Model):
    finding_id: str
    segment_id: str
    start: int
    end: int
    entity_type: EntityType
    risk: Risk
    tier: Tier
    evidence: list[Evidence]
    format_invalid: bool = False
    value: str = raw_field()  # [RAW], dropped before persistence
    value_hmac: str
    preview: str
    person_key: str | None = None
    decision: Decision
    token: str | None = None


class RedactionAction(_Model):
    finding_ids: list[str]
    locator: Locator
    method: Literal["token_replace", "pixel_mask", "region_mask", "metadata_clear", "remove_part"]
    token: str | None = None
    applied: bool = False
    error_code: str | None = None


CheckId = Literal["V1", "V2", "V3", "V4", "V5", "V6"]
ALL_CHECKS: frozenset[CheckId] = frozenset({"V1", "V2", "V3", "V4", "V5", "V6"})


class VerificationReport(_Model):
    """Outcome of checks V1..V6 (TRD 8.1) as the gate reads them. Counts only, no values.

    Phase 7 produces it from the independent re-extraction path; the gate (Phase 1)
    only consumes it. ``verifiers`` records name -> version for reproducibility.

    ``checks_run`` lists the checks that actually executed. It defaults to empty, so a
    report that does not say a check ran is treated as if that check failed (ADR-24):
    V1 missing is G0, V2..V5 missing is G3 (an uninspected verification dimension),
    V6 missing is G6.
    """

    job_id: str
    checks_run: frozenset[CheckId] = frozenset()
    reopen_ok: bool  # V1
    leak_hits: int = Field(0, ge=0)  # V2
    residual_deterministic: int = Field(0, ge=0)  # V3, blocking
    residual_other: int = Field(0, ge=0)  # V3, review
    uninspected_unmasked: int = Field(0, ge=0)  # V4
    unit_counts_equal: bool = True  # V4: pages/slides/images unchanged
    consistency_ok: bool = True  # V5
    srs: float | None = Field(None, ge=0.0, le=1.0)  # V6
    crs: float | None = Field(None, ge=0.0, le=1.0)  # V6
    verifiers: dict[str, str] = Field(default_factory=dict)


# Every model field that holds raw content. Tests assert none of them serialise.
RAW_FIELDS: dict[type[BaseModel], tuple[str, ...]] = {
    Segment: ("text",),
    Finding: ("value",),
}
