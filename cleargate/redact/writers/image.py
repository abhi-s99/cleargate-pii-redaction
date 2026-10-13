"""Raster redaction: burn filled rectangles into pixels (ADR-07, TR-RD-20, FR-18).

* ``span_boxes``: pixel boxes for a finding span on an OCR line, from the per-word boxes
  of the segment; words of one span on one line are merged into one rectangle.
* ``burn``: fill boxes (+padding) in black on an RGB copy.
* ``encode``: write the image back in its own format (PNG, JPEG, GIF, BMP, TIFF) with no
  metadata (EXIF, text chunks and ICC profiles are not carried over); EMF via a minimal
  EMF containing only the redacted bitmap, keeping the original frame size.
* ``ImageWriter``: standalone PNG/JPEG/TIFF files (all frames), EXIF stripped (FR-18).
"""

from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from cleargate.core.models import Document, Finding, Locator, RedactionAction, Segment
from cleargate.redact.text_renderer import is_region, render, span_plan

Box = tuple[float, float, float, float]
PIL_SAVE = {"PNG": "PNG", "JPEG": "JPEG", "MPO": "JPEG", "GIF": "GIF", "BMP": "BMP", "TIFF": "TIFF"}


def span_boxes(seg: Segment, start: int, end: int) -> list[Box]:
    """Union box of the words a ``[start, end)`` span touches on one OCR line."""
    boxes = seg.ocr_word_boxes or []
    words = seg.text.split(" ")
    if len(words) != len(boxes):
        return [seg.locator.bbox] if seg.locator.bbox else []
    hit: list[Box] = []
    pos = 0
    for word, box in zip(words, boxes, strict=True):
        w_start, w_end = pos, pos + len(word)
        if w_start < end and start < w_end:
            hit.append(box)
        pos = w_end + 1
    if not hit:
        return []
    return [
        (
            min(b[0] for b in hit),
            min(b[1] for b in hit),
            max(b[2] for b in hit),
            max(b[3] for b in hit),
        )
    ]


def burn(img: Image.Image, boxes: list[Box], pad: int) -> Image.Image:
    out = img.convert("RGB") if img.mode not in ("RGB", "L") else img.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    for x0, y0, x1, y1 in boxes:
        draw.rectangle(
            (max(0, x0 - pad), max(0, y0 - pad), min(w - 1, x1 + pad), min(h - 1, y1 + pad)),
            fill=0 if out.mode == "L" else (0, 0, 0),
        )
    return out


def encode(img: Image.Image, fmt: str | None, original: bytes) -> bytes | None:
    """Bytes in the source format, without metadata; None if the format cannot be written."""
    if _emf_frame(original):
        return emf_from_image(img, original)
    if not fmt:  # Pillow forgets the format of some decoded images (EMF/WMF): ask again
        try:
            with Image.open(io.BytesIO(original)) as probe:
                fmt = probe.format
        except Exception:  # not an image Pillow knows: cannot be rewritten
            return None
    fmt = (fmt or "").upper()
    buf = io.BytesIO()
    if fmt in ("WMF", "EMF"):  # Pillow names both "WMF"; only EMF can be rebuilt
        return emf_from_image(img, original) if _emf_frame(original) else None
    target = PIL_SAVE.get(fmt)
    if target is None:
        return None
    save_img = img
    if target == "JPEG":
        save_img = img.convert("RGB")
        save_img.save(buf, "JPEG", quality=90)
    elif target == "GIF":
        save_img.convert("P").save(buf, "GIF")
    else:
        save_img.save(buf, target)
    return buf.getvalue()


# --------------------------------------------------------------------- EMF


def _emf_frame(
    original: bytes,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
    """``(rclBounds, rclFrame)`` from an EMF header, or None if not an EMF."""
    if len(original) < 88 or struct.unpack_from("<I", original, 0)[0] != 1:
        return None
    if original[40:44] != b" EMF":
        return None
    bounds = struct.unpack_from("<4i", original, 8)
    frame = struct.unpack_from("<4i", original, 24)
    return bounds, frame


def emf_from_image(img: Image.Image, original: bytes) -> bytes | None:
    """A minimal EMF (header, one EMR_STRETCHDIBITS, EOF) showing ``img`` in the same frame."""
    header = _emf_frame(original)
    if header is None:
        return None
    bounds, frame = header
    rgb = img.convert("RGB")
    w, h = rgb.size
    row = (w * 3 + 3) & ~3
    pixels = bytearray()
    raw = rgb.tobytes()
    for y in range(h - 1, -1, -1):  # bottom-up DIB, BGR
        line = raw[y * w * 3 : (y + 1) * w * 3]
        bgr = bytearray(len(line))
        bgr[0::3], bgr[1::3], bgr[2::3] = line[2::3], line[1::3], line[0::3]
        pixels += bgr + b"\0" * (row - w * 3)
    bmi = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pixels), 0, 0, 0, 0)
    bx0, by0, bx1, by1 = bounds
    dest_w, dest_h = max(1, bx1 - bx0 + 1), max(1, by1 - by0 + 1)
    off_bmi = 80
    off_bits = off_bmi + len(bmi)
    size = off_bits + len(pixels)
    # EMR_STRETCHDIBITS (MS-EMF 2.3.1.7): 80-byte fixed part, then BITMAPINFOHEADER, bits.
    stretch = (
        struct.pack("<II", 81, size)
        + struct.pack("<4i", bx0, by0, bx1, by1)  # rclBounds
        + struct.pack("<6i", bx0, by0, 0, 0, w, h)  # xDest yDest xSrc ySrc cxSrc cySrc
        + struct.pack("<4I", off_bmi, len(bmi), off_bits, len(pixels))
        + struct.pack("<2I", 0, 0x00CC0020)  # DIB_RGB_COLORS, SRCCOPY
        + struct.pack("<2i", dest_w, dest_h)
        + bmi
        + bytes(pixels)
    )
    eof = struct.pack("<5I", 14, 20, 0, 16, 20)  # EMR_EOF
    n_bytes = 108 + len(stretch) + len(eof)
    fx0, fy0, fx1, fy1 = frame
    mm = (max(1, (fx1 - fx0) // 100), max(1, (fy1 - fy0) // 100))
    # EMR_HEADER with both extensions (108 bytes); device px per mm matches bounds / frame.
    hdr = (
        struct.pack("<II", 1, 108)
        + struct.pack("<4i", *bounds)
        + struct.pack("<4i", *frame)
        + struct.pack("<4I", 0x464D4520, 0x10000, n_bytes, 3)
        + struct.pack("<2H", 1, 0)
        + struct.pack("<3I", 0, 0, 0)
        + struct.pack("<2i", dest_w, dest_h)  # szlDevice
        + struct.pack("<2i", *mm)  # szlMillimeters
        + struct.pack("<3I", 0, 0, 0)
        + struct.pack("<2i", mm[0] * 1000, mm[1] * 1000)  # micrometers
    )
    return hdr + stretch + eof


# --------------------------------------------------------------------- standalone images


def raster_boxes(
    doc: Document,
    findings: list[Finding],
    part: str,
    page: int | None = None,
    image_ref: str | None = None,
) -> tuple[list[Box], list[str]]:
    """Boxes to burn on one raster: OCR word boxes of redacted spans plus region masks."""
    plan = span_plan(findings)
    segs = {s.segment_id: s for s in doc.segments}
    boxes: list[Box] = []
    ids: list[str] = []
    for f in findings:
        if f.decision not in ("auto_redact", "review"):
            continue
        if is_region(f):
            loc = f.locator
            if (
                loc
                and loc.part == part
                and (page is None or loc.page == page)
                and (image_ref is None or loc.image_ref == image_ref)
                and loc.bbox
            ):
                # Regions are estimates of an area, not word boxes: pad them by 1.5 % of
                # their size on each side so fuzzy edges are covered too.
                x0, y0, x1, y1 = loc.bbox
                mx, my = max(6.0, (x1 - x0) * 0.015), max(6.0, (y1 - y0) * 0.015)
                boxes.append((x0 - mx, y0 - my, x1 + mx, y1 + my))
                ids.append(f.finding_id)
            continue
        seg = segs.get(f.segment_id)
        if seg is None or seg.kind != "ocr_line" or seg.locator.part != part:
            continue
        if page is not None and seg.locator.page != page:
            continue
        if image_ref is not None and seg.locator.image_ref != image_ref:
            continue
        for s, e, _tok in plan.get(seg.segment_id, []):
            if s <= f.start and f.end <= e:
                found = span_boxes(seg, s, e)
                if found:
                    boxes.extend(found)
                    ids.append(f.finding_id)
                break
    return boxes, ids


class ImageWriter:
    name = "image-writer"
    version = "0.6.0"

    def apply(
        self, src: Path, doc: Document, findings: list[Finding], out_dir: Path, ctx: Any
    ) -> Any:
        from cleargate.pipeline import WriteResult

        pad = ctx.policy.redaction.pdf_padding_px
        out = out_dir / f"redacted{src.suffix.lower()}"
        actions: list[RedactionAction] = []
        frames = []
        with Image.open(src) as img:
            fmt = img.format
            for i in range(getattr(img, "n_frames", 1)):
                img.seek(i)
                boxes, ids = raster_boxes(doc, findings, "image", page=i + 1)
                frames.append(burn(img.copy(), boxes, pad))
                loc = Locator(part="image", page=i + 1, image_ref="image")
                actions += [
                    RedactionAction(
                        finding_ids=[fid], locator=loc, method="pixel_mask", applied=True
                    )
                    for fid in ids
                ]
        # EXIF and text chunks are never written back, so metadata findings are cleared.
        meta = {s.segment_id for s in doc.segments if s.locator.part == "image:exif"}
        actions += [
            RedactionAction(
                finding_ids=[f.finding_id],
                locator=Locator(part="image:exif"),
                method="metadata_clear",
                applied=True,
            )
            for f in findings
            if f.segment_id in meta and f.decision in ("auto_redact", "review")
        ]
        target = PIL_SAVE.get((fmt or "").upper(), "PNG")
        if target == "TIFF" and len(frames) > 1:
            frames[0].save(out, "TIFF", save_all=True, append_images=frames[1:])
        elif target == "JPEG":
            frames[0].convert("RGB").save(out, "JPEG", quality=90)
        else:
            frames[0].save(out, target)  # no exif/pnginfo passed: metadata stripped
        actions += unapplied_for_missing(doc, findings, actions)
        sanitized = out_dir / "sanitized.txt"
        sanitized.write_text(render(doc, findings), encoding="utf-8")
        return WriteResult(output_path=out, sanitized_path=sanitized, actions=actions)


def _loc() -> Any:
    from cleargate.core.models import Locator

    return Locator(part="image")


def unapplied_for_missing(
    doc: Document, findings: list[Finding], actions: list[RedactionAction]
) -> list[RedactionAction]:
    """Every redacting finding without an applied action gets an unapplied one (G4)."""
    done = {fid for a in actions if a.applied for fid in a.finding_ids}
    segs = {s.segment_id: s for s in doc.segments}
    out = []
    for f in findings:
        if f.decision in ("auto_redact", "review") and f.finding_id not in done:
            seg = segs.get(f.segment_id)
            loc = f.locator or (seg.locator if seg else _loc())
            out.append(
                RedactionAction(
                    finding_ids=[f.finding_id],
                    locator=loc,
                    method="token_replace",
                    token=f.token,
                    applied=False,
                    error_code="NOT_APPLIED",
                )
            )
    return out
