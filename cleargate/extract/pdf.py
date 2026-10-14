"""PDF extraction (TR-EX-01..08, ADR-03, D1-D5).

Per page: ``native_chars`` and ``image_coverage`` (union of image boxes / page area)
decide routing (TR-EX-02): OCR when ``native_chars < min_native_chars`` or coverage
> 0.60. OCR pages are rendered at ``policy.ocr.dpi`` and analysed (OCR, faces, ink,
regions) in a process pool, one page per task; native text on such pages is kept and
OCR lines overlapping it are dropped. Native pages give block segments, and every
embedded image of at least 120 x 120 px is OCR'd as a child part (TR-EX-03).

Also extracted: Info and XMP metadata (TR-EX-07), annotation text and authors, link
URIs, outline titles and form-field values. Embedded files cannot be inspected and are
registered as uninspected (``EMBEDDED_OBJECT``), which blocks the gate (G3).
"""

from __future__ import annotations

import multiprocessing
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf
from PIL import Image

from cleargate.core.errors import OcrError
from cleargate.core.limits import enforced, limit_memory
from cleargate.core.models import Document, FileFormat, Locator
from cleargate.extract.base import DocBuilder, analyse_raster
from cleargate.extract.image import (
    detect_faces,
    ink_ratio,
    nontext_regions,
    open_image,
    prepare_for_ocr,
)
from cleargate.extract.metadata import pdf_info, xmp_text
from cleargate.extract.ocr import OcrEngine, OcrResult

MIN_IMAGE_PX = 120
OCR_COVERAGE = 0.60
GRID = 120

pymupdf.TOOLS.mupdf_display_errors(False)


@dataclass
class PageAnalysis:
    index: int
    size: tuple[int, int]
    result: OcrResult | None
    error_code: str | None
    faces: list[tuple[int, int, int, int]]
    ink: float
    seconds: float
    nontext: list[tuple[tuple[int, int, int, int], list[float]]] | None = None


_WORKER_ENGINE: dict[tuple[Any, ...], OcrEngine] = {}


def analyse_page(args: tuple[Any, ...]) -> PageAnalysis:
    """Process-pool task: render one page, OCR it, detect faces. Picklable result."""
    pdf_path, index, dpi, cmd, cache_dir, cache_key, timeout, floor, area_ratio = args
    start = time.perf_counter()
    key = (cmd, cache_dir, timeout, floor)
    if key not in _WORKER_ENGINE:
        _WORKER_ENGINE[key] = OcrEngine(
            cmd,
            cache_dir=Path(cache_dir) if cache_dir else None,
            cache_key=cache_key,
            timeout_s=timeout,
            word_conf_floor=floor,
        )
    with pymupdf.open(pdf_path) as doc:
        pix = doc[index].get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    faces = detect_faces(img)
    ink = ink_ratio(img)
    result, code = None, None
    try:
        result = _WORKER_ENGINE[key].ocr(img, f"{dpi}dpi")
    except OcrError as exc:
        code = exc.code.value
    nontext = None
    if result is not None:
        boxes = [(w.box, w.text, w.conf) for line in result.lines for w in line.words]
        nontext = nontext_regions(img, boxes, min_area_ratio=area_ratio)
    return PageAnalysis(
        index, img.size, result, code, faces, ink, round(time.perf_counter() - start, 3), nontext
    )


def image_coverage(page: pymupdf.Page) -> float:
    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        return 0.0
    grid = np.zeros((GRID, GRID), dtype=bool)
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        c0 = int(max(0, (x0 - rect.x0) / rect.width * GRID))
        c1 = int(min(GRID, np.ceil((x1 - rect.x0) / rect.width * GRID)))
        r0 = int(max(0, (y0 - rect.y0) / rect.height * GRID))
        r1 = int(min(GRID, np.ceil((y1 - rect.y0) / rect.height * GRID)))
        grid[r0:r1, c0:c1] = True
    return float(grid.mean())


def native_blocks(page: pymupdf.Page) -> list[tuple[str, tuple[float, float, float, float]]]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        lines = ["".join(span["text"] for span in line["spans"]) for line in block["lines"]]
        text = "\n".join(ln for ln in lines if ln.strip())
        if text.strip():
            out.append((text, tuple(round(v, 2) for v in block["bbox"])))
    return out


def _overlap_share(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return ix * iy / area


class PdfExtractor:
    name = "pdf-extractor"
    version = "0.3.0"

    def supports(self, fmt: FileFormat) -> bool:
        return fmt is FileFormat.PDF

    def extract(self, path: Path, fmt: FileFormat, ctx: Any) -> Document:
        b = DocBuilder.for_job(ctx, path, fmt)
        b.doc.extractors[self.name] = self.version
        policy = ctx.policy
        dpi = policy.ocr.dpi
        with pymupdf.open(path) as doc:
            plan: list[tuple[int, int, float]] = []  # index, native_chars, coverage
            for i, page in enumerate(doc):
                chars = sum(1 for c in page.get_text("text") if not c.isspace())
                plan.append((i, chars, image_coverage(page)))
            ocr_pages = [
                i
                for i, chars, cov in plan
                if chars < policy.ocr.min_native_chars or cov > OCR_COVERAGE
            ]
            analyses = self._run_ocr(path, ocr_pages, ctx)
            seen_xrefs: set[int] = set()
            image_parts = 0
            for i, page in enumerate(doc):
                n = i + 1
                blocks = native_blocks(page)
                for text, bbox in blocks:
                    b.add("paragraph", text, Locator(part="page", page=n, bbox=bbox))
                if i in analyses:
                    self._add_ocr_page(b, analyses[i], n, blocks, dpi)
                else:
                    b.register(Locator(part="page", page=n), inspected=True)
                    image_parts += self._embedded_images(b, doc, page, n, seen_xrefs)
                self._page_extras(b, page, n)
            self._doc_extras(b, doc)
            b.doc.units = {
                "pages": doc.page_count,
                "ocr_pages": len(ocr_pages),
                "images": image_parts,
            }
        if analyses:
            secs = [a.seconds for a in analyses.values()]
            ctx.timings.update(
                {
                    "ocr_pages": float(len(secs)),
                    "ocr_page_sum_s": round(sum(secs), 2),
                    "ocr_page_p50_s": round(statistics.median(secs), 2),
                    "ocr_page_max_s": round(max(secs), 2),
                }
            )
        return b.build()

    # -------------------------------------------------------------- OCR pages

    def _run_ocr(self, path: Path, pages: list[int], ctx: Any) -> dict[int, PageAnalysis]:
        if not pages:
            return {}
        s, p = ctx.settings, ctx.policy
        args = [
            (
                str(path),
                i,
                p.ocr.dpi,
                s.tesseract_cmd,
                str(s.data_dir / "ocr_cache"),
                s.vault_key.get_secret_value() if s.vault_key else None,
                p.ocr.timeout_s_per_page,
                p.ocr.word_conf_floor,
                p.ocr.unreadable_region.min_area_ratio,
            )
            for i in pages
        ]
        workers = min(len(pages), max(1, s.ocr_workers))
        out: dict[int, PageAnalysis] = {}
        # Under a memory limit OCR always runs in worker processes, never in the service
        # process itself (TR-SEC-07, ADR-34).
        if workers == 1 and not (s.worker_mem_mb and enforced()):
            for done, a in enumerate(map(analyse_page, args), 1):
                out[a.index] = a
                ctx.report("ocr", done, len(pages))
            return out
        # "spawn" everywhere: a forked worker would inherit the service's address space
        # (spaCy loaded, several GB) and start above its RLIMIT_AS; forking from the API's
        # worker thread is unsafe as well (ADR-34).
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=limit_memory,
            initargs=(s.worker_mem_mb,),
        ) as pool:
            for done, a in enumerate(pool.map(analyse_page, args), 1):
                out[a.index] = a
                ctx.report("ocr", done, len(pages))
        return out

    def _add_ocr_page(
        self,
        b: DocBuilder,
        a: PageAnalysis,
        n: int,
        native: list[tuple[str, tuple[float, float, float, float]]],
        dpi: int,
    ) -> None:
        loc = Locator(part="page", page=n, image_ref="page-raster")
        result = a.result
        if result is not None and native:
            pt = 72.0 / dpi
            kept = [
                line
                for line in result.lines
                if not any(
                    _overlap_share(tuple(v * pt for v in line.box), bb) > 0.5 for _, bb in native
                )
            ]
            result = OcrResult(
                result.width,
                result.height,
                kept,
                result.blocks,
                result.engine,
                result.seconds,
                result.cached,
            )
        placeholder = Image.new("1", a.size)  # size only; analysis was done in the worker
        analyse_raster(
            b,
            placeholder,
            loc,
            dpi_tag=f"{dpi}dpi",
            require_text=True,
            result=result,
            error_code=a.error_code,
            faces=a.faces,
            ink=a.ink,
            nontext=a.nontext or [],
        )

    def _embedded_images(
        self, b: DocBuilder, doc: pymupdf.Document, page: pymupdf.Page, n: int, seen: set[int]
    ) -> int:
        count = 0
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if not xref or xref in seen:
                continue
            if info.get("width", 0) < MIN_IMAGE_PX or info.get("height", 0) < MIN_IMAGE_PX:
                continue
            seen.add(xref)
            loc = Locator(part="page-image", page=n, image_ref=f"xref:{xref}")
            try:
                img = open_image(doc.extract_image(xref)["image"])
            except Exception:  # undecodable image data
                b.register(loc, inspected=False, code="IMAGE_DECODE_FAILED")
                continue
            analyse_raster(b, img, loc, dpi_tag="native", prepare=prepare_for_ocr)
            count += 1
        return count

    # -------------------------------------------------------------- non-page text

    def _page_extras(self, b: DocBuilder, page: pymupdf.Page, n: int) -> None:
        annots = list(page.annots() or [])
        if annots:
            b.register(Locator(part="page-annots", page=n), inspected=True)
        for annot in annots:
            info = annot.info
            for key in ("content", "title", "subject"):
                b.add(
                    "paragraph" if key == "content" else "metadata",
                    info.get(key, ""),
                    Locator(part="page-annots", page=n, xpath=f"annot:{annot.xref}:{key}"),
                )
        for link in page.get_links():
            if link.get("uri"):
                b.add("paragraph", link["uri"], Locator(part="page-links", page=n, xpath="uri"))
        for widget in page.widgets() or []:
            for value in (widget.field_value, widget.field_label):
                if isinstance(value, str):
                    b.add(
                        "paragraph",
                        value,
                        Locator(part="page-widgets", page=n, xpath=f"field:{widget.field_name}"),
                    )

    def _doc_extras(self, b: DocBuilder, doc: pymupdf.Document) -> None:
        b.register(Locator(part="pdf:info"), inspected=True)
        for key, value in pdf_info(doc.metadata):
            b.add("metadata", value, Locator(part="pdf:info", xpath=key))
        xmp = doc.get_xml_metadata() or ""
        if xmp.strip():
            b.register(Locator(part="pdf:xmp"), inspected=True)
            for value in xmp_text(xmp):
                b.add("metadata", value, Locator(part="pdf:xmp"))
        for level, title, page_no, *_ in doc.get_toc(simple=True):
            b.add("heading", title, Locator(part="pdf:outline", page=page_no), heading_level=level)
        for i in range(doc.embfile_count()):
            b.register(Locator(part=f"pdf:embedded:{i}"), inspected=False, code="EMBEDDED_OBJECT")
