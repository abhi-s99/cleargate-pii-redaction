"""V4 coverage (TRD 8.1).

* every uninspected source part must have been removed or masked by the writer;
* every part of the re-extracted output must itself be inspected (a redacted image the
  verifier cannot read is not "clean");
* unit counts must be unchanged: pages (PDF), slides (PPTX), paragraphs, tables and images
  (DOCX), frames (images).
"""

from __future__ import annotations

from cleargate.core.models import Document, FileFormat, Locator

UNIT_KEYS = {
    FileFormat.PDF: ("pages",),
    FileFormat.PPTX: ("slides", "tables"),
    FileFormat.DOCX: ("paragraphs", "tables", "images"),
    FileFormat.PNG: ("images",),
    FileFormat.JPEG: ("images",),
    FileFormat.TIFF: ("images",),
}


# On a raster the writer burned masks into, OCR reads the black boxes as low-confidence
# noise, so the output part can look "unreadable" or "no text". The verifier still OCR'd it
# and searched it (V2); that classification is an effect of the masks (ADR-30). Other
# codes (OCR unavailable, timeout, undecodable image) always count.
MASK_EFFECT_CODES = frozenset({"OCR_UNREADABLE", "OCR_NO_TEXT"})


def uninspected_unmasked(
    src: Document,
    out: Document | None,
    masked: list[Locator],
    masked_rasters: set[str] | None = None,
) -> int:
    masked_set = set(masked)
    count = sum(1 for loc in src.coverage.uninspected if loc not in masked_set)
    if out is not None:
        rasters = masked_rasters or set()
        for issue in out.coverage.issues:
            loc = issue.locator
            key = f"{loc.part}:{loc.page}" if loc.part == "page" else loc.part
            if issue.code in MASK_EFFECT_CODES and key in rasters:
                continue
            count += 1
    return count


def units_equal(src: Document, out: Document | None) -> bool:
    if out is None:
        return False
    keys = UNIT_KEYS.get(src.fmt, ())
    return all(src.units.get(k) == out.units.get(k) for k in keys)
