"""V3 residual scan (TRD 8.1, ADR-08).

The output is re-extracted into a CDM with the standard extractors and scanned with the
``verify`` profile of the detection engine: allowlist off, propagation on (registry seeded
from the source's redacted persons), ``review_threshold * 0.5``, spans touching ClearGate
tokens ignored.

A residual hit is **new** when no source finding has the same ``(type, value_hmac)``
(ADR-30): values the source pass already decided on (kept business names, discarded weak
candidates) are not re-litigated, and a redacted value that is still present is V2's job.
New DETERMINISTIC hits block (G2); other new hits go to review (G6) unless a reviewer
already accepted them (``known_residual``).
"""

from __future__ import annotations

from typing import Any

from cleargate.core.models import Document, Finding
from cleargate.detect.engine import DetectionEngine
from cleargate.detect.registry import PersonRegistry

REDACTING = ("auto_redact", "review")
_ENGINES: dict[int, DetectionEngine] = {}


def verify_engine(policy: Any) -> DetectionEngine:
    key = id(policy)
    if key not in _ENGINES:
        _ENGINES[key] = DetectionEngine(policy, profile="verify")
    return _ENGINES[key]


def residual(
    out_doc: Document,
    source_findings: list[Finding],
    ctx: Any,
) -> tuple[list[Finding], list[Finding]]:
    """``(new_deterministic, new_other)`` findings on the output document."""
    vk = ctx.settings.vault_key
    key = vk.get_secret_value().encode() if vk else b""
    registry = PersonRegistry(key)
    for f in source_findings:
        if (
            f.entity_type.value == "PERSON"
            and f.decision in REDACTING
            and f.tier in ("DETERMINISTIC", "CORROBORATED")
        ):
            registry.add(f.value)
    found = verify_engine(ctx.policy).detect_batch([out_doc], key=key, registry=registry)[0]
    known = {(f.entity_type, f.value_hmac) for f in source_findings}
    accepted = set(getattr(ctx, "known_residual", set()))
    det: list[Finding] = []
    other: list[Finding] = []
    for f in found:
        if f.decision not in REDACTING or f.end <= f.start:
            continue  # region findings re-detected on masked rasters are not residual text
        if (f.entity_type, f.value_hmac) in known or f.value_hmac in accepted:
            continue
        (det if f.tier == "DETERMINISTIC" else other).append(f)
    return det, other


def raster_key(seg_locator: Any) -> tuple[str, str | int] | None:
    """Repair key of the output raster a segment was OCR'd from, if any."""
    loc = seg_locator
    if loc.part == "page" and loc.page:
        return ("page", loc.page)
    if loc.part == "image" and loc.page:
        return ("image", loc.page)
    if loc.image_ref and loc.part.startswith(("word/", "ppt/")):
        return ("media", loc.part)
    return None


def raster_boxes_by_finding(out_doc: Document, findings: list[Finding]) -> dict[str, list[Any]]:
    """finding id -> ``[key, box]`` pairs on output rasters (review confirm burns them)."""
    from cleargate.redact.writers.image import span_boxes

    segs = {s.segment_id: s for s in out_doc.segments}
    out: dict[str, list[Any]] = {}
    for f in findings:
        seg = segs.get(f.segment_id)
        if seg is None or seg.kind != "ocr_line":
            continue
        key = raster_key(seg.locator)
        if key is None:
            continue
        out[f.finding_id] = [[list(key), list(b)] for b in span_boxes(seg, f.start, f.end)]
    return out


def raster_boxes_of(
    out_doc: Document, findings: list[Finding]
) -> dict[tuple[str, str | int], list[Any]]:
    out: dict[tuple[str, str | int], list[Any]] = {}
    for pairs in raster_boxes_by_finding(out_doc, findings).values():
        for key, box in pairs:
            out.setdefault((key[0], key[1]), []).append(tuple(box))
    return out
