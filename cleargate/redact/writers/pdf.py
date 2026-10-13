"""Scanned and native PDF writers (TR-RD-20, TR-RD-21, TR-SEC-08, ADR-07).

Pages are routed exactly as extraction routed them (``extract.pdf`` rule):

* **raster pages** (scanned, or image-dominated): the page is rendered at ``ocr.dpi`` (the
  raster OCR saw, so word boxes line up), black rectangles are burned over the word boxes of
  redacted spans (+``pdf_padding_px``) and over masked regions, native text spans on the
  page are located with ``search_for`` and burned too; then everything on the page is
  removed (``apply_redactions`` with images removed) and the redacted raster becomes the
  only content, same mediabox. Original image XObjects do not survive (``garbage=4``).
* **native pages**: ``add_redact_annot`` per located span quad, embedded-image word boxes
  mapped to page space, ``apply_redactions(images=PDF_REDACT_IMAGE_PIXELS,
  graphics=PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)`` (TRD: ``..._LINE_ART_IF_TOUCHED``).

Then: annotations carrying findings are deleted and the author (``title``) of the rest
cleared; links whose URI carries a finding deleted; form values and outline titles
sanitized; Info cleared (``Producer`` = ``ClearGate``), XMP deleted, embedded files removed
(reported as masked parts); saved with ``garbage=4, deflate=True, clean=True``.
"""

from __future__ import annotations

import io
from collections import defaultdict
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from cleargate.core.models import Document, Finding, Locator, RedactionAction, Segment
from cleargate.extract.pdf import OCR_COVERAGE, image_coverage
from cleargate.redact.text_renderer import is_region, render, sanitized_segment, span_plan
from cleargate.redact.writers.image import burn, raster_boxes, unapplied_for_missing

REDACTING = ("auto_redact", "review")
PM: Any = pymupdf  # the stubs lack the redaction constants


def raster_pages(pdf: Any, min_native_chars: int) -> set[int]:
    out = set()
    for i, page in enumerate(pdf):
        chars = sum(1 for c in page.get_text("text") if not c.isspace())
        if chars < min_native_chars or image_coverage(page) > OCR_COVERAGE:
            out.add(i + 1)
    return out


def encode_page(img: Image.Image) -> bytes:
    """PNG for low-colour pages, JPEG q=85 otherwise (TR-RD-20)."""
    buf = io.BytesIO()
    small = img.copy()
    small.thumbnail((256, 256))
    colours = small.getcolors(maxcolors=64)
    if colours is not None:
        img.convert("P", palette=Image.Palette.ADAPTIVE, colors=64).save(buf, "PNG", optimize=True)
    else:
        img.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


def locate(page: Any, seg: Segment, start: int, end: int) -> list[Any]:
    """Rects of a native span: each line of the span searched inside the segment's block."""
    clip: Any = None
    if seg.locator.bbox:  # the segment's block, 2 pt larger on every side
        x0, y0, x1, y1 = seg.locator.bbox
        clip = pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
    rects: list[Any] = []
    for piece in seg.text[start:end].split("\n"):
        piece = piece.strip()
        if not piece:
            continue
        found = page.search_for(piece, clip=clip) if clip else page.search_for(piece)
        if not found:
            return []
        rects.extend(found)
    return rects


class PdfWriter:
    name = "pdf-writer"
    version = "0.6.0"

    def apply(
        self, src: Path, doc: Document, findings: list[Finding], out_dir: Path, ctx: Any
    ) -> Any:
        from cleargate.pipeline import WriteResult

        policy = ctx.policy
        dpi, pad = policy.ocr.dpi, policy.redaction.pdf_padding_px
        plan = span_plan(findings)
        segs = {s.segment_id: s for s in doc.segments}
        by_seg: dict[str, list[Finding]] = defaultdict(list)
        for f in findings:
            if f.decision in REDACTING and not is_region(f):
                by_seg[f.segment_id].append(f)
        actions: list[RedactionAction] = []
        masked: list[Locator] = []
        pdf: Any = pymupdf.open(src)
        try:
            rasters = raster_pages(pdf, policy.ocr.min_native_chars)
            for page in pdf:
                n = page.number + 1
                if n in rasters:
                    actions += self._raster_page(
                        page, n, doc, findings, plan, segs, by_seg, dpi, pad
                    )
                else:
                    actions += self._native_page(pdf, page, n, doc, findings, plan, segs, by_seg)
            actions += self._extras(pdf, doc, plan, segs, by_seg)
            for i in reversed(range(pdf.embfile_count())):
                pdf.embfile_del(i)
                masked.append(Locator(part=f"pdf:embedded:{i}"))
            pdf.set_metadata(
                {k: "" for k in ("author", "creator", "title", "subject", "keywords")}
                | {"producer": "ClearGate"}
            )
            pdf.del_xml_metadata()
            out = out_dir / "redacted.pdf"
            pdf.save(out, garbage=4, deflate=True, clean=True)
        finally:
            pdf.close()
        actions += unapplied_for_missing(doc, findings, actions)
        sanitized = out_dir / "sanitized.txt"
        sanitized.write_text(render(doc, findings), encoding="utf-8")
        return WriteResult(
            output_path=out, sanitized_path=sanitized, actions=actions, masked_parts=masked
        )

    # -------------------------------------------------------------- pages

    def _raster_page(
        self,
        page: Any,
        n: int,
        doc: Document,
        findings: list[Finding],
        plan: Any,
        segs: Any,
        by_seg: Any,
        dpi: int,
        pad: int,
    ) -> list[RedactionAction]:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        boxes, ids = raster_boxes(doc, findings, "page", page=n)
        native_ids: list[str] = []
        failed: list[str] = []
        scale = dpi / 72.0
        for seg_id, spans in plan.items():
            seg = segs.get(seg_id)
            if (
                seg is None
                or seg.locator.part != "page"
                or seg.locator.page != n
                or seg.method == "ocr"
            ):
                continue
            for s, e, _tok in spans:
                fids = [f.finding_id for f in by_seg[seg_id] if s <= f.start and f.end <= e]
                rects = locate(page, seg, s, e)
                (native_ids if rects else failed).extend(fids)
                boxes += [(r.x0 * scale, r.y0 * scale, r.x1 * scale, r.y1 * scale) for r in rects]
        out_img = burn(img, boxes, pad)
        page.add_redact_annot(page.rect, fill=(1, 1, 1))
        page.apply_redactions(
            images=PM.PDF_REDACT_IMAGE_REMOVE,
            graphics=PM.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
            text=PM.PDF_REDACT_TEXT_REMOVE,
        )
        page.insert_image(page.rect, stream=encode_page(out_img))
        loc = Locator(part="page", page=n, image_ref="page-raster")
        out = [
            RedactionAction(finding_ids=[i], locator=loc, method="pixel_mask", applied=True)
            for i in ids + native_ids
        ]
        out += [
            RedactionAction(
                finding_ids=[i],
                locator=loc,
                method="pixel_mask",
                applied=False,
                error_code="SPAN_NOT_LOCATED",
            )
            for i in failed
        ]
        return out

    def _native_page(
        self,
        pdf: Any,
        page: Any,
        n: int,
        doc: Document,
        findings: list[Finding],
        plan: Any,
        segs: Any,
        by_seg: Any,
    ) -> list[RedactionAction]:
        out: list[RedactionAction] = []
        touched = False
        for seg_id, spans in plan.items():
            seg = segs.get(seg_id)
            if seg is None or seg.locator.part != "page" or seg.locator.page != n:
                continue
            for s, e, _tok in spans:
                fids = [f.finding_id for f in by_seg[seg_id] if s <= f.start and f.end <= e]
                rects = locate(page, seg, s, e)
                for r in rects:
                    page.add_redact_annot(r, fill=(0, 0, 0))
                touched = touched or bool(rects)
                out.append(
                    RedactionAction(
                        finding_ids=fids,
                        locator=seg.locator,
                        method="token_replace",
                        applied=bool(rects),
                        error_code=None if rects else "SPAN_NOT_LOCATED",
                    )
                )
        refs = {
            s.locator.image_ref
            for s in doc.segments
            if s.locator.part == "page-image" and s.locator.page == n
        }
        refs |= {
            f.locator.image_ref
            for f in findings
            if is_region(f) and f.locator and f.locator.part == "page-image" and f.locator.page == n
        }
        for ref in sorted(r for r in refs if r):
            boxes, ids = raster_boxes(doc, findings, "page-image", page=n, image_ref=ref)
            if not boxes:
                continue
            xref = int(ref.split(":", 1)[1])
            info = pdf.extract_image(xref)
            w, h = info["width"], info["height"]
            placements = page.get_image_rects(xref)
            for rect in placements:
                sx, sy = rect.width / w, rect.height / h
                for x0, y0, x1, y1 in boxes:
                    page.add_redact_annot(
                        pymupdf.Rect(
                            rect.x0 + x0 * sx,
                            rect.y0 + y0 * sy,
                            rect.x0 + x1 * sx,
                            rect.y0 + y1 * sy,
                        ),
                        fill=(0, 0, 0),
                    )
            touched = touched or bool(placements)
            loc = Locator(part="page-image", page=n, image_ref=ref)
            out += [
                RedactionAction(
                    finding_ids=[i], locator=loc, method="pixel_mask", applied=bool(placements)
                )
                for i in ids
            ]
        if touched:
            page.apply_redactions(
                images=PM.PDF_REDACT_IMAGE_PIXELS,
                graphics=PM.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
            )
        return out

    # -------------------------------------------------------------- annotations, links, forms

    def _extras(
        self, pdf: Any, doc: Document, plan: Any, segs: Any, by_seg: Any
    ) -> list[RedactionAction]:
        out: list[RedactionAction] = []
        hit = {sid for sid in plan if sid in segs}
        for page in pdf:
            n = page.number + 1
            annot_hits = {
                segs[sid].locator.xpath.split(":")[1]
                for sid in hit
                if segs[sid].locator.part == "page-annots"
                and segs[sid].locator.page == n
                and segs[sid].locator.xpath
            }
            for annot in list(page.annots() or []):
                if str(annot.xref) in annot_hits:
                    page.delete_annot(annot)
                else:
                    annot.set_info(title="")
                    annot.update()
            link_hits = {
                segs[sid].text
                for sid in hit
                if segs[sid].locator.part == "page-links" and segs[sid].locator.page == n
            }
            for link in page.get_links():
                if link.get("uri") in link_hits:
                    page.delete_link(link)
            widget_segs = {
                segs[sid].locator.xpath: segs[sid]
                for sid in hit
                if segs[sid].locator.part == "page-widgets" and segs[sid].locator.page == n
            }
            for widget in page.widgets() or []:
                seg = widget_segs.get(f"field:{widget.field_name}")
                if (
                    seg is not None
                    and isinstance(widget.field_value, str)
                    and widget.field_value == seg.text
                ):
                    widget.field_value = sanitized_segment(seg, plan)
                    widget.update()
        outline = {
            segs[sid].text: sanitized_segment(segs[sid], plan)
            for sid in hit
            if segs[sid].locator.part == "pdf:outline"
        }
        if outline:
            toc = pdf.get_toc(simple=False)
            pdf.set_toc(
                [[lvl, outline.get(title, title), pno, *rest] for lvl, title, pno, *rest in toc]
            )
        for sid in hit:
            seg = segs[sid]
            if seg.locator.part in (
                "page-annots",
                "page-links",
                "page-widgets",
                "pdf:outline",
                "pdf:info",
                "pdf:xmp",
            ):
                out.append(
                    RedactionAction(
                        finding_ids=[f.finding_id for f in by_seg[sid]],
                        locator=seg.locator,
                        method="metadata_clear"
                        if seg.locator.part.startswith("pdf:")
                        else "remove_part",
                        applied=True,
                    )
                )
        return out
