"""Unit tests for OCR parsing, regions, faces, XML helpers and the OCR cache."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from lxml import etree
from PIL import Image, ImageDraw

from cleargate.core.config import load_settings
from cleargate.extract.docx import paragraph_text
from cleargate.extract.image import (
    detect_faces,
    ink_ratio,
    merge_boxes,
    nontext_regions,
    prepare_for_ocr,
)
from cleargate.extract.ocr import OcrEngine, parse_data, raster_key, unreadable_blocks
from cleargate.extract.xml import author_attributes
from tests.fixtures.make_fixtures import face, text_image

TESS = load_settings({}).tesseract_cmd
needs_tesseract = pytest.mark.skipif(not TESS, reason="Tesseract not installed")


def data(words: list[tuple[str, float, int, int, int, int, int]]) -> dict[str, list[object]]:
    keys = ("text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num")
    out: dict[str, list[object]] = {k: [] for k in keys}
    for text, conf, left, top, w, h, block in words:
        for k, v in zip(keys, (text, conf, left, top, w, h, block, 1, 1), strict=True):
            out[k].append(v)
    return out


def test_parse_data_groups_lines_and_drops_empty_or_negative() -> None:
    d = data(
        [
            ("Ada", 95, 10, 10, 40, 20, 1),
            ("", -1, 0, 0, 0, 0, 1),
            ("Quill", 90, 60, 10, 50, 20, 1),
            ("x", -1, 0, 0, 1, 1, 2),
        ]
    )
    r = parse_data(d, 200, 100, "t", 0.1)
    assert [ln.text for ln in r.lines] == ["Ada Quill"]
    assert r.lines[0].confs == [95.0, 90.0]
    assert r.lines[0].box == (10, 10, 110, 30)
    assert r.word_count == 2


def test_unreadable_block_rules() -> None:
    low = [(f"w{i}", 40.0, 0, 0, 100, 100, 1) for i in range(5)]  # big, low confidence
    ok = [(f"v{i}", 95.0, 0, 200, 10, 10, 2) for i in range(5)]  # tiny, high confidence
    r = parse_data(data(low + ok), 1000, 1000, "t", 0.1)
    bad = unreadable_blocks(r, min_area_ratio=0.005, max_mean_conf=70)
    assert [b.block for b in bad] == [1]


def test_single_character_words_do_not_make_a_clean_table_unreadable() -> None:
    raci = [
        ("R", 20.0, 0, 0, 300, 300, 1),
        ("A", 25.0, 300, 0, 300, 300, 1),
        ("Approve", 93.0, 0, 300, 300, 300, 1),
        ("vendor", 92.0, 300, 300, 300, 300, 1),
    ]
    r = parse_data(data(raci), 1000, 1000, "t", 0.1)
    assert unreadable_blocks(r, min_area_ratio=0.02, max_mean_conf=70) == []


def test_raster_key_depends_on_pixels_dpi_and_engine() -> None:
    a = Image.new("RGB", (10, 10), "white")
    b = a.copy()
    b.putpixel((0, 0), (0, 0, 0))
    assert raster_key(a, "300dpi", "t5") == raster_key(a.copy(), "300dpi", "t5")
    assert (
        len(
            {
                raster_key(a, "300dpi", "t5"),
                raster_key(b, "300dpi", "t5"),
                raster_key(a, "200dpi", "t5"),
                raster_key(a, "300dpi", "t6"),
            }
        )
        == 4
    )


def test_faces_found_on_public_domain_photo_not_on_text() -> None:
    assert len(detect_faces(face(256))) >= 1
    assert detect_faces(text_image(["Approver: Invented Person", "Status: approved"])) == []


def test_merge_boxes() -> None:
    assert merge_boxes([(0, 0, 10, 10), (2, 2, 12, 12), (50, 50, 60, 60)]) == [
        (0, 0, 12, 12),
        (50, 50, 60, 60),
    ]


def test_nontext_region_found_when_no_words_inside() -> None:
    img = Image.new("RGB", (1000, 1000), "white")
    ImageDraw.Draw(img).rectangle((100, 100, 500, 400), fill=(90, 90, 90))
    regions = nontext_regions(img, [], min_area_ratio=0.02)
    assert len(regions) == 1
    (x0, y0, x1, y1), confs = regions[0]
    assert x0 <= 110
    assert y0 <= 110
    assert x1 >= 490
    assert y1 >= 390
    assert confs == []


def test_word_boxes_are_not_non_text_regions() -> None:
    img = Image.new("RGB", (1000, 1000), "white")
    ImageDraw.Draw(img).rectangle((100, 100, 500, 400), fill=(0, 0, 0))
    assert nontext_regions(img, [((95, 95, 505, 405), "word", 90.0)], min_area_ratio=0.02) == []


def test_ink_ratio_and_prepare() -> None:
    blank = Image.new("RGB", (400, 400), "white")
    assert ink_ratio(blank) == 0.0
    assert ink_ratio(text_image(["Some text here"])) > 0.0
    small = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    out = prepare_for_ocr(small)
    assert (out.mode, out.size) == ("RGB", (600, 400))


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def test_paragraph_text_includes_deleted_text_and_field_codes_but_not_fallback() -> None:
    p = etree.fromstring(
        f'<w:p xmlns:w="{W}" xmlns:mc="{MC}"><w:r><w:t>Kept</w:t><w:tab/></w:r>'
        '<w:del w:author="x"><w:r><w:delText>gone</w:delText></w:r></w:del>'
        '<w:r><w:instrText> HYPERLINK "mailto:a@b.example" </w:instrText></w:r>'
        "<w:r><mc:AlternateContent><mc:Choice><w:t>choice</w:t></mc:Choice>"
        "<mc:Fallback><w:t>fallback</w:t></mc:Fallback></mc:AlternateContent></w:r></w:p>"
    )
    text = paragraph_text(p)
    assert "Kept\t" in text
    assert "gone" in text
    assert "mailto:a@b.example" in text
    assert "choice" in text
    assert "fallback" not in text


def test_author_attributes_are_collected_once() -> None:
    root = etree.fromstring(
        f'<w:document xmlns:w="{W}"><w:ins w:author="Invented Author"/>'
        '<w:del w:author="Invented Author"/><w:comment w:initials="IA"/></w:document>'
    )
    values = [v for _, v in author_attributes(root)]
    assert values == ["Invented Author", "IA"]


@needs_tesseract
def test_ocr_cache_is_encrypted_and_reused(tmp_path: Path) -> None:
    key = Fernet.generate_key().decode()
    engine = OcrEngine(TESS, cache_dir=tmp_path, cache_key=key)
    img = text_image(["Invented Zorvath Pemberly"])
    first = engine.ocr(img, "native")
    assert not first.cached
    blobs = list(tmp_path.glob("*.ocr"))
    assert len(blobs) == 1
    assert b"Zorvath" not in blobs[0].read_bytes()  # ciphertext at rest (ADR-26)
    again = OcrEngine(TESS, cache_dir=tmp_path, cache_key=key).ocr(img, "native")
    assert again.cached
    assert [ln.text for ln in again.lines] == [ln.text for ln in first.lines]
    wrong = OcrEngine(TESS, cache_dir=tmp_path, cache_key=Fernet.generate_key().decode())
    assert not wrong.ocr(img, "native").cached  # undecryptable cache is ignored


def test_missing_tesseract_is_unavailable() -> None:
    from cleargate.core.errors import ErrorCode, OcrError

    engine = OcrEngine(None)
    assert not engine.available()
    with pytest.raises(OcrError) as exc_info:
        engine.ocr(Image.new("RGB", (10, 10)), "native")
    assert exc_info.value.code is ErrorCode.OCR_UNAVAILABLE


def test_cache_key_includes_parser_version(monkeypatch: pytest.MonkeyPatch) -> None:
    import cleargate.extract.ocr as ocr

    img = Image.new("RGB", (10, 10), "white")
    before = raster_key(img, "300dpi", "t5")
    monkeypatch.setattr(ocr, "PARSER_VERSION", "999")
    assert raster_key(img, "300dpi", "t5") != before
