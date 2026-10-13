"""Helpers for detection unit tests: build segments and documents from invented text."""

from __future__ import annotations

from cleargate.core.models import Document, FileFormat, Locator, Segment, SegmentKind
from cleargate.detect.base import Candidate, DocContext


def seg(
    text: str,
    *,
    kind: SegmentKind = "paragraph",
    method: str = "native",
    idx: int = 0,
    doc_id: str = "d",
    **loc: object,
) -> Segment:
    return Segment(
        segment_id=f"{doc_id}:{idx}",
        kind=kind,
        text=text,
        order_index=idx,
        locator=Locator(part=str(loc.pop("part", "word/document.xml")), **loc),  # type: ignore[arg-type]
        method=method,  # type: ignore[arg-type]
    )


def doc_of(*segments: Segment, doc_id: str = "d") -> Document:
    d = Document(doc_id=doc_id, filename="t.docx", sha256="", fmt=FileFormat.DOCX, size_bytes=0)
    d.segments.extend(segments)
    return d


def table(rows: list[list[str]], *, table_no: int = 0, doc_id: str = "d") -> list[Segment]:
    out = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            out.append(
                seg(
                    text,
                    kind="table_cell",
                    idx=len(out),
                    doc_id=doc_id,
                    table=table_no,
                    row=r,
                    col=c,
                )
            )
    return out


def run(recognizer: object, text: str, **kw: object) -> list[Candidate]:
    s = seg(text, **kw)  # type: ignore[arg-type]
    return recognizer.analyze(s, DocContext.build(doc_of(s)))  # type: ignore[attr-defined]


def values(cands: list[Candidate]) -> list[str]:
    return [c.value for c in cands if not c.discard_reason]
