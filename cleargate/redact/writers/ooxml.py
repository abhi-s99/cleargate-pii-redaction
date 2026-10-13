"""Shared OOXML writer machinery for DOCX and PPTX (TR-RD-10, TR-RD-11, TR-SEC-08, ADR-07).

``OoxmlWriter.apply`` copies the package and changes it in place:

1. **segments**: each redacted span is written into the node(s) its offsets map to
   (``extract.textmap``), token in the first run, covered text removed from the rest;
   attributes (alt text, author, relationship targets) and ``docProps`` fields likewise;
2. **media**: images with OCR findings or masked regions are replaced by redacted rasters of
   the same pixel size and format under the same part name (so the ``rId`` is kept);
   identical copies of a redacted image (a logo used twice) get the same bytes;
3. **scrub**: ``dc:creator`` / ``cp:lastModifiedBy`` / ``Manager`` become ``[REDACTED]``;
   every author-like attribute in every XML part (revision and comment authors, initials,
   people ids) becomes ``[REDACTED]``;
4. **value sweep**: any remaining exact occurrence of a redacted value in any paragraph,
   text node or attribute of any part (``mc:Fallback`` copies, chart caches) is replaced by
   its token, so the file and verification V2 agree;
5. **parts**: ``docProps/thumbnail.*`` is removed (its relationship and content-type
   override too); uninspected parts nothing references (``[trash]`` remnants) and printer
   settings are removed and reported as masked; any other uninspected part is left as is,
   which keeps the gate at G3.

Each redacted finding yields a ``RedactionAction``; ``applied=False`` blocks the gate (G4).
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from lxml import etree

from cleargate.core.models import Document, Finding, Locator, RedactionAction, Segment
from cleargate.extract.image import open_image
from cleargate.extract.textmap import (
    A_P,
    W_P,
    Piece,
    docx_paragraph,
    drawing_paragraph,
    generic,
    replace_spans,
    text_of,
)
from cleargate.extract.xml import AUTHOR_ATTRS, NAME_ATTR_ELEMENTS, SAFE, local
from cleargate.redact.text_renderer import Span, apply_spans, is_region, render, span_plan
from cleargate.redact.writers.image import burn, encode, raster_boxes, unapplied_for_missing

REDACTED = "[REDACTED]"
CORE_PERSON = ("creator", "lastModifiedBy")
APP_PERSON = ("Manager",)
SWEEP_ATTRS = frozenset({"descr", "title", "Target", "name"})
MIN_SWEEP_LEN = 4
THUMBNAIL = re.compile(r"^docProps/thumbnail\.\w+$")
PRINTER = re.compile(r"printerSettings\d*\.bin$")
REMOVABLE_CODES = frozenset({"EMBEDDED_OBJECT", "XML_PARSE"})
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


class Package:
    """A zip package held in memory; XML parts parsed lazily and re-serialised on save."""

    def __init__(self, path: Path) -> None:
        with zipfile.ZipFile(path) as zf:
            self.infos = [i for i in zf.infolist() if not i.is_dir()]
            self.data = {i.filename: zf.read(i) for i in self.infos}
        self.trees: dict[str, etree._Element] = {}
        self.removed: set[str] = set()

    def names(self) -> list[str]:
        return [i.filename for i in self.infos if i.filename not in self.removed]

    def is_xml(self, name: str) -> bool:
        return name.endswith((".xml", ".rels", ".vml"))

    def tree(self, name: str) -> etree._Element | None:
        if name not in self.trees:
            data = self.data.get(name)
            if data is None or b"<!DOCTYPE" in data[:4096].upper():
                return None
            try:
                self.trees[name] = etree.fromstring(data, parser=SAFE)
            except etree.XMLSyntaxError:
                return None
        return self.trees[name]

    def remove(self, name: str) -> None:
        self.removed.add(name)
        self.trees.pop(name, None)

    def save(self, out: Path) -> None:
        with zipfile.ZipFile(out, "w") as zf:
            for info in self.infos:
                name = info.filename
                if name in self.removed:
                    continue
                if name in self.trees:
                    data = etree.tostring(
                        self.trees[name], xml_declaration=True, encoding="UTF-8", standalone=True
                    )
                else:
                    data = self.data[name]
                zi = zipfile.ZipInfo(name, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zf.writestr(zi, data)

    def rels_targets(self) -> dict[str, list[tuple[str, etree._Element]]]:
        """Resolved internal relationship target -> [(rels part, Relationship element)]."""
        out: dict[str, list[tuple[str, etree._Element]]] = defaultdict(list)
        for name in self.names():
            if not name.endswith(".rels"):
                continue
            root = self.tree(name)
            if root is None:
                continue
            folder = posixpath.dirname(posixpath.dirname(name))
            for rel in root:
                if rel.get("TargetMode") == "External" or not rel.get("Target"):
                    continue
                target = rel.get("Target", "")
                resolved = (
                    target.lstrip("/")
                    if target.startswith("/")
                    else posixpath.normpath(posixpath.join(folder, target))
                )
                out[resolved].append((name, rel))
        return out


def namespaces(root: etree._Element) -> dict[str, str]:
    ns: dict[str, str] = {}
    for el in root.iter():
        if isinstance(el.tag, str):
            ns.update({k: v for k, v in el.nsmap.items() if k})
    return ns


def find(root: etree._Element, xpath: str) -> etree._Element | None:
    try:
        hits = root.xpath(xpath, namespaces=namespaces(root))
    except etree.XPathError:
        return None
    return (
        hits[0] if isinstance(hits, list) and hits and isinstance(hits[0], etree._Element) else None
    )


def split_attr(xpath: str) -> tuple[str, str] | None:
    if "/@" not in xpath:
        return None
    path, attr = xpath.rsplit("/@", 1)
    return path, attr


def set_attr_spans(el: etree._Element, attr: str, spans: list[Span]) -> bool:
    for name in el.attrib:
        if local(name) == attr:
            value = el.get(name, "")
            stripped = value.strip()
            lead = len(value) - len(value.lstrip())
            el.set(
                name, value[:lead] + apply_spans(stripped, spans) + value[lead + len(stripped) :]
            )
            return True
    return False


def text_pieces(el: etree._Element) -> list[Piece]:
    raw = el.text or ""
    stripped = raw.strip()
    return [Piece(el, "text", stripped, lead=len(raw) - len(raw.lstrip()))] if stripped else []


class OoxmlWriter:
    name = "ooxml-writer"
    version = "0.6.0"

    # -------------------------------------------------------------- format hooks

    def segment_pieces(self, pkg: Package, seg: Segment) -> list[Piece] | None:
        raise NotImplementedError

    def alt_text_element(self, pkg: Package, seg: Segment, path: str) -> etree._Element | None:
        root = pkg.tree(seg.locator.part)
        return find(root, path) if root is not None else None

    # -------------------------------------------------------------- main

    def apply(
        self, src: Path, doc: Document, findings: list[Finding], out_dir: Path, ctx: Any
    ) -> Any:
        from cleargate.pipeline import WriteResult

        pkg = Package(src)
        plan = span_plan(findings)
        segs = {s.segment_id: s for s in doc.segments}
        by_seg: dict[str, list[Finding]] = defaultdict(list)
        for f in findings:
            if f.decision in ("auto_redact", "review") and not is_region(f):
                by_seg[f.segment_id].append(f)
        actions: list[RedactionAction] = []
        for seg_id, spans in plan.items():
            seg = segs.get(seg_id)
            if seg is not None and seg.kind == "ocr_line":
                continue  # text inside an image: burned into the raster by _media
            flags = self._apply_segment(pkg, seg, spans) if seg else [False] * len(spans)
            for (s, e, tok), ok in zip(spans, flags, strict=True):
                ids = [f.finding_id for f in by_seg[seg_id] if s <= f.start and f.end <= e]
                actions.append(
                    RedactionAction(
                        finding_ids=ids,
                        locator=seg.locator if seg else Locator(part="?"),
                        method="token_replace",
                        token=tok,
                        applied=ok,
                        error_code=None if ok else "SPAN_NOT_MAPPED",
                    )
                )
        actions += self._media(pkg, doc, findings, ctx.policy.redaction.pdf_padding_px)
        self._scrub(pkg)
        swept = self._sweep(pkg, findings)
        actions = [self._rescue(a, swept) for a in actions]
        masked = self._parts(pkg, doc)
        out = out_dir / f"redacted{src.suffix.lower()}"
        pkg.save(out)
        actions += unapplied_for_missing(doc, findings, actions)
        sanitized = out_dir / "sanitized.txt"
        sanitized.write_text(render(doc, findings), encoding="utf-8")
        return WriteResult(
            output_path=out, sanitized_path=sanitized, actions=actions, masked_parts=masked
        )

    def _rescue(self, action: RedactionAction, swept: set[str]) -> RedactionAction:
        """A span the structure could not map, removed by the value sweep, is applied."""
        if not action.applied and action.finding_ids and set(action.finding_ids) <= swept:
            return action.model_copy(update={"applied": True, "error_code": None})
        return action

    def _apply_segment(self, pkg: Package, seg: Segment, spans: list[Span]) -> list[bool]:
        loc = seg.locator
        root = pkg.tree(loc.part)
        if root is None:
            return [False] * len(spans)
        xpath = loc.xpath or ""
        attr = split_attr(xpath)
        if seg.kind == "alt_text" and attr:
            el = self.alt_text_element(pkg, seg, attr[0])
            ok = el is not None and set_attr_spans(el, attr[1], spans)
            return [ok] * len(spans)
        if attr:  # author attributes, relationship targets
            el = find(root, attr[0])
            ok = el is not None and set_attr_spans(el, attr[1], spans)
            return [ok] * len(spans)
        if loc.part.startswith("docProps/") and seg.kind == "metadata":
            el = self._prop(root, xpath)
            return replace_spans(text_pieces(el), spans) if el is not None else [False] * len(spans)
        pieces = self.segment_pieces(pkg, seg)
        if pieces is None or text_of(pieces) != seg.text:
            return [False] * len(spans)  # never guess: the map must reproduce the text
        return replace_spans(pieces, spans)

    @staticmethod
    def _prop(root: etree._Element, key: str) -> etree._Element | None:
        if key.startswith("custom:"):
            name = key.split(":", 1)[1]
            for prop in root:
                if prop.get("name") == name:
                    return next((c for c in prop if (c.text or "").strip()), None)
            return None
        want = key.split(":", 1)[-1]
        for el in root:
            if local(el.tag) == want:
                return el
        return None

    # -------------------------------------------------------------- media

    def _media(
        self, pkg: Package, doc: Document, findings: list[Finding], pad: int
    ) -> list[RedactionAction]:
        parts = {s.locator.part for s in doc.segments if s.kind == "ocr_line"}
        parts |= {f.locator.part for f in findings if is_region(f) and f.locator}
        actions: list[RedactionAction] = []
        written: dict[bytes, bytes] = {}
        for part in sorted(parts):
            if part not in pkg.data:
                continue
            boxes, ids = raster_boxes(doc, findings, part)
            if not boxes:
                continue
            original = pkg.data[part]
            ok = False
            try:
                img = open_image(original)
                new = encode(burn(img, boxes, pad), img.format, original)
                if new is not None:
                    pkg.data[part] = new
                    written[original] = new
                    ok = True
            except Exception:  # undecodable or unwritable image: unapplied, gate blocks
                ok = False
            loc = Locator(part=part, image_ref=part)
            for fid in ids:
                actions.append(
                    RedactionAction(
                        finding_ids=[fid],
                        locator=loc,
                        method="pixel_mask",
                        applied=ok,
                        error_code=None if ok else "IMAGE_NOT_WRITABLE",
                    )
                )
        for name in pkg.names():  # identical copies of a redacted image (logo reuse)
            if pkg.data.get(name) in written:
                pkg.data[name] = written[pkg.data[name]]
        return actions

    # -------------------------------------------------------------- scrub and sweep

    def _scrub(self, pkg: Package) -> None:
        for part, keys in (("docProps/core.xml", CORE_PERSON), ("docProps/app.xml", APP_PERSON)):
            root = pkg.tree(part) if part in pkg.data else None
            if root is None:
                continue
            for el in root:
                if local(el.tag) in keys and (el.text or "").strip():
                    el.text = REDACTED
        for name in pkg.names():
            if not name.endswith(".xml"):
                continue
            root = pkg.tree(name)
            if root is None:
                continue
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                for attr in list(el.attrib):
                    lname = local(attr)
                    if (
                        lname in AUTHOR_ATTRS
                        or (lname == "name" and local(el.tag) in NAME_ATTR_ELEMENTS)
                    ) and el.get(attr, "").strip():
                        el.set(attr, REDACTED)

    def _sweep(self, pkg: Package, findings: list[Finding]) -> set[str]:
        """Replace remaining exact occurrences of redacted values; returns finding ids hit."""
        needles: dict[str, tuple[str, list[str]]] = {}
        for f in findings:
            if f.decision in ("auto_redact", "review") and not is_region(f) and f.token:
                v = f.value.strip()
                # Short numbers (card endings, years) would hit unrelated text: never swept.
                if len(v) >= MIN_SWEEP_LEN and not (v.isdigit() and len(v) < 6):
                    _tok, ids = needles.setdefault(v, (f.token, []))
                    ids.append(f.finding_id)
        if not needles:
            return set()
        rx = re.compile(
            r"(?<![A-Za-z0-9])("
            + "|".join(re.escape(v) for v in sorted(needles, key=len, reverse=True))
            + r")(?![A-Za-z0-9])"
        )
        hit: set[str] = set()

        def sweep_pieces(pieces: list[Piece]) -> None:
            text = text_of(pieces)
            spans = [(m.start(), m.end(), needles[m.group(1)][0]) for m in rx.finditer(text)]
            if spans:
                replace_spans(pieces, spans)
                for m in rx.finditer(text):
                    hit.update(needles[m.group(1)][1])

        for name in pkg.names():
            if not pkg.is_xml(name):
                continue
            root = pkg.tree(name)
            if root is None:
                continue
            for p in root.iter(W_P):
                sweep_pieces(docx_paragraph(p))
            for p in root.iter(A_P):
                sweep_pieces(drawing_paragraph(p))
            sweep_pieces(generic(root))
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                for attr in list(el.attrib):
                    if local(attr) in SWEEP_ATTRS:
                        value = el.get(attr, "")
                        new = rx.sub(lambda m: needles[m.group(1)][0], value)
                        if new != value:
                            el.set(attr, new)
                            for m in rx.finditer(value):
                                hit.update(needles[m.group(1)][1])
        return hit

    # -------------------------------------------------------------- parts

    def _parts(self, pkg: Package, doc: Document) -> list[Locator]:
        refs = pkg.rels_targets()
        masked: list[Locator] = []
        # Only parts that are junk by construction: unreadable XML or binary objects that
        # nothing references (``[trash]`` remnants), printer settings, the thumbnail. Package
        # infrastructure is never removed.
        removable = {
            i.locator.part
            for i in doc.coverage.issues
            if i.code in REMOVABLE_CODES
            and i.locator.part in pkg.data
            and i.locator.part != "[Content_Types].xml"
            and not i.locator.part.endswith(".rels")
        }
        for name in list(pkg.names()):
            thumb = bool(THUMBNAIL.match(name))
            if not (thumb or name in removable):
                continue
            referenced = refs.get(name, [])
            if referenced and not (thumb or PRINTER.search(name)):
                continue  # e.g. an embedded OLE object: removing it would break the file
            for _rels_part, rel in referenced:
                rel.getparent().remove(rel)
            self._drop_override(pkg, name)
            pkg.remove(name)
            masked.extend(loc for loc in doc.coverage.uninspected if loc.part == name)
        return masked

    @staticmethod
    def _drop_override(pkg: Package, name: str) -> None:
        root = pkg.tree("[Content_Types].xml")
        if root is None:
            return
        for el in list(root):
            if local(el.tag) == "Override" and el.get("PartName", "").lstrip("/") == name:
                root.remove(el)


def open_bytes(data: bytes) -> Any:
    return open_image(io.BytesIO(data).getvalue())
