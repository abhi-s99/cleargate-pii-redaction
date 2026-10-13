"""Tiny builders for valid and deliberately broken input files (invented content only)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pymupdf
from docx import Document as DocxDocument
from PIL import Image
from pptx import Presentation

CT_PATH = "[Content_Types].xml"


def docx(path: Path, text: str = "Quarterly vendor review.") -> Path:
    d = DocxDocument()
    d.add_paragraph(text)
    d.save(str(path))
    return path


def pptx(path: Path, text: str = "Org overview") -> Path:
    p = Presentation()
    slide = p.slides.add_slide(p.slide_layouts[1])
    slide.shapes.title.text = text
    p.save(str(path))
    return path


def pdf(path: Path, pages: int = 1, **save_kwargs: object) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Policy page {i + 1}")
    doc.save(str(path), **save_kwargs)
    doc.close()
    return path


def png(path: Path, size: tuple[int, int] = (64, 32)) -> Path:
    Image.new("RGB", size, "white").save(path, format="PNG")
    return path


def jpeg(path: Path) -> Path:
    Image.new("RGB", (32, 32), "white").save(path, format="JPEG")
    return path


def rewrite_zip(
    src: Path,
    dest: Path,
    *,
    replace: dict[str, bytes] | None = None,
    add: dict[str, bytes] | None = None,
) -> Path:
    """Copy an OOXML package, replacing or adding parts."""
    replace, add = replace or {}, add or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item.filename, replace.get(item.filename, zin.read(item.filename)))
        for name, data in add.items():
            zout.writestr(name, data)
    dest.write_bytes(buf.getvalue())
    return dest


def content_types(path: Path) -> bytes:
    with zipfile.ZipFile(path) as zf:
        return zf.read(CT_PATH)


def set_zip_encrypted_flag(path: Path) -> Path:
    """Mark every central-directory entry as encrypted (general purpose bit 0)."""
    data = bytearray(path.read_bytes())
    pos = data.find(b"PK\x01\x02")
    while pos != -1:
        data[pos + 8] |= 0x01
        pos = data.find(b"PK\x01\x02", pos + 4)
    path.write_bytes(bytes(data))
    return path


def ole_file(path: Path, *, encrypted: bool) -> Path:
    """A minimal OLE compound-file look-alike: magic + optional EncryptedPackage name."""
    body = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
    if encrypted:
        body += "EncryptedPackage".encode("utf-16-le")
    path.write_bytes(body + b"\x00" * 512)
    return path


def xlsx(path: Path) -> Path:
    ct = (
        b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
        b'package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="'
        b'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(CT_PATH, ct)
        zf.writestr("xl/workbook.xml", b"<workbook/>")
    return path
