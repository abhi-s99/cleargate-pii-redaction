"""Detection against the planted-PII manifest (TR-DT-10..16, FR-05, FR-06, brief 4.4).

Every planted item is detected with the right type at its locator and is redacted (decision
``auto_redact`` or ``review``); decoys (risk/incident/policy IDs, products, a company PAN)
are never redacted; faces and the illegible region become region findings.
"""

from __future__ import annotations

import re

import pytest
from rapidfuzz import fuzz

from cleargate.core.config import Settings, load_policy
from cleargate.core.models import Document, Finding
from cleargate.detect.engine import DetectionEngine
from tests.fixtures.manifest import Planted, load_manifest, locator_ok, norm, planted_items

ITEMS = planted_items()
REDACTING = ("auto_redact", "review")


@pytest.fixture(scope="module")
def findings(docs: dict[str, Document], ocr_settings: Settings) -> dict[str, list[Finding]]:
    assert ocr_settings.vault_key is not None
    names = sorted(docs)
    out = DetectionEngine(load_policy()).detect_batch(
        [docs[n] for n in names], key=ocr_settings.vault_key.get_secret_value().encode()
    )
    return dict(zip(names, out, strict=True))


def span_text(doc: Document, f: Finding) -> str:
    seg = next(s for s in doc.segments if s.segment_id == f.segment_id)
    return seg.text[f.start : f.end]


def covers(doc: Document, f: Finding, item: Planted) -> bool:
    seg = next((s for s in doc.segments if s.segment_id == f.segment_id), None)
    if seg is None or not locator_ok(seg, item.expect):
        return False
    text = norm(span_text(doc, f))
    if norm(item.value) in text:
        return True
    return (
        item.channel == "ocr"
        and fuzz.partial_ratio(norm(item.value), text) >= 90
        and len(text) >= len(norm(item.value)) - 2
    )


@pytest.mark.parametrize(
    "item", [i for i in ITEMS if i.channel != "image-only"], ids=lambda i: i.id
)
def test_planted_item_detected_with_type_and_redacted(
    docs: dict[str, Document], findings: dict[str, list[Finding]], item: Planted
) -> None:
    doc = docs[item.file]
    hits = [
        f
        for f in findings[item.file]
        if f.entity_type.value == item.type and f.decision in REDACTING and covers(doc, f, item)
    ]
    assert hits, f"{item.id}: {item.type} not detected ({item.channel}, {item.note})"


def test_illegible_region_item_is_masked_not_read(findings: dict[str, list[Finding]]) -> None:
    regions = [
        f
        for f in findings["planted_scanned.pdf"]
        if f.entity_type.value == "UNREADABLE_IMAGE_REGION"
    ]
    assert regions
    assert all(f.locator and f.locator.page == 1 for f in regions)


@pytest.mark.parametrize(
    "decoy", load_manifest()["decoys"], ids=lambda d: f"{d['kind']}-{d['file']}"
)
def test_decoys_are_not_redacted(
    docs: dict[str, Document], findings: dict[str, list[Finding]], decoy: dict[str, str]
) -> None:
    doc = docs[decoy["file"]]
    bad = [
        f
        for f in findings[decoy["file"]]
        if f.decision in REDACTING
        and f.segment_id in {s.segment_id for s in doc.segments}
        and norm(decoy["value"]) in norm(span_text(doc, f))
    ]
    assert bad == [], f"decoy {decoy['kind']} redacted as {[f.entity_type.value for f in bad]}"


def test_company_pan_is_discarded_as_business(
    docs: dict[str, Document], findings: dict[str, list[Finding]]
) -> None:
    pans = [f for f in findings["planted_scanned.pdf"] if f.entity_type.value == "IN_PAN"]
    assert sorted(f.decision for f in pans) == ["auto_redact", "discarded"]
    assert any(e.rule_id == "discard:business_pan" for f in pans for e in f.evidence)


@pytest.mark.parametrize(
    "region", load_manifest()["regions"], ids=lambda r: f"{r['kind']}-{r['file']}"
)
def test_expected_regions_become_findings(
    findings: dict[str, list[Finding]], region: dict[str, object]
) -> None:
    etype = "PHOTO" if region["kind"] == "face" else "UNREADABLE_IMAGE_REGION"
    hits = [f for f in findings[str(region["file"])] if f.entity_type.value == etype]
    for key in ("page", "slide"):
        if key in region:
            hits = [f for f in hits if f.locator and getattr(f.locator, key) == region[key]]
    if "part_prefix" in region:
        hits = [
            f for f in hits if f.locator and f.locator.part.startswith(str(region["part_prefix"]))
        ]
    assert hits, region


def test_same_person_gets_one_person_key(
    docs: dict[str, Document], findings: dict[str, list[Finding]]
) -> None:
    doc = docs["planted.docx"]
    keys = {
        f.person_key
        for f in findings["planted.docx"]
        if f.entity_type.value == "PERSON" and "Oyelaran" in span_text(doc, f)
    }
    assert len(keys) == 1  # OCR line, alt text and approver label share one identity


def test_findings_persist_without_values(findings: dict[str, list[Finding]], store) -> None:  # type: ignore[no-untyped-def]
    from cleargate.core.db import MetaStore

    s: MetaStore = store
    s.create_batch("b1", "p", "h")
    s.create_job("planted_docx", "b1", "planted.docx", "h")
    all_f = findings["planted.docx"]
    s.add_findings(
        "planted_docx", [f.model_copy(update={"finding_id": "x" + f.finding_id}) for f in all_f]
    )
    dump = "\n".join(str(tuple(r)) for r in s.findings("planted_docx"))
    for item in (i for i in ITEMS if i.file == "planted.docx"):
        # Boundaries: a short value can occur by chance inside a 64-char HMAC hex digest.
        hit = re.search(rf"(?<![0-9A-Za-z]){re.escape(item.value)}(?![0-9A-Za-z])", dump)
        assert hit is None, item.id
