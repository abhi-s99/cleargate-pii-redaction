"""Verification repair pass (ADR-30).

When V2 finds a redacted value in the OCR of an output raster (Tesseract read pixels
differently once masks changed the page layout), the verifier reports the word boxes of the
hit. ``repair_output`` burns those boxes into the same raster of the output file, then the
pipeline verifies the repaired file again from scratch. Text-layer leaks (XML, PDF text,
sanitized text) are never "repaired" here: they keep the gate at G1.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from cleargate.core.models import FileFormat
from cleargate.extract.image import open_image
from cleargate.redact.writers.image import PIL_SAVE, burn, encode
from cleargate.redact.writers.ooxml import Package
from cleargate.redact.writers.pdf import encode_page

PM: Any = pymupdf  # the stubs lack the redaction constants
Boxes = dict[tuple[str, Any], list[tuple[float, float, float, float]]]


def repair_output(path: Path, fmt: FileFormat, boxes: Boxes, ctx: Any) -> int:
    pad = ctx.policy.redaction.pdf_padding_px
    tmp = path.with_name(path.stem + ".repair" + path.suffix)
    burned = 0
    if fmt is FileFormat.PDF:
        dpi = ctx.policy.verification.verify_ocr_dpi
        pdf: Any
        with pymupdf.open(path) as pdf:
            for (kind, n), bxs in boxes.items():
                if kind != "page" or not bxs:
                    continue
                page = pdf[int(n) - 1]
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                img = burn(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), bxs, pad)
                page.add_redact_annot(page.rect, fill=(1, 1, 1))
                page.apply_redactions(
                    images=PM.PDF_REDACT_IMAGE_REMOVE, text=PM.PDF_REDACT_TEXT_REMOVE
                )
                page.insert_image(page.rect, stream=encode_page(img))
                burned += len(bxs)
            pdf.save(tmp, garbage=4, deflate=True, clean=True)
    elif fmt in (FileFormat.DOCX, FileFormat.PPTX):
        pkg = Package(path)
        written: dict[bytes, bytes] = {}
        for (kind, part), bxs in boxes.items():
            if kind != "media" or not bxs or part not in pkg.data:
                continue
            original = pkg.data[part]
            new = encode(burn(open_image(original), bxs, pad), None, original)
            if new is not None:
                pkg.data[part] = new
                written[original] = new
                burned += len(bxs)
        for name in pkg.names():
            if pkg.data.get(name) in written:
                pkg.data[name] = written[pkg.data[name]]
        pkg.save(tmp)
    else:
        with Image.open(path) as img:
            target = PIL_SAVE.get((img.format or "").upper(), "PNG")
            frames = []
            for i in range(getattr(img, "n_frames", 1)):
                img.seek(i)
                bxs = boxes.get(("image", i + 1), [])
                frames.append(burn(img.copy(), bxs, pad))
                burned += len(bxs)
        buf = io.BytesIO()
        if target == "TIFF" and len(frames) > 1:
            frames[0].save(buf, "TIFF", save_all=True, append_images=frames[1:])
        elif target == "JPEG":
            frames[0].convert("RGB").save(buf, "JPEG", quality=90)
        else:
            frames[0].save(buf, target)
        tmp.write_bytes(buf.getvalue())
    os.replace(tmp, path)
    return burned
