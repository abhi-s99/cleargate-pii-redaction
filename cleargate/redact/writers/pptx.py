"""PPTX in-place run-level writer (TR-RD-10, TR-RD-11).

Locators: slide shapes carry the shape element path plus ``paragraph_index`` (text frames)
or ``row``/``col`` (tables); notes carry the notes part, ``shape_id`` and
``paragraph_index``; alt text sits on the shape's ``cNvPr``. Chart text (no paragraph
index) is left to the shared value sweep. Everything else is shared with DOCX.
"""

from __future__ import annotations

from lxml import etree

from cleargate.core.models import FileFormat, Segment
from cleargate.extract.textmap import A, Piece, drawing_body, drawing_paragraph, generic, q
from cleargate.redact.writers.ooxml import OoxmlWriter, Package, find

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_P, A_TBL, A_TR, A_TC = q(A, "p"), q(A, "tbl"), q(A, "tr"), q(A, "tc")


def _tx_paragraphs(shape: etree._Element) -> list[etree._Element]:
    body = shape.find(".//{*}txBody")
    return body.findall(A_P) if body is not None else []


def _shape_by_id(root: etree._Element, shape_id: int) -> etree._Element | None:
    for cnv in root.iter("{*}cNvPr"):
        if cnv.get("id") == str(shape_id):
            nv = cnv.getparent()
            return nv.getparent() if nv is not None else None
    return None


class PptxWriter(OoxmlWriter):
    name = "pptx-writer"
    version = "0.6.0"

    def supports(self, fmt: FileFormat) -> bool:
        return fmt is FileFormat.PPTX

    def alt_text_element(self, pkg: Package, seg: Segment, path: str) -> etree._Element | None:
        root = pkg.tree(seg.locator.part)
        shape = find(root, path) if root is not None else None
        return shape.find(".//{*}cNvPr") if shape is not None else None

    def segment_pieces(self, pkg: Package, seg: Segment) -> list[Piece] | None:
        loc = seg.locator
        root = pkg.tree(loc.part)
        if root is None:
            return None
        if seg.kind == "notes" and loc.shape_id is not None:
            shape = _shape_by_id(root, loc.shape_id)
        elif loc.xpath:
            shape = find(root, loc.xpath)
        else:
            return generic(root)
        if shape is None:
            return None
        if seg.kind == "table_cell" and loc.row is not None and loc.col is not None:
            tbl = shape.find(".//" + A_TBL)
            rows = tbl.findall(A_TR) if tbl is not None else []
            if loc.row >= len(rows):
                return None
            cells = rows[loc.row].findall(A_TC)
            if loc.col >= len(cells):
                return None
            body = cells[loc.col].find("{*}txBody")
            return drawing_body(body) if body is not None else None
        if loc.paragraph_index is None:
            return None  # chart text: handled by the value sweep
        paras = _tx_paragraphs(shape)
        if loc.paragraph_index >= len(paras):
            return None
        return drawing_paragraph(paras[loc.paragraph_index])
