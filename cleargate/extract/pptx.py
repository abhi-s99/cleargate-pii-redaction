"""PPTX extraction (TR-EX-20..22, D9, ADR-03).

Slides in order; shapes recursively (group shapes) in z-order:

* text frames: one ``shape_text`` segment per paragraph (``paragraph_index``);
* tables: one ``table_cell`` per cell, spanned (merged-away) cells skipped;
* charts: chart title, category and series names;
* pictures: OCR + faces on the image part (``image_ref`` = part name). A picture whose
  bytes appear on at least half of the slides (a logo) is analysed once and reused;
* ``cNvPr/@descr`` and ``@title``: ``alt_text`` segments;
* notes slide text: ``notes`` segments.

Every remaining part (layouts, masters, notes and handout masters, comments, comment
authors, chart XML, docProps) goes through the shared sweep, including person names
held in attributes. ``docProps`` fields become metadata segments (TR-EX-22).
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.shapes.base import BaseShape

from cleargate.core.models import Document, FileFormat, Locator
from cleargate.extract.base import DocBuilder, analyse_raster
from cleargate.extract.docx import analyse_media, sweep_remaining
from cleargate.extract.image import open_image, prepare_for_ocr
from cleargate.extract.metadata import ooxml_core
from cleargate.extract.textmap import drawing_body, drawing_paragraph, text_of
from cleargate.extract.xml import author_attributes, parse_part

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def iter_shapes(shapes: Any) -> Any:
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from iter_shapes(shape.shapes)


def _xpath(shape: BaseShape) -> str:
    el = shape._element
    return str(el.getroottree().getpath(el))


class PptxExtractor:
    name = "pptx-extractor"
    version = "0.3.0"

    def supports(self, fmt: FileFormat) -> bool:
        return fmt is FileFormat.PPTX

    def extract(self, path: Path, fmt: FileFormat, ctx: Any) -> Document:
        b = DocBuilder.for_job(ctx, path, fmt)
        b.doc.extractors[self.name] = self.version
        prs = Presentation(str(path))
        handled: set[str] = {"[Content_Types].xml"}
        slides = list(prs.slides)
        logo_hashes = self._logos(slides)
        analysed: dict[str, str] = {}  # analysis key -> media part analysed
        reused: set[str] = set()  # media parts covered by an earlier identical analysis
        tables = pictures = 0
        for s, slide in enumerate(slides, 1):
            part = str(slide.part.partname).lstrip("/")
            handled.add(part)
            for shape in iter_shapes(slide.shapes):
                base = {
                    "part": part,
                    "slide": s,
                    "shape_id": shape.shape_id,
                    "xpath": _xpath(shape),
                }
                cnv = shape._element.find(".//{*}cNvPr")
                if cnv is not None:
                    for attr in ("descr", "title"):
                        b.add(
                            "alt_text",
                            cnv.get(attr, ""),
                            Locator(**{**base, "xpath": f"{base['xpath']}/@{attr}"}),
                        )
                if shape.has_text_frame:
                    for i, para in enumerate(shape.text_frame.paragraphs):
                        text = text_of(drawing_paragraph(para._p))
                        b.add("shape_text", text, Locator(**base, paragraph_index=i))
                if getattr(shape, "has_table", False) and shape.has_table:
                    tables += 1
                    for r, row in enumerate(shape.table.rows):
                        for c, cell in enumerate(row.cells):
                            if cell.is_spanned:
                                continue
                            b.add(
                                "table_cell",
                                text_of(drawing_body(cell._tc)),
                                Locator(**base, table=tables - 1, row=r, col=c),
                            )
                if getattr(shape, "has_chart", False) and shape.has_chart:
                    self._chart(b, shape, base)
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or hasattr(shape, "image"):
                    try:
                        image = shape.image
                    except (AttributeError, ValueError):
                        continue
                    pictures += 1
                    blip = shape._element.find(".//{*}blip")
                    rid = (
                        blip.get(
                            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
                        )
                        if blip is not None
                        else None
                    )
                    media = (
                        str(slide.part.related_part(rid).partname).lstrip("/")
                        if rid
                        else f"{part}#picture{shape.shape_id}"
                    )
                    handled.add(media)
                    digest = hashlib.sha256(image.blob).hexdigest()
                    key = digest if digest in logo_hashes else media
                    if key in analysed:
                        if analysed[key] != media:
                            reused.add(media)  # identical logo bytes in another part
                        continue  # logo already analysed once (TR-EX-21)
                    analysed[key] = media
                    loc = Locator(part=media, slide=s, shape_id=shape.shape_id, image_ref=media)
                    try:
                        img = open_image(image.blob)
                    except Exception:  # undecodable picture
                        b.register(loc, inspected=False, code="UNSUPPORTED_IMAGE")
                        continue
                    analyse_raster(b, img, loc, dpi_tag="native", prepare=prepare_for_ocr)
            if slide.has_notes_slide:
                notes = slide.notes_slide
                npart = str(notes.part.partname).lstrip("/")
                handled.add(npart)
                for shape in iter_shapes(notes.shapes):
                    if shape.has_text_frame:
                        for i, para in enumerate(shape.text_frame.paragraphs):
                            b.add(
                                "notes",
                                text_of(drawing_paragraph(para._p)),
                                Locator(
                                    part=npart, slide=s, shape_id=shape.shape_id, paragraph_index=i
                                ),
                            )
                b.register(Locator(part=npart, slide=s), inspected=True)
            b.register(Locator(part=part, slide=s), inspected=True)
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            for part in sorted(handled & set(names)):
                if part.endswith(".xml"):
                    for xpath, value in author_attributes(parse_part(zf, part)):
                        b.add("metadata", value, Locator(part=part, xpath=xpath))
            for part, key, value in ooxml_core(zf):
                b.add("metadata", value, Locator(part=part, xpath=key))
            for part in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
                if part in names:
                    handled.add(part)
                    b.register(Locator(part=part), inspected=True)
            # Identical logo copies in other parts: covered by the one analysis above.
            for part in sorted(reused - set(analysed.values())):
                b.register(Locator(part=part, image_ref=part), inspected=True)
            for part in sorted(n for n in names if n.startswith("ppt/media/") and n not in handled):
                handled.add(part)
                analyse_media(b, zf, part, None)
            sweep_remaining(b, zf, names, handled)
        b.doc.units = {"slides": len(slides), "tables": tables, "pictures": pictures}
        return b.build()

    @staticmethod
    def _logos(slides: list[Any]) -> set[str]:
        if len(slides) < 2:
            return set()
        per_slide: dict[str, set[int]] = {}
        for s, slide in enumerate(slides):
            for shape in iter_shapes(slide.shapes):
                try:
                    blob = shape.image.blob
                except (AttributeError, ValueError):
                    continue
                per_slide.setdefault(hashlib.sha256(blob).hexdigest(), set()).add(s)
        return {h for h, used in per_slide.items() if len(used) >= len(slides) / 2}

    @staticmethod
    def _chart(b: DocBuilder, shape: Any, base: dict[str, Any]) -> None:
        chart = shape.chart
        if chart.has_title and chart.chart_title.has_text_frame:
            b.add("shape_text", chart.chart_title.text_frame.text, Locator(**base))
        for plot in chart.plots:
            for cat in plot.categories:
                b.add("shape_text", str(cat), Locator(**base))
            for series in plot.series:
                b.add("shape_text", str(series.name), Locator(**base))
