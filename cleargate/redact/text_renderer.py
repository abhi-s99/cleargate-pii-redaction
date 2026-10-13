"""Span planning and the sanitized text renderer (TR-RD-30, ADR-07).

``span_plan`` turns findings into per-segment ``(start, end, token)`` replacements: only
findings the gate applies (``auto_redact`` and ``review``), nested spans dropped (the outer
span wins, e.g. a PERSON inside a HOME_ADDRESS), partial overlaps unioned. Writers and the
renderer use the same plan, so the file and the sanitized text always agree.

``render`` walks segments in ``order_index`` and substitutes tokens, with structural markers:
``[Page n]`` / ``[Slide n]``, ``#`` headings from ``heading_level``, table rows as pipe rows,
``[Image: n words OCR'd, k redactions]`` before an embedded image's text, ``[Image region
redacted: unreadable|photo]`` for masked regions, ``[Alt text: ...]`` and ``[Notes]``.
Metadata segments and generic-sweep blobs (no structural position) are not rendered. This
is the only artifact that may reach the AI.
"""

from __future__ import annotations

from collections import defaultdict

from cleargate.core.models import Document, EntityType, Finding, Segment

REDACTING = ("auto_redact", "review")
REGION_TYPES = (EntityType.PHOTO, EntityType.UNREADABLE_IMAGE_REGION)
Span = tuple[int, int, str]


def is_region(f: Finding) -> bool:
    return f.entity_type in REGION_TYPES


def span_plan(findings: list[Finding]) -> dict[str, list[Span]]:
    by_seg: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for f in findings:
        if f.decision in REDACTING and not is_region(f) and f.end > f.start:
            by_seg[f.segment_id].append((f.start, f.end, f.token or "[REDACTED]"))
    plan: dict[str, list[Span]] = {}
    for seg_id, spans in by_seg.items():
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        out: list[Span] = []
        for s, e, tok in spans:
            if out and s < out[-1][1]:
                ps, pe, ptok = out[-1]
                if e > pe:  # partial overlap: union, keep the earlier (outer) token
                    out[-1] = (ps, e, ptok)
                continue  # nested inside the previous span: the outer one wins
            out.append((s, e, tok))
        plan[seg_id] = out
    return plan


def apply_spans(text: str, spans: list[Span]) -> str:
    for s, e, tok in sorted(spans, reverse=True):
        text = text[:s] + tok + text[e:]
    return text


def sanitized_segment(seg: Segment, plan: dict[str, list[Span]]) -> str:
    return apply_spans(seg.text, plan.get(seg.segment_id, []))


def rendered(seg: Segment) -> bool:
    """Segments that carry document content (not metadata, not generic blobs)."""
    if seg.kind == "metadata" or seg.locator.part == "page-links":
        return False
    loc = seg.locator
    positional = (
        loc.page,
        loc.slide,
        loc.paragraph_index,
        loc.table,
        loc.bbox,
        loc.image_ref,
        loc.xpath,
    )
    return any(v is not None for v in positional)


def render(doc: Document, findings: list[Finding]) -> str:
    plan = span_plan(findings)
    regions_by_part: dict[tuple[str, int | None, int | None], list[Finding]] = defaultdict(list)
    for f in findings:
        if is_region(f) and f.decision in REDACTING and f.locator is not None:
            regions_by_part[(f.locator.part, f.locator.page, f.locator.slide)].append(f)
    image_words: dict[str, int] = defaultdict(int)
    image_redactions: dict[str, int] = defaultdict(int)
    for s in doc.segments:
        if s.kind == "ocr_line" and s.locator.part != "page":
            key = s.locator.image_ref or s.locator.part
            image_words[key] += len(s.text.split())
            image_redactions[key] += len(plan.get(s.segment_id, []))
    lines: list[str] = []
    marker: tuple[str, int] | None = None
    row_key: tuple[object, ...] | None = None
    row: list[str] = []
    seen_images: set[str] = set()
    emitted_regions: set[tuple[str, int | None, int | None]] = set()

    def flush_row() -> None:
        nonlocal row, row_key
        if row:
            lines.append("| " + " | ".join(c.replace("\n", " ") for c in row) + " |")
        row, row_key = [], None

    def regions_for(key: tuple[str, int | None, int | None]) -> None:
        if key in emitted_regions:
            return
        emitted_regions.add(key)
        for f in regions_by_part.get(key, []):
            kind = "photo" if f.entity_type is EntityType.PHOTO else "unreadable"
            lines.append(f"[Image region redacted: {kind}]")

    for seg in sorted(doc.segments, key=lambda s: s.order_index):
        if not rendered(seg):
            continue
        loc = seg.locator
        new_marker = ("Page", loc.page) if loc.page and loc.part.startswith("page") else None
        if loc.slide:
            new_marker = ("Slide", loc.slide)
        if new_marker and new_marker != marker:
            flush_row()
            lines.append(f"[{new_marker[0]} {new_marker[1]}]")
            marker = new_marker
            if new_marker[0] == "Page":
                regions_for(("page", loc.page, None))
        text = sanitized_segment(seg, plan)
        if seg.kind == "table_cell":
            rkey = (loc.part, loc.slide, loc.table, loc.row)
            if rkey != row_key:
                flush_row()
                row_key = rkey
            row.append(text)
            continue
        flush_row()
        if seg.kind == "ocr_line" and loc.part != "page":
            ref = loc.image_ref or loc.part
            if ref not in seen_images:
                seen_images.add(ref)
                lines.append(
                    f"[Image: {image_words[ref]} words OCR'd, {image_redactions[ref]} redactions]"
                )
                regions_for((loc.part, loc.page, loc.slide))
            lines.append(f"  {text}")
        elif seg.kind == "heading" and seg.heading_level:
            lines.append("#" * min(seg.heading_level, 6) + " " + text)
        elif seg.kind == "alt_text":
            lines.append(f"[Alt text: {text}]")
        elif seg.kind == "notes":
            lines.append(f"[Notes] {text}")
        else:
            lines.append(text)
    flush_row()
    for rk in regions_by_part:  # regions on images without any OCR text
        regions_for(rk)
    return "\n".join(lines).rstrip() + "\n"
