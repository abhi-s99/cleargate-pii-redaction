"""Separate re-extraction path for outputs (TRD 8.1 V1/V2, ADR-08).

This path does not use the structured extractors: it reads the **output file** raw.

* ``reopen``: V1, the format library **and** a second parser must open it (PDF: PyMuPDF and
  pdfplumber with equal page counts; DOCX/PPTX: python-docx/python-pptx and a zip + lxml
  parse of every XML part; images: Pillow verify and full decode).
* ``haystacks``: every text the output contains, for the V2 leak search. OOXML: all text
  nodes of every XML part (one string per part), each ``w:p``/``a:p`` as a joined paragraph
  (values split across runs), every attribute value, and OCR of every output media image.
  PDF: PyMuPDF text, pdfplumber text, annotation fields, link URIs, form values, outline,
  Info and XMP, and OCR of every page raster at ``verify_ocr_dpi``. Images: OCR of every
  frame and any text metadata left in the file.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf
from lxml import etree
from PIL import Image

from cleargate.core.errors import OcrError
from cleargate.core.models import FileFormat
from cleargate.extract.base import engine_for
from cleargate.extract.image import open_image, prepare_for_ocr
from cleargate.extract.ocr import OcrResult
from cleargate.extract.textmap import A_P, W_P, docx_paragraph, drawing_paragraph, text_of
from cleargate.extract.xml import SAFE

RASTER_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf")


def reopen(path: Path, fmt: FileFormat) -> bool:
    try:
        if fmt is FileFormat.PDF:
            with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
                pages = pdf.page_count
            with pdfplumber.open(path) as plumb:
                return bool(pages > 0 and len(plumb.pages) == pages)
        if fmt in (FileFormat.DOCX, FileFormat.PPTX):
            if fmt is FileFormat.DOCX:
                from docx import Document as Docx

                Docx(str(path))
            else:
                from pptx import Presentation

                Presentation(str(path))
            with zipfile.ZipFile(path) as zf:
                if zf.testzip() is not None:
                    return False
                for name in zf.namelist():
                    if name.endswith((".xml", ".rels")):
                        etree.fromstring(zf.read(name), parser=SAFE)
            return True
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            img.load()
        return True
    except Exception:  # any failure to reopen is a V1 failure
        return False


@dataclass
class RasterOcr:
    """OCR of one output raster, kept so V2 hits can be located (repair pass, ADR-30)."""

    key: tuple[str, str | int]  # ("page", n) | ("media", part) | ("image", frame)
    result: OcrResult
    scale: float  # OCR raster px / source raster px


RASTERS: dict[str, list[RasterOcr]] = {}  # job_id -> rasters of the last haystack read


def _ocr_text(
    img: Image.Image,
    ctx: Any,
    tag: str,
    key: tuple[str, str | int] | None = None,
    scale: float = 1.0,
) -> tuple[str | None, int]:
    """OCR text of a raster, or ``(None, 1)`` when OCR is unavailable (uninspected)."""
    engine = engine_for(ctx.settings, ctx.policy)
    try:
        result = engine.ocr(img, tag)
    except OcrError:
        return None, 1
    if key is not None:
        RASTERS.setdefault(ctx.job_id, []).append(RasterOcr(key, result, scale))
    return "\n".join(line.text for line in result.lines), 0


def haystacks(path: Path, fmt: FileFormat, ctx: Any) -> tuple[list[str], int]:
    """Output texts and the number of rasters that could not be OCR'd."""
    RASTERS[ctx.job_id] = []
    if fmt is FileFormat.PDF:
        return _pdf(path, ctx)
    if fmt in (FileFormat.DOCX, FileFormat.PPTX):
        return _ooxml(path, ctx)
    out: list[str] = []
    missed = 0
    with Image.open(path) as img:
        out += [str(v) for v in (img.info or {}).values() if isinstance(v, str)]
        exif = img.getexif()
        out += [str(v) for v in exif.values() if isinstance(v, str | bytes)]
        for i in range(getattr(img, "n_frames", 1)):
            img.seek(i)
            frame = img.copy()
            prepared = prepare_for_ocr(frame)
            text, miss = _ocr_text(
                prepared, ctx, "verify-native", ("image", i + 1), prepared.width / frame.width
            )
            missed += miss
            out.append(text or "")
    return out, missed


def _ooxml(path: Path, ctx: Any) -> tuple[list[str], int]:
    out: list[str] = []
    missed = 0
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            data = zf.read(name)
            if name.endswith((".xml", ".rels", ".vml")):
                root = etree.fromstring(data, parser=SAFE)
                out.append("\n".join(t for t in root.itertext() if t.strip()))
                out.extend(text_of(docx_paragraph(p)) for p in root.iter(W_P))
                out.extend(text_of(drawing_paragraph(p)) for p in root.iter(A_P))
                out.extend(
                    v for el in root.iter() if isinstance(el.tag, str) for v in el.attrib.values()
                )
            elif name.lower().endswith(RASTER_EXT):
                try:
                    img = open_image(data)
                except Exception:  # unreadable output image: counted as not inspected
                    missed += 1
                    continue
                prepared = prepare_for_ocr(img)
                text, miss = _ocr_text(
                    prepared, ctx, "verify-native", ("media", name), prepared.width / img.width
                )
                missed += miss
                out.append(text or "")
            elif name.lower().endswith(".svg"):
                out.append(data.decode("utf-8", "ignore"))
    return out, missed


def _pdf(path: Path, ctx: Any) -> tuple[list[str], int]:
    out: list[str] = []
    missed = 0
    dpi = ctx.policy.verification.verify_ocr_dpi
    with pymupdf.open(path) as pdf:  # type: ignore[no-untyped-call]
        out += [str(v) for v in (pdf.metadata or {}).values() if v]
        out.append(pdf.get_xml_metadata() or "")
        out += [str(t[1]) for t in pdf.get_toc(simple=True)]
        for page in pdf:
            out.append(page.get_text("text"))
            for annot in page.annots() or []:
                out += [str(v) for v in annot.info.values() if v]
            out += [str(link.get("uri")) for link in page.get_links() if link.get("uri")]
            out += [str(w.field_value) for w in page.widgets() or [] if w.field_value]
            if page.get_images():
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                text, miss = _ocr_text(img, ctx, f"{dpi}dpi", ("page", page.number + 1))
                missed += miss
                out.append(text or "")
    with pdfplumber.open(path) as plumb:
        out += [p.extract_text() or "" for p in plumb.pages]
    return out, missed


def image_bytes_equal(a: bytes, b: bytes) -> bool:
    return io.BytesIO(a).getvalue() == io.BytesIO(b).getvalue()
