"""DOCX extraction by an ordered lxml walk over every package part (TR-EX-10..13, D7).

Body (and every header, footer, footnote, endnote and comment part) is walked in
document order:

* ``w:p``: one segment; text is every ``w:t``, ``w:delText`` (tracked deletions are
  still in the file), ``w:instrText`` (field codes, e.g. ``mailto:`` links), tabs and
  breaks whose nearest paragraph is this one and that are not inside ``mc:Fallback``.
  Heading level from the paragraph style or outline level; list membership from
  ``w:numPr`` (TR-EX-13).
* ``w:tbl``: one segment per grid cell; ``gridSpan`` advances the column, ``vMerge``
  continuation cells are skipped, so a merged cell is extracted once.
* ``w:sdt`` / ``w:customXml``: their content is walked in place.
* text boxes (``w:txbxContent``) are walked as ``textbox`` segments after their host
  paragraph; the ``mc:Fallback`` copy of the same box is ignored.
* ``wp:docPr/@descr`` and ``@title``: ``alt_text`` segments.

Every ``word/media`` part is OCR'd with face detection; SVG text is read natively;
EMF/WMF that Pillow cannot rasterise are uninspected (``UNSUPPORTED_IMAGE``). Person
names in attributes (``w:author`` on revisions and comments, ``w15:person``) become
metadata segments. ``docProps`` fields become metadata segments (TR-EX-11). Every other
XML part goes through a generic text sweep; binary parts that are neither media nor
fonts are uninspected (``EMBEDDED_OBJECT``).
"""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from cleargate.core.errors import ExtractionError
from cleargate.core.models import Document, FileFormat, Locator, SegmentKind
from cleargate.extract.base import DocBuilder, analyse_raster
from cleargate.extract.image import open_image, prepare_for_ocr
from cleargate.extract.metadata import ooxml_core
from cleargate.extract.xml import author_attributes, generic_text, parse_part

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
V = "urn:schemas-microsoft-com:vml"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


W_P, W_T, W_TBL, W_TR, W_TC = q(W, "p"), q(W, "t"), q(W, "tbl"), q(W, "tr"), q(W, "tc")
W_TXBX, MC_FALLBACK = q(W, "txbxContent"), q(MC, "Fallback")
TEXT_TAGS = {q(W, "t"), q(W, "delText"), q(W, "instrText")}
BREAK_TAGS = {
    q(W, "br"): "\n",
    q(W, "cr"): "\n",
    q(W, "tab"): "\t",
    q(W, "noBreakHyphen"): "-",
    q(W, "softHyphen"): "",
}
STORY_PARTS = {"header": "header", "footer": "footer"}
STRUCTURED_PREFIXES = ("word/header", "word/footer")
STRUCTURED_PARTS = {
    "word/document.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
    "word/comments.xml",
}
RASTER_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf"}
FONT_EXT = {".odttf", ".ttf", ".otf", ".fntdata"}
IGNORE_PARTS = {"[Content_Types].xml"}


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


def paragraph_text(p: etree._Element) -> str:
    parts: list[str] = []
    for el in p.iter():
        if el is p or not isinstance(el.tag, str):
            continue
        if el.tag in TEXT_TAGS or el.tag in BREAK_TAGS:
            if nearest(el, W_P) is not p or in_fallback(el, p):
                continue
            parts.append(el.text or "" if el.tag in TEXT_TAGS else BREAK_TAGS[el.tag])
    return "".join(parts)


def rels(zf: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, name = posixpath.split(part)
    rel_path = posixpath.join(folder, "_rels", name + ".rels")
    if rel_path not in zf.namelist():
        return {}
    out = {}
    for rel in parse_part(zf, rel_path):
        if rel.get("TargetMode") == "External":
            continue
        out[rel.get("Id", "")] = posixpath.normpath(posixpath.join(folder, rel.get("Target", "")))
    return out


class _Walker:
    def __init__(
        self,
        b: DocBuilder,
        part: str,
        root: etree._Element,
        styles: dict[str, str],
        part_rels: dict[str, str],
        media_owner: dict[str, str | None],
        list_styles: set[str],
    ) -> None:
        self.b, self.part, self.tree = b, part, root.getroottree()
        self.styles, self.rels, self.media_owner = styles, part_rels, media_owner
        self.list_styles = list_styles
        self.p_index = 0
        self.t_index = 0
        base = posixpath.basename(part)
        self.default_kind: SegmentKind = "paragraph"
        for prefix, kind in STORY_PARTS.items():
            if base.startswith(prefix):
                self.default_kind = kind  # type: ignore[assignment]

    def loc(self, el: etree._Element, **extra: Any) -> Locator:
        return Locator(part=self.part, xpath=self.tree.getpath(el), **extra)

    def walk(self, container: etree._Element, kind: SegmentKind | None = None) -> None:
        for child in container:
            tag = child.tag
            if tag == W_P:
                self.paragraph(child, kind)
            elif tag == W_TBL:
                self.table(child, kind)
            elif tag in (q(W, "sdt"),):
                content = child.find(q(W, "sdtContent"))
                if content is not None:
                    self.walk(content, kind)
            elif tag in (
                q(W, "customXml"),
                q(W, "sdtContent"),
                q(W, "ins"),
                q(W, "del"),
                q(W, "footnote"),
                q(W, "endnote"),
                q(W, "comment"),
            ):
                self.walk(child, kind)

    def heading(self, p: etree._Element) -> int | None:
        ppr = p.find(q(W, "pPr"))
        if ppr is None:
            return None
        style = ppr.find(q(W, "pStyle"))
        name = self.styles.get(style.get(q(W, "val"), ""), "") if style is not None else ""
        if name.lower().startswith("heading "):
            level = name.split()[-1]
            if level.isdigit():
                return int(level)
        if name.lower() == "title":
            return 1
        outline = ppr.find(q(W, "outlineLvl"))
        if outline is not None and outline.get(q(W, "val"), "").isdigit():
            return int(outline.get(q(W, "val"))) + 1
        return None

    def paragraph(
        self, p: etree._Element, kind: SegmentKind | None, table: tuple[int, int, int] | None = None
    ) -> str | None:
        level = self.heading(p)
        ppr = p.find(q(W, "pPr"))
        style = ppr.find(q(W, "pStyle")) if ppr is not None else None
        is_list = (ppr is not None and ppr.find(q(W, "numPr")) is not None) or (
            style is not None and style.get(q(W, "val"), "") in self.list_styles
        )
        seg_kind: SegmentKind = kind or (
            "heading" if level else "list_item" if is_list else self.default_kind
        )
        extra: dict[str, Any] = {"paragraph_index": self.p_index}
        if table:
            extra.update(table=table[0], row=table[1], col=table[2])
        self.p_index += 1
        seg_id = None
        if table is None:
            seg_id = self.b.add(
                seg_kind, paragraph_text(p), self.loc(p, **extra), heading_level=level
            )
        self.inline_objects(p, seg_id)
        return seg_id

    def inline_objects(self, host: etree._Element, parent_id: str | None) -> None:
        """Text boxes, alt text and image references inside ``host``, Fallback ignored."""
        for box in host.iter(W_TXBX):
            if in_fallback(box, host) or nearest(box, W_TXBX) is not None:
                continue
            if nearest(box, W_P) is not host and host.tag == W_P:
                continue
            self.walk(box, "textbox")
        # Alt text lives twice per picture: wp:docPr and pic:cNvPr (both are in the file).
        for pr in host.iter(q(WP, "docPr"), "{*}cNvPr"):
            if in_fallback(pr, host):
                continue
            for attr in ("descr", "title"):
                self.b.add(
                    "alt_text",
                    pr.get(attr, ""),
                    Locator(part=self.part, xpath=f"{self.tree.getpath(pr)}/@{attr}"),
                    parent_id=parent_id,
                )
        for blip in host.iter(q(A, "blip")):
            if in_fallback(blip, host):
                continue
            target = self.rels.get(blip.get(q(R, "embed"), ""))
            if target and self.media_owner.get(target) is None:
                self.media_owner[target] = parent_id
        for imagedata in host.iter(q(V, "imagedata")):
            target = self.rels.get(imagedata.get(q(R, "id"), ""))
            if target and self.media_owner.get(target) is None:
                self.media_owner[target] = parent_id

    def table(self, tbl: etree._Element, kind: SegmentKind | None) -> None:
        t = self.t_index
        self.t_index += 1
        for r, tr in enumerate(tbl.findall(W_TR)):
            col = 0
            cells = [c for c in tr if c.tag == W_TC] + [
                c for sdt in tr.findall(q(W, "sdt")) for c in sdt.iter(W_TC)
            ]
            for tc in cells:
                tcpr = tc.find(q(W, "tcPr"))
                span = 1
                continuation = False
                if tcpr is not None:
                    gs = tcpr.find(q(W, "gridSpan"))
                    if gs is not None and gs.get(q(W, "val"), "1").isdigit():
                        span = int(gs.get(q(W, "val")))
                    vm = tcpr.find(q(W, "vMerge"))
                    continuation = vm is not None and vm.get(q(W, "val"), "continue") != "restart"
                if not continuation:
                    paras = [
                        p
                        for p in tc.iter(W_P)
                        if nearest(p, W_TXBX) is None and not in_fallback(p, tc)
                    ]
                    text = "\n".join(paragraph_text(p) for p in paras)
                    seg_id = self.b.add(
                        kind or "table_cell", text, self.loc(tc, table=t, row=r, col=col)
                    )
                    self.inline_objects(tc, seg_id)
                col += span


class DocxExtractor:
    name = "docx-extractor"
    version = "0.3.0"

    def supports(self, fmt: FileFormat) -> bool:
        return fmt is FileFormat.DOCX

    def extract(self, path: Path, fmt: FileFormat, ctx: Any) -> Document:
        b = DocBuilder.for_job(ctx, path, fmt)
        b.doc.extractors[self.name] = self.version
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            styles, list_styles = self._styles(zf, names)
            media_owner: dict[str, str | None] = {}
            handled: set[str] = set(IGNORE_PARTS)
            body_units = {"paragraphs": 0, "tables": 0, "images": 0}
            order = (
                ["word/document.xml"]
                + sorted(
                    n for n in names if n.startswith(STRUCTURED_PREFIXES) and n.endswith(".xml")
                )
                + [
                    n
                    for n in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")
                    if n in names
                ]
            )
            for part in order:
                handled.add(part)
                try:
                    root = parse_part(zf, part)
                except ExtractionError:
                    b.register(Locator(part=part), inspected=False, code="XML_PARSE")
                    continue
                walker = _Walker(b, part, root, styles, rels(zf, part), media_owner, list_styles)
                container = root.find(q(W, "body")) if part == "word/document.xml" else root
                walker.walk(container if container is not None else root)
                if part == "word/document.xml" and container is not None:
                    body_units = {
                        "paragraphs": len(container.findall(W_P)),
                        "tables": len(container.findall(W_TBL)),
                        "images": sum(
                            1 for blip in root.iter(q(A, "blip")) if not in_fallback(blip)
                        ),
                        "inline_images": sum(1 for _ in root.iter(q(WP, "inline"))),
                        "textboxes": sum(1 for box in root.iter(W_TXBX) if not in_fallback(box)),
                    }
                for xpath, value in author_attributes(root):
                    b.add("metadata", value, Locator(part=part, xpath=xpath))
                b.register(Locator(part=part), inspected=True)
            for part, key, value in ooxml_core(zf):
                b.add("metadata", value, Locator(part=part, xpath=key))
            for part in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
                if part in names:
                    handled.add(part)
                    b.register(Locator(part=part), inspected=True)
            self._media(b, zf, names, media_owner, handled)
            sweep_remaining(b, zf, names, handled)
        b.doc.units = {
            **body_units,
            "media": sum(
                1 for n in names if posixpath.splitext(n)[1].lower() in RASTER_EXT | {".svg"}
            ),
        }
        return b.build()

    def _styles(self, zf: zipfile.ZipFile, names: list[str]) -> tuple[dict[str, str], set[str]]:
        """styleId -> name, and the ids of styles that carry list numbering."""
        if "word/styles.xml" not in names:
            return {}, set()
        try:
            root = parse_part(zf, "word/styles.xml")
        except ExtractionError:
            return {}, set()
        out: dict[str, str] = {}
        lists: set[str] = set()
        for st in root.iter(q(W, "style")):
            name = st.find(q(W, "name"))
            sid = st.get(q(W, "styleId"), "")
            out[sid] = name.get(q(W, "val"), "") if name is not None else ""
            # Styles such as "List Bullet" carry the numbering themselves (TR-EX-13).
            if st.find(f"{q(W, 'pPr')}/{q(W, 'numPr')}") is not None:
                lists.add(sid)
        return out, lists

    def _media(
        self,
        b: DocBuilder,
        zf: zipfile.ZipFile,
        names: list[str],
        owner: dict[str, str | None],
        handled: set[str],
    ) -> None:
        media = sorted(
            n
            for n in names
            if posixpath.splitext(n)[1].lower() in RASTER_EXT | {".svg"}
            and (n.startswith("word/media/") or n.startswith("docProps/") or n in owner)
        )
        for part in media:
            handled.add(part)
            analyse_media(b, zf, part, owner.get(part))


def analyse_media(b: DocBuilder, zf: zipfile.ZipFile, part: str, parent_id: str | None) -> None:
    loc = Locator(part=part, image_ref=part)
    ext = posixpath.splitext(part)[1].lower()
    data = zf.read(part)
    if ext == ".svg":
        try:
            root = etree.fromstring(
                data, parser=etree.XMLParser(resolve_entities=False, no_network=True)
            )
        except etree.XMLSyntaxError:
            b.register(loc, inspected=False, code="SVG_PARSE")
            return
        for text in generic_text(root):
            b.add("ocr_line", text, loc, parent_id=parent_id)
        b.register(loc, inspected=True)
        return
    try:
        img = open_image(data)
    except Exception:  # Pillow cannot rasterise every EMF/WMF or damaged image
        b.register(loc, inspected=False, code="UNSUPPORTED_IMAGE")
        return
    analyse_raster(b, img, loc, dpi_tag="native", prepare=prepare_for_ocr, parent_id=parent_id)


def sweep_remaining(
    b: DocBuilder, zf: zipfile.ZipFile, names: list[str], handled: set[str]
) -> None:
    """Generic sweep so no part of the package goes unaccounted for (ADR-26)."""
    for part in names:
        if part in handled:
            continue
        if part.endswith(".rels"):
            # Internal targets are part names; external ones can be mailto: or URLs.
            try:
                root = parse_part(zf, part)
            except ExtractionError:
                b.register(Locator(part=part), inspected=False, code="XML_PARSE")
                continue
            for rel in root:
                if rel.get("TargetMode") == "External" and rel.get("Target"):
                    b.add(
                        "metadata",
                        rel.get("Target", ""),
                        Locator(part=part, xpath=f"{root.getroottree().getpath(rel)}/@Target"),
                    )
            b.register(Locator(part=part), inspected=True)
            continue
        ext = posixpath.splitext(part)[1].lower()
        loc = Locator(part=part)
        if ext in (".xml", ".vml"):
            try:
                root = parse_part(zf, part)
            except ExtractionError:
                b.register(loc, inspected=False, code="XML_PARSE")
                continue
            texts = generic_text(root)
            if texts:
                kind: SegmentKind = "metadata" if "customXml" in part else "paragraph"
                b.add(kind, "\n".join(texts), loc)
            for xpath, value in author_attributes(root):
                b.add("metadata", value, Locator(part=part, xpath=xpath))
            b.register(loc, inspected=True)
        elif ext in RASTER_EXT or ext == ".svg":
            analyse_media(b, zf, part, None)
        elif ext in FONT_EXT:
            b.register(loc, inspected=True)  # glyph data, no document text
        else:
            b.register(loc, inspected=False, code="EMBEDDED_OBJECT")
