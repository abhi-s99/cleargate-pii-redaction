"""Text-to-node maps shared by the OOXML extractors and writers (TRD 5, TR-RD-10).

A segment's text is the concatenation of ``Piece.text`` values. Editable pieces point at the
XML node that holds the text (``el.text``, ``el.tail`` or an attribute); separator pieces
(tabs, breaks, the ``\\n`` between cell paragraphs) are not editable. Because extraction
builds the segment text from the same pieces, a finding's ``(start, end)`` offsets map onto
the exact nodes the writer must change, across any number of runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


W_P, W_TXBX, MC_FALLBACK = q(W, "p"), q(W, "txbxContent"), q(MC, "Fallback")
W_TEXT = {q(W, "t"), q(W, "delText"), q(W, "instrText")}
W_BREAK = {
    q(W, "br"): "\n",
    q(W, "cr"): "\n",
    q(W, "tab"): "\t",
    q(W, "noBreakHyphen"): "-",
    q(W, "softHyphen"): "",
}
A_P, A_R, A_FLD, A_BR, A_T = q(A, "p"), q(A, "r"), q(A, "fld"), q(A, "br"), q(A, "t")


@dataclass
class Piece:
    el: etree._Element | None
    slot: Literal["text", "tail"] | None
    text: str
    lead: int = 0  # characters stripped from the node text before this piece (generic parts)

    @property
    def editable(self) -> bool:
        return self.el is not None


def text_of(pieces: list[Piece]) -> str:
    return "".join(p.text for p in pieces)


def in_fallback(el: etree._Element, stop: etree._Element | None = None) -> bool:
    for anc in el.iterancestors():
        if anc is stop:
            return False
        if anc.tag == MC_FALLBACK:
            return True
    return False


def nearest(el: etree._Element, tag: str) -> etree._Element | None:
    for anc in el.iterancestors(tag):
        return anc
    return None


# --------------------------------------------------------------------- DOCX


def docx_paragraph(p: etree._Element) -> list[Piece]:
    """``w:t``/``w:delText``/``w:instrText`` and breaks whose nearest paragraph is ``p``."""
    out: list[Piece] = []
    for el in p.iter():
        if el is p or not isinstance(el.tag, str):
            continue
        if el.tag not in W_TEXT and el.tag not in W_BREAK:
            continue
        if nearest(el, W_P) is not p or in_fallback(el, p):
            continue
        if el.tag in W_TEXT:
            out.append(Piece(el, "text", el.text or ""))
        else:
            out.append(Piece(None, None, W_BREAK[el.tag]))
    return out


def docx_cell_paragraphs(tc: etree._Element) -> list[etree._Element]:
    return [p for p in tc.iter(W_P) if nearest(p, W_TXBX) is None and not in_fallback(p, tc)]


def docx_cell(tc: etree._Element) -> list[Piece]:
    out: list[Piece] = []
    for i, p in enumerate(docx_cell_paragraphs(tc)):
        if i:
            out.append(Piece(None, None, "\n"))
        out.extend(docx_paragraph(p))
    return out


# --------------------------------------------------------------------- PPTX / DrawingML


def drawing_paragraph(p: etree._Element) -> list[Piece]:
    """``a:r`` and ``a:fld`` text, ``a:br`` as a line break."""
    out: list[Piece] = []
    for child in p:
        if child.tag in (A_R, A_FLD):
            t = child.find(A_T)
            if t is not None:
                out.append(Piece(t, "text", t.text or ""))
        elif child.tag == A_BR:
            out.append(Piece(None, None, "\n"))
    return out


def drawing_body(body: etree._Element) -> list[Piece]:
    """All ``a:p`` of a text body joined by ``\\n`` (a table cell)."""
    out: list[Piece] = []
    for i, p in enumerate(body.iter(A_P)):
        if i:
            out.append(Piece(None, None, "\n"))
        out.extend(drawing_paragraph(p))
    return out


# --------------------------------------------------------------------- generic parts


def _walk(el: etree._Element, out: list[tuple[etree._Element, Literal["text", "tail"]]]) -> None:
    if isinstance(el.tag, str):
        out.append((el, "text"))
        for child in el:
            _walk(child, out)
            out.append((child, "tail"))


def generic(root: etree._Element) -> list[Piece]:
    """Every non-blank text node, stripped, joined by ``\\n`` (the generic sweep, ADR-26)."""
    slots: list[tuple[etree._Element, Literal["text", "tail"]]] = []
    _walk(root, slots)
    out: list[Piece] = []
    for el, slot in slots:
        raw = (el.text if slot == "text" else el.tail) or ""
        stripped = raw.strip()
        if not stripped:
            continue
        if out:
            out.append(Piece(None, None, "\n"))
        out.append(Piece(el, slot, stripped, lead=len(raw) - len(raw.lstrip())))
    return out


def generic_text(root: etree._Element) -> list[str]:
    return [p.text for p in generic(root) if p.editable]


# --------------------------------------------------------------------- editing


def replace_spans(pieces: list[Piece], spans: list[tuple[int, int, str]]) -> list[bool]:
    """Apply ``(start, end, token)`` spans (segment offsets) to the nodes behind ``pieces``.

    The token goes into the first editable piece the span touches (keeping that run's
    formatting); covered text is removed from the following pieces. Returns one flag per
    span: False if no editable piece intersects it (the redaction cannot be applied).
    """
    bounds = []
    pos = 0
    for p in pieces:
        bounds.append((pos, pos + len(p.text)))
        pos += len(p.text)
    edits: dict[int, list[tuple[int, int, str]]] = {}
    applied: list[bool] = []
    for start, end, token in spans:
        first = True
        touched = False
        for i, (ps, pe) in enumerate(bounds):
            if pe <= start or ps >= end or not pieces[i].editable or pe == ps:
                continue
            local_s, local_e = max(start, ps) - ps, min(end, pe) - ps
            edits.setdefault(i, []).append((local_s, local_e, token if first else ""))
            first = False
            touched = True
        applied.append(touched)
    for i, items in edits.items():
        piece = pieces[i]
        text = piece.text
        for s, e, tok in sorted(items, reverse=True):
            text = text[:s] + tok + text[e:]
        _write(piece, text)
    return applied


def _write(piece: Piece, new_text: str) -> None:
    el = piece.el
    assert el is not None
    assert piece.slot is not None
    raw = (el.text if piece.slot == "text" else el.tail) or ""
    if piece.lead or raw != piece.text:  # generic piece: keep surrounding whitespace
        head = raw[: piece.lead]
        tail = raw[piece.lead + len(piece.text) :]
        new_text = head + new_text + tail
    if piece.slot == "text":
        el.text = new_text
        if el.tag == q(W, "t") and new_text != new_text.strip():
            el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    else:
        el.tail = new_text
