"""Ingest validation (TR-IN-01..06, TR-SEC-07, FR-01)."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from cleargate.core.config import LimitsPolicy
from cleargate.core.errors import ErrorCode, IngestError
from cleargate.core.models import FileFormat
from cleargate.ingest.validator import validate
from tests import filegen

LIMITS = LimitsPolicy()


def code_of(path: Path, limits: LimitsPolicy = LIMITS, name: str | None = None) -> ErrorCode:
    with pytest.raises(IngestError) as exc_info:
        validate(path, limits, display_name=name)
    assert str(path) not in str(exc_info.value)  # messages never quote paths or content
    return exc_info.value.code


@pytest.mark.parametrize(
    ("builder", "name", "fmt"),
    [
        (filegen.docx, "a.docx", FileFormat.DOCX),
        (filegen.pptx, "a.pptx", FileFormat.PPTX),
        (filegen.pdf, "a.pdf", FileFormat.PDF),
        (filegen.png, "a.png", FileFormat.PNG),
        (filegen.jpeg, "a.jpg", FileFormat.JPEG),
        (filegen.jpeg, "a.JPEG", FileFormat.JPEG),
    ],
)
def test_valid_files_are_accepted(
    tmp_path: Path, builder: object, name: str, fmt: FileFormat
) -> None:
    path = builder(tmp_path / name)  # type: ignore[operator]
    vf = validate(path, LIMITS)
    assert vf.fmt is fmt
    assert len(vf.sha256) == 64
    assert vf.size_bytes == path.stat().st_size


def test_pdf_page_count_is_recorded(tmp_path: Path) -> None:
    assert validate(filegen.pdf(tmp_path / "p.pdf", pages=3), LIMITS).pages == 3


# --- TR-IN-06 and extension agreement ---------------------------------------------


@pytest.mark.parametrize(
    ("builder", "name", "detected"),
    [
        (filegen.docx, "report.pdf", None),
        (filegen.pdf, "report.docx", None),
        (filegen.pptx, "deck.docx", None),
        (filegen.jpeg, "photo.png", None),
    ],
)
def test_extension_must_match_content(
    tmp_path: Path, builder: object, name: str, detected: None
) -> None:
    path = builder(tmp_path / name)  # type: ignore[operator]
    assert code_of(path) is ErrorCode.EXTENSION_MISMATCH


@pytest.mark.parametrize("name", ["notes.txt", "legacy.doc", "legacy.ppt", "sheet.xls", "noext"])
def test_unsupported_extensions(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"hello")
    assert code_of(path) is ErrorCode.UNSUPPORTED_FORMAT


def test_legacy_ole_file_disguised_as_docx(tmp_path: Path) -> None:
    assert (
        code_of(filegen.ole_file(tmp_path / "x.docx", encrypted=False))
        is ErrorCode.UNSUPPORTED_FORMAT
    )


def test_xlsx_is_not_supported_yet(tmp_path: Path) -> None:
    path = filegen.xlsx(tmp_path / "book.xlsx")
    assert code_of(path) is ErrorCode.UNSUPPORTED_FORMAT
    renamed = path.rename(tmp_path / "book.docx")
    assert code_of(renamed) is ErrorCode.UNSUPPORTED_FORMAT


def test_unknown_content(tmp_path: Path) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"GIF89a not a pdf")
    assert code_of(path) is ErrorCode.UNSUPPORTED_FORMAT


# --- encryption ---------------------------------------------------------------------


def test_encrypted_pdf(tmp_path: Path) -> None:
    path = filegen.pdf(
        tmp_path / "enc.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o"
    )
    assert code_of(path) is ErrorCode.ENCRYPTED


def test_encrypted_ooxml_package(tmp_path: Path) -> None:
    assert code_of(filegen.ole_file(tmp_path / "enc.docx", encrypted=True)) is ErrorCode.ENCRYPTED


def test_zip_with_encrypted_entries(tmp_path: Path) -> None:
    path = filegen.set_zip_encrypted_flag(filegen.docx(tmp_path / "z.docx"))
    assert code_of(path) is ErrorCode.ENCRYPTED


# --- macros -------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["m.docm", "m.pptm", "m.xlsm", "m.dotm"])
def test_macro_extensions(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"PK\x03\x04")
    assert code_of(path) is ErrorCode.MACRO_ENABLED


def test_macro_content_type_behind_docx_extension(tmp_path: Path) -> None:
    src = filegen.docx(tmp_path / "src.docx")
    ct = filegen.content_types(src).replace(
        b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        b"application/vnd.ms-word.document.macroEnabled.main+xml",
    )
    path = filegen.rewrite_zip(src, tmp_path / "disguised.docx", replace={filegen.CT_PATH: ct})
    assert code_of(path) is ErrorCode.MACRO_ENABLED


def test_macro_content_type_behind_pptx_extension(tmp_path: Path) -> None:
    src = filegen.pptx(tmp_path / "src.pptx")
    ct = filegen.content_types(src).replace(
        b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        b"application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml",
    )
    path = filegen.rewrite_zip(src, tmp_path / "disguised.pptx", replace={filegen.CT_PATH: ct})
    assert code_of(path) is ErrorCode.MACRO_ENABLED


def test_vba_project_part(tmp_path: Path) -> None:
    src = filegen.docx(tmp_path / "src.docx")
    path = filegen.rewrite_zip(src, tmp_path / "vba.docx", add={"word/vbaProject.bin": b"x"})
    assert code_of(path) is ErrorCode.MACRO_ENABLED


# --- size, zip bomb, pages, images ----------------------------------------------------


def test_oversize_file(tmp_path: Path) -> None:
    path = filegen.docx(tmp_path / "big.docx")
    assert code_of(path, LimitsPolicy(max_file_bytes=100)) is ErrorCode.FILE_TOO_LARGE


def test_zip_bomb_by_ratio(tmp_path: Path) -> None:
    src = filegen.docx(tmp_path / "src.docx")
    path = filegen.rewrite_zip(
        src, tmp_path / "bomb.docx", add={"word/media/pad.bin": b"\0" * (20 << 20)}
    )
    assert code_of(path) is ErrorCode.ZIP_BOMB


def test_zip_bomb_by_total_size(tmp_path: Path) -> None:
    path = filegen.docx(tmp_path / "d.docx")
    assert code_of(path, LimitsPolicy(max_uncompressed_bytes=1000)) is ErrorCode.ZIP_BOMB


def test_too_many_pages(tmp_path: Path) -> None:
    path = filegen.pdf(tmp_path / "p.pdf", pages=3)
    assert code_of(path, LimitsPolicy(max_pdf_pages=2)) is ErrorCode.TOO_MANY_PAGES


def test_image_too_large(tmp_path: Path) -> None:
    path = filegen.png(tmp_path / "i.png", size=(2000, 1000))
    assert code_of(path, LimitsPolicy(max_image_megapixels=1)) is ErrorCode.IMAGE_TOO_LARGE


# --- malformed and hostile structure (TR-SEC-07) ------------------------------------


def test_xxe_in_content_types_is_rejected(tmp_path: Path) -> None:
    src = filegen.docx(tmp_path / "src.docx")
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE t [<!ENTITY x SYSTEM "file:///c:/windows/win.ini">]>'
        b"<Types>&x;</Types>"
    )
    path = filegen.rewrite_zip(src, tmp_path / "xxe.docx", replace={filegen.CT_PATH: evil})
    assert code_of(path) is ErrorCode.MALFORMED


def test_billion_laughs_is_rejected(tmp_path: Path) -> None:
    src = filegen.docx(tmp_path / "src.docx")
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa">'
        b'<!ENTITY b "&a;&a;&a;">]><Types>&b;</Types>'
    )
    path = filegen.rewrite_zip(src, tmp_path / "lol.docx", replace={filegen.CT_PATH: evil})
    assert code_of(path) is ErrorCode.MALFORMED


def test_broken_zip(tmp_path: Path) -> None:
    path = tmp_path / "broken.docx"
    path.write_bytes(b"PK\x03\x04" + b"garbage" * 50)
    assert code_of(path) is ErrorCode.MALFORMED


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    assert code_of(path) is ErrorCode.MALFORMED


def test_truncated_png(tmp_path: Path) -> None:
    good = filegen.png(tmp_path / "g.png", size=(200, 200)).read_bytes()
    path = tmp_path / "t.png"
    path.write_bytes(good[: len(good) // 2])
    assert code_of(path) is ErrorCode.MALFORMED


def test_corrupt_pdf(tmp_path: Path) -> None:
    path = tmp_path / "c.pdf"
    path.write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 20)
    assert code_of(path) is ErrorCode.MALFORMED


def test_display_name_extension_is_used(tmp_path: Path) -> None:
    path = filegen.docx(tmp_path / "original.bin")
    assert validate(path, LIMITS, display_name="Quarterly.docx").fmt is FileFormat.DOCX


# --- real samples ------------------------------------------------------------------------


@pytest.mark.samples
@pytest.mark.parametrize(
    ("name", "fmt"),
    [
        ("Cadence_Group_Risk_Management_Policy__v6.0.pdf", FileFormat.PDF),
        ("Cadence_TPRM_Training.docx", FileFormat.DOCX),
        ("Cadence_Financial_Group_Organizational_Pack.pptx", FileFormat.PPTX),
    ],
)
def test_samples_are_accepted(samples_dir: Path, name: str, fmt: FileFormat) -> None:
    vf = validate(samples_dir / name, LIMITS)
    assert vf.fmt is fmt
    if fmt is FileFormat.PDF:
        assert vf.pages == 35
