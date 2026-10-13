"""DOCX in-place run-level writer (TR-RD-10, TR-RD-11).

Segment locators carry the element path of their ``w:p`` (paragraphs, headings, list
items, headers, footers, footnotes, comments, text-box paragraphs) or ``w:tc`` (table
cells); the writer maps the finding offsets onto the same text pieces extraction used
(``extract.textmap``). Generic-sweep segments (parts without a structured walker) map onto
the part's text nodes. Everything else is shared with PPTX (``ooxml.OoxmlWriter``).
"""

from __future__ import annotations

from cleargate.core.models import FileFormat, Segment
from cleargate.extract.textmap import (
    W_P,
    Piece,
    docx_cell,
    docx_paragraph,
    generic,
    q,
)
from cleargate.redact.writers.ooxml import OoxmlWriter, Package, find

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_TC = q(W, "tc")


class DocxWriter(OoxmlWriter):
    name = "docx-writer"
    version = "0.6.0"

    def supports(self, fmt: FileFormat) -> bool:
        return fmt is FileFormat.DOCX

    def segment_pieces(self, pkg: Package, seg: Segment) -> list[Piece] | None:
        root = pkg.tree(seg.locator.part)
        if root is None:
            return None
        if not seg.locator.xpath:
            return generic(root)
        el = find(root, seg.locator.xpath)
        if el is None:
            return None
        if el.tag == W_P:
            return docx_paragraph(el)
        if el.tag == W_TC:
            return docx_cell(el)
        return None
