"""Shared extractor machinery (TRD 5, TR-EX-40, ADR-02).

``DocBuilder`` builds a ``Document``: segments get ids ``{doc_id}:{order_index}`` in
global reading order; every part is registered in ``Coverage``.

``analyse_raster`` is the single place where a raster (scanned page, embedded image,
standalone image) becomes OCR segments, face regions, unreadable regions and a
coverage entry. Rules (fail closed):

* OCR unavailable or timed out: the part is uninspected with that code;
* all recognised words lie in unreadable blocks: uninspected, ``OCR_UNREADABLE``;
* ``require_text`` (scanned PDF pages): visible ink but no words is uninspected,
  ``OCR_NO_TEXT`` (Architecture D1: an image page with no text is not "PII-free");
* otherwise inspected. Face and unreadable regions are recorded either way.

Index conventions: ``page`` and ``slide`` are 1-based (TRD 4); ``table``, ``row``,
``col`` and ``paragraph_index`` are 0-based. Raster ``bbox`` values are pixels of the
source raster (before any OCR upscaling).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image

from cleargate.core.config import Policy, Settings
from cleargate.core.errors import OcrError
from cleargate.core.models import (
    Document,
    FileFormat,
    Locator,
    Region,
    Segment,
    SegmentKind,
)
from cleargate.extract.ocr import OcrEngine, OcrResult, unreadable_blocks
from cleargate.ingest.validator import sha256_file

if TYPE_CHECKING:
    from cleargate.pipeline import JobContext

_ENGINES: dict[tuple[str | None, str, int], OcrEngine] = {}


def engine_for(settings: Settings, policy: Policy) -> OcrEngine:
    """One OCR engine per (binary, cache dir, timeout) per process."""
    cache_dir = settings.data_dir / "ocr_cache"
    key = (settings.tesseract_cmd, str(cache_dir), policy.ocr.timeout_s_per_page)
    if key not in _ENGINES:
        _ENGINES[key] = OcrEngine(
            settings.tesseract_cmd,
            cache_dir=cache_dir,
            cache_key=settings.vault_key.get_secret_value() if settings.vault_key else None,
            timeout_s=policy.ocr.timeout_s_per_page,
            word_conf_floor=policy.ocr.word_conf_floor,
        )
    return _ENGINES[key]


class DocBuilder:
    def __init__(self, doc: Document, engine: OcrEngine, policy: Policy) -> None:
        self.doc = doc
        self.engine = engine
        self.policy = policy
        self.timings: dict[str, float] = {}

    @classmethod
    def for_job(cls, ctx: JobContext | Any, path: Path, fmt: FileFormat) -> DocBuilder:
        doc = Document(
            doc_id=ctx.job_id,
            filename=path.name,
            sha256=sha256_file(path),
            fmt=fmt,
            size_bytes=path.stat().st_size,
        )
        return cls(doc, engine_for(ctx.settings, ctx.policy), ctx.policy)

    def add(
        self,
        kind: SegmentKind,
        text: str,
        locator: Locator,
        *,
        method: str = "native",
        heading_level: int | None = None,
        ocr_word_conf: list[float] | None = None,
        ocr_word_boxes: list[tuple[float, float, float, float]] | None = None,
        parent_id: str | None = None,
    ) -> str | None:
        """Append a segment in reading order; whitespace-only text is skipped."""
        if not text or not text.strip():
            return None
        idx = len(self.doc.segments)
        seg_id = f"{self.doc.doc_id}:{idx}"
        self.doc.segments.append(
            Segment(
                segment_id=seg_id,
                kind=kind,
                text=text,
                order_index=idx,
                heading_level=heading_level,
                locator=locator,
                method="ocr" if method == "ocr" else "native",
                ocr_word_conf=ocr_word_conf,
                ocr_word_boxes=ocr_word_boxes,
                parent_id=parent_id,
            )
        )
        return seg_id

    def register(self, locator: Locator, *, inspected: bool, code: str | None = None) -> None:
        self.doc.coverage.register(locator, inspected=inspected, code=code)

    def build(self) -> Document:
        return self.doc


def ocr_segments(
    b: DocBuilder, result: OcrResult, locator: Locator, scale: float, parent_id: str | None
) -> int:
    """Turn OCR lines into ``ocr_line`` segments (boxes mapped back to source pixels)."""
    count = 0
    for line in result.lines:
        box = tuple(round(v / scale, 1) for v in line.box)
        words = [tuple(round(v / scale, 1) for v in w.box) for w in line.words]
        if b.add(
            "ocr_line",
            line.text,
            locator.model_copy(update={"bbox": box}),
            method="ocr",
            ocr_word_conf=line.confs,
            ocr_word_boxes=words,  # type: ignore[arg-type]
            parent_id=parent_id,
        ):
            count += 1
    return count


def analyse_raster(
    b: DocBuilder,
    image: Image.Image,
    locator: Locator,
    *,
    dpi_tag: str,
    prepare: Callable[[Image.Image], Image.Image] | None = None,
    parent_id: str | None = None,
    require_text: bool = False,
    result: OcrResult | None = None,
    error_code: str | None = None,
    faces: list[tuple[int, int, int, int]] | None = None,
    ink: float | None = None,
    nontext: list[tuple[tuple[int, int, int, int], list[float]]] | None = None,
) -> OcrResult | None:
    """OCR + faces + regions + coverage for one raster. See module docstring.

    ``result``/``error_code``/``faces``/``ink`` may be precomputed (process pool).
    """
    from cleargate.extract.image import detect_faces, ink_ratio, nontext_regions

    src_w, src_h = image.size
    area = max(src_w * src_h, 1)
    ocr_img = prepare(image) if prepare else image
    scale = ocr_img.width / src_w if src_w else 1.0
    if faces is None:
        faces = detect_faces(image)
    for box in faces:
        b.doc.regions.append(
            Region(
                kind="face",
                locator=locator.model_copy(update={"bbox": tuple(map(float, box))}),
                area_ratio=min(1.0, (box[2] - box[0]) * (box[3] - box[1]) / area),
            )
        )
    if result is None and error_code is None:
        try:
            result = b.engine.ocr(ocr_img, dpi_tag)
        except OcrError as exc:
            error_code = exc.code.value
    if result is None:
        b.register(locator, inspected=False, code=error_code or "OCR_FAILED")
        return None
    ocr_segments(b, result, locator, scale, parent_id)
    cfg = b.policy.ocr.unreadable_region
    bad = unreadable_blocks(
        result, min_area_ratio=cfg.min_area_ratio, max_mean_conf=cfg.max_mean_conf
    )
    for blk in bad:
        rbox = tuple(round(v / scale, 1) for v in blk.box)
        b.doc.regions.append(
            Region(
                kind="unreadable",
                locator=locator.model_copy(update={"bbox": rbox}),
                area_ratio=min(
                    1.0,
                    (blk.box[2] - blk.box[0])
                    * (blk.box[3] - blk.box[1])
                    / max(result.width * result.height, 1),
                ),
                mean_conf=round(blk.mean_conf, 1),
                word_count=blk.words,
            )
        )
    if require_text:
        # TR-EX-05 second clause, scanned pages only: connected non-text regions.
        if nontext is None:
            boxes = [(w.box, w.text, w.conf) for line in result.lines for w in line.words]
            nontext = nontext_regions(image, boxes, min_area_ratio=cfg.min_area_ratio)
        floor = b.policy.ocr.word_conf_floor
        for box, confs in nontext:
            mean = sum(confs) / len(confs) if confs else None
            low = sum(1 for c in confs if c < floor) / len(confs) if confs else 1.0
            if mean is None or mean < cfg.max_mean_conf or low >= 0.4:
                b.doc.regions.append(
                    Region(
                        kind="unreadable",
                        locator=locator.model_copy(update={"bbox": tuple(map(float, box))}),
                        area_ratio=min(1.0, (box[2] - box[0]) * (box[3] - box[1]) / area),
                        mean_conf=round(mean, 1) if mean is not None else None,
                        word_count=len(confs),
                    )
                )
    words = result.word_count
    bad_words = sum(blk.words for blk in bad)
    has_ink = words == 0 and (ink if ink is not None else ink_ratio(image)) > 0.01
    if words and bad_words == words:
        b.register(locator, inspected=False, code="OCR_UNREADABLE")
    elif require_text and has_ink:
        b.register(locator, inspected=False, code="OCR_NO_TEXT")
    else:
        if has_ink and not faces:
            # An embedded picture with visible content but no recognised words could hold
            # text OCR cannot read: mask it whole and send it to review (ADR-27).
            b.doc.regions.append(
                Region(
                    kind="unreadable",
                    locator=locator.model_copy(
                        update={"bbox": (0.0, 0.0, float(src_w), float(src_h))}
                    ),
                    area_ratio=1.0,
                    mean_conf=None,
                    word_count=0,
                )
            )
        b.register(locator, inspected=True)
    return result
