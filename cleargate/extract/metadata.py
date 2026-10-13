"""Metadata fields from OOXML ``docProps``, PDF Info/XMP and image EXIF (TR-EX-07/11/22/30).

Each function returns ``(key, value)`` pairs with non-empty string values. Keys are
stable identifiers (``dc:creator``, ``Author``, ``exif:Artist``) used as the locator
``xpath`` so writers can clear the same field later.
"""

from __future__ import annotations

import re
import zipfile

from lxml import etree
from PIL import ExifTags, Image

from cleargate.extract.xml import parse_part

CORE_FIELDS = (
    "dc:creator",
    "cp:lastModifiedBy",
    "dc:title",
    "dc:subject",
    "cp:keywords",
    "dc:description",
    "cp:category",
    "cp:contentStatus",
    "dc:identifier",
    "dc:language",
)
APP_FIELDS = ("Company", "Manager", "HyperlinkBase", "Template")
PDF_FIELDS = ("author", "creator", "producer", "title", "subject", "keywords")
EXIF_TEXT_TAGS = (
    "Artist",
    "Copyright",
    "ImageDescription",
    "XPAuthor",
    "XPComment",
    "XPSubject",
    "XPTitle",
    "XPKeywords",
    "UserComment",
    "Make",
    "Model",
    "Software",
    "HostComputer",
    "CameraOwnerName",
    "BodySerialNumber",
)


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def ooxml_core(zf: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    """``(part, key, value)`` from core.xml, app.xml and custom.xml when present."""
    out: list[tuple[str, str, str]] = []
    names = set(zf.namelist())
    if "docProps/core.xml" in names:
        root = parse_part(zf, "docProps/core.xml")
        prefixes = {v: k for k, v in root.nsmap.items() if k}
        for el in root:
            qname = etree.QName(el)
            key = f"{prefixes.get(qname.namespace or '', 'x')}:{qname.localname}"
            if el.text and el.text.strip() and key not in ("dcterms:created", "dcterms:modified"):
                out.append(("docProps/core.xml", key, el.text.strip()))
    if "docProps/app.xml" in names:
        root = parse_part(zf, "docProps/app.xml")
        for el in root:
            if _local(el.tag) in APP_FIELDS and el.text and el.text.strip():
                out.append(("docProps/app.xml", _local(el.tag), el.text.strip()))
    if "docProps/custom.xml" in names:
        root = parse_part(zf, "docProps/custom.xml")
        for prop in root:
            value = "".join(prop.itertext()).strip()
            if value:
                out.append(("docProps/custom.xml", f"custom:{prop.get('name', '?')}", value))
    return out


def pdf_info(metadata: dict[str, str] | None) -> list[tuple[str, str]]:
    meta = metadata or {}
    return [(k, str(meta[k]).strip()) for k in PDF_FIELDS if meta.get(k) and str(meta[k]).strip()]


def xmp_text(xml: str) -> list[str]:
    """Text values inside an XMP packet (no tags)."""
    if not xml.strip():
        return []
    cleaned = re.sub(r"<\?xpacket[^>]*\?>", "", xml)
    try:
        root = etree.fromstring(
            cleaned.encode(), parser=etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        return [cleaned] if cleaned.strip() else []
    return [t.strip() for t in root.itertext() if t.strip()]


def exif_fields(img: Image.Image) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        exif = img.getexif()
    except Exception:  # broken EXIF must not hide the image itself
        return out
    for tag_id, value in exif.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if name not in EXIF_TEXT_TAGS:
            continue
        text = value.decode("utf-16-le", "ignore") if isinstance(value, bytes) else str(value)
        text = text.strip("\x00 ").strip()
        if text:
            out.append((f"exif:{name}", text))
    for key, value in (img.info or {}).items():
        if isinstance(value, str) and value.strip() and str(key).lower() not in ("dpi", "gamma"):
            out.append((f"info:{key}", value.strip()))
    return out
