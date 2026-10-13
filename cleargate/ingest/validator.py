"""File validation (TR-IN-01..06, TR-SEC-07, FR-01).

``validate(path, limits, display_name)`` returns a ``ValidatedFile`` or raises
``IngestError`` with a specific code. The type is detected from content, never from
the extension alone, and the extension must agree with it:

* ``%PDF-`` header, opened with PyMuPDF: encrypted -> ``ENCRYPTED``, page limit.
* ZIP: zip-bomb limits (total size, ratio, entry count), encrypted entries, then
  ``[Content_Types].xml`` (parsed with DTDs and entities disabled) decides DOCX, PPTX,
  macro-enabled (``MACRO_ENABLED``) or unsupported (XLSX, templates).
* OLE compound file: encrypted OOXML (``EncryptedPackage`` stream) -> ``ENCRYPTED``,
  otherwise legacy ``.doc``/``.ppt`` -> ``UNSUPPORTED_FORMAT``.
* PNG/JPEG/TIFF magic bytes, Pillow verify, megapixel limit.

Messages carry codes and numbers only (``core.errors``).
"""

from __future__ import annotations

import hashlib
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from lxml import etree
from PIL import Image

from cleargate.core.config import LimitsPolicy
from cleargate.core.errors import ErrorCode, IngestError
from cleargate.core.models import FileFormat

EXT_FORMATS: dict[str, FileFormat] = {
    ".pdf": FileFormat.PDF,
    ".docx": FileFormat.DOCX,
    ".pptx": FileFormat.PPTX,
    ".png": FileFormat.PNG,
    ".jpg": FileFormat.JPEG,
    ".jpeg": FileFormat.JPEG,
    ".tif": FileFormat.TIFF,
    ".tiff": FileFormat.TIFF,
}
MACRO_EXTS = frozenset({".docm", ".dotm", ".pptm", ".potm", ".ppsm", ".xlsm", ".xltm"})
LEGACY_EXTS = frozenset({".doc", ".dot", ".ppt", ".pot", ".pps", ".xls", ".rtf"})

_CT = "application/vnd.openxmlformats-officedocument."
MAIN_CONTENT_TYPES: dict[str, FileFormat | ErrorCode] = {
    _CT + "wordprocessingml.document.main+xml": FileFormat.DOCX,
    _CT + "presentationml.presentation.main+xml": FileFormat.PPTX,
    "application/vnd.ms-word.document.macroEnabled.main+xml": ErrorCode.MACRO_ENABLED,
    "application/vnd.ms-word.template.macroEnabledTemplate.main+xml": ErrorCode.MACRO_ENABLED,
    "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml": ErrorCode.MACRO_ENABLED,
    "application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml": ErrorCode.MACRO_ENABLED,
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml": ErrorCode.MACRO_ENABLED,
    _CT + "spreadsheetml.sheet.main+xml": ErrorCode.UNSUPPORTED_FORMAT,  # TR-IN-05 (MAY)
    _CT + "wordprocessingml.template.main+xml": ErrorCode.UNSUPPORTED_FORMAT,
    _CT + "presentationml.template.main+xml": ErrorCode.UNSUPPORTED_FORMAT,
    _CT + "presentationml.slideshow.main+xml": ErrorCode.UNSUPPORTED_FORMAT,
}
VBA_CONTENT_TYPE = "application/vnd.ms-office.vbaProject"

CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")
MAX_ZIP_ENTRIES = 10_000
MAX_CONTENT_TYPES_BYTES = 1 << 20

SAFE_XML = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False
)

pymupdf.TOOLS.mupdf_display_errors(False)


@dataclass(frozen=True)
class ValidatedFile:
    path: Path
    fmt: FileFormat
    ext: str
    size_bytes: int
    sha256: str
    pages: int | None = None


def file_ext(name: str) -> str:
    return Path(name.replace("\\", "/")).suffix.lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def parse_safe_xml(data: bytes, stage: str) -> etree._Element:
    """Parse untrusted XML: any DTD (and so any entity, incl. XXE) is rejected."""
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        raise IngestError(ErrorCode.MALFORMED, stage=f"{stage}_dtd")
    try:
        return etree.fromstring(data, parser=SAFE_XML)
    except etree.XMLSyntaxError:
        raise IngestError(ErrorCode.MALFORMED, stage=stage) from None


def _sniff(head: bytes) -> str:
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(CFB_MAGIC):
        return "cfb"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileFormat.PNG.value
    if head.startswith(b"\xff\xd8\xff"):
        return FileFormat.JPEG.value
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return FileFormat.TIFF.value
    return "unknown"


def _check_zip(path: Path, limits: LimitsPolicy) -> FileFormat:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise IngestError(ErrorCode.MALFORMED, stage="zip") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise IngestError(ErrorCode.ZIP_BOMB)
        total = sum(i.file_size for i in infos)
        packed = sum(i.compress_size for i in infos)
        if total > limits.max_uncompressed_bytes:
            raise IngestError(ErrorCode.ZIP_BOMB)
        if packed and total / packed > limits.max_compression_ratio:
            raise IngestError(ErrorCode.ZIP_BOMB)
        if any(i.flag_bits & 0x1 for i in infos):
            raise IngestError(ErrorCode.ENCRYPTED)
        names = {i.filename for i in infos}
        if "[Content_Types].xml" not in names:
            raise IngestError(ErrorCode.UNSUPPORTED_FORMAT, ext="zip")
        info = zf.getinfo("[Content_Types].xml")
        if info.file_size > MAX_CONTENT_TYPES_BYTES:
            raise IngestError(ErrorCode.ZIP_BOMB)
        root = parse_safe_xml(zf.read(info), "content_types")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise IngestError(ErrorCode.MACRO_ENABLED)
    types = {el.get("ContentType", "") for el in root}
    if VBA_CONTENT_TYPE in types:
        raise IngestError(ErrorCode.MACRO_ENABLED)
    found = [MAIN_CONTENT_TYPES[t] for t in types if t in MAIN_CONTENT_TYPES]
    if not found:
        raise IngestError(ErrorCode.UNSUPPORTED_FORMAT, ext="zip")
    for item in found:
        if isinstance(item, ErrorCode):
            raise IngestError(item, ext="ooxml")
    return next(f for f in found if isinstance(f, FileFormat))


def _check_cfb(path: Path) -> None:
    with path.open("rb") as fh:
        data = fh.read(4 << 20)
    if ENCRYPTED_PACKAGE in data:
        raise IngestError(ErrorCode.ENCRYPTED)
    raise IngestError(ErrorCode.UNSUPPORTED_FORMAT, ext="legacy_office")


def _check_pdf(path: Path, limits: LimitsPolicy) -> int:
    try:
        doc = pymupdf.open(path)
    except Exception:  # PyMuPDF raises several unrelated types on corrupt input
        raise IngestError(ErrorCode.MALFORMED, stage="pdf_open") from None
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise IngestError(ErrorCode.ENCRYPTED)
        pages = doc.page_count
    if pages == 0:
        raise IngestError(ErrorCode.MALFORMED, stage="pdf_no_pages")
    if pages > limits.max_pdf_pages:
        raise IngestError(ErrorCode.TOO_MANY_PAGES, pages=pages, limit=limits.max_pdf_pages)
    return pages


def _check_image(path: Path, fmt: FileFormat, limits: LimitsPolicy) -> None:
    pil_names = {FileFormat.PNG: "PNG", FileFormat.JPEG: "JPEG", FileFormat.TIFF: "TIFF"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path) as img:
                megapixels = img.width * img.height / 1e6
                if megapixels > limits.max_image_megapixels:
                    raise IngestError(
                        ErrorCode.IMAGE_TOO_LARGE,
                        megapixels=round(megapixels, 1),
                        limit=limits.max_image_megapixels,
                    )
                if img.format != pil_names[fmt]:
                    raise IngestError(ErrorCode.MALFORMED, stage="image_format")
                img.verify()
    except Image.DecompressionBombError:
        raise IngestError(ErrorCode.IMAGE_TOO_LARGE) from None
    except IngestError:
        raise
    except Exception:  # Pillow raises many types for corrupt images
        raise IngestError(ErrorCode.MALFORMED, stage="image_verify") from None


def validate(path: Path, limits: LimitsPolicy, display_name: str | None = None) -> ValidatedFile:
    ext = file_ext(display_name or path.name)
    if ext in MACRO_EXTS:
        raise IngestError(ErrorCode.MACRO_ENABLED)
    if ext in LEGACY_EXTS or ext not in EXT_FORMATS:
        raise IngestError(ErrorCode.UNSUPPORTED_FORMAT, ext=ext.lstrip(".") or "none")
    size = path.stat().st_size
    if size > limits.max_file_bytes:
        raise IngestError(
            ErrorCode.FILE_TOO_LARGE, size_bytes=size, limit_bytes=limits.max_file_bytes
        )
    if size == 0:
        raise IngestError(ErrorCode.MALFORMED, stage="empty")
    with path.open("rb") as fh:
        head = fh.read(1024)
    kind = _sniff(head)
    pages: int | None = None
    if kind == "zip":
        fmt = _check_zip(path, limits)
    elif kind == "cfb":
        _check_cfb(path)
        raise AssertionError("unreachable")  # pragma: no cover
    elif kind == "pdf":
        fmt = FileFormat.PDF
    elif kind in {f.value for f in (FileFormat.PNG, FileFormat.JPEG, FileFormat.TIFF)}:
        fmt = FileFormat(kind)
    else:
        raise IngestError(ErrorCode.UNSUPPORTED_FORMAT, ext=ext.lstrip("."))
    if EXT_FORMATS[ext] is not fmt:
        raise IngestError(ErrorCode.EXTENSION_MISMATCH, ext=ext.lstrip("."), detected=fmt.value)
    if fmt is FileFormat.PDF:
        pages = _check_pdf(path, limits)
    elif fmt in (FileFormat.PNG, FileFormat.JPEG, FileFormat.TIFF):
        _check_image(path, fmt, limits)
    return ValidatedFile(
        path=path, fmt=fmt, ext=ext, size_bytes=size, sha256=sha256_file(path), pages=pages
    )
