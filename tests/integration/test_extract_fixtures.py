"""Phase 3 extraction against the planted-PII manifest (TR-EX-01..40, FR-03, FR-04).

Every planted item must be extracted at its expected locator; merged cells and the
Choice/Fallback text box exactly once; faces and the illegible region found;
coverage complete; unit counts agree with an independent library (differential).
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pdfplumber
import pymupdf
import pytest
from cryptography.fernet import Fernet
from docx import Document as DocxDocument
from PIL import Image
from pptx import Presentation
from pydantic import SecretStr
from rapidfuzz import fuzz

from cleargate.core.config import Settings, load_policy
from cleargate.core.models import Document
from cleargate.ingest.validator import validate
from cleargate.pipeline import JobContext, default_stages
from tests.fixtures.manifest import SYNTHETIC, load_manifest, matches, norm, planted_items

ITEMS = [i for i in planted_items() if i.type != "UNREADABLE_IMAGE_REGION"]
FILES = sorted({i.file for i in planted_items()})


def extract_file(path: Path, settings: Settings, job_dir: Path) -> Document:
    policy = load_policy()
    vf = validate(path, policy.limits)
    ctx = JobContext("fixture", "none", job_dir, policy, "", settings, None)  # type: ignore[arg-type]
    return default_stages().extractor_for(vf.fmt).extract(path, vf.fmt, ctx)


@pytest.fixture(scope="session")
def ocr_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    from cleargate.core.config import load_settings

    base = load_settings({})
    return Settings(
        data_dir=tmp_path_factory.mktemp("data"),
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=base.tesseract_cmd,
        ocr_workers=1,
    )


@pytest.fixture(scope="session")
def docs(ocr_settings: Settings, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Document]:
    if not ocr_settings.tesseract_cmd:
        pytest.skip("Tesseract not installed")
    return {
        f: extract_file(SYNTHETIC / f, ocr_settings, tmp_path_factory.mktemp("job")) for f in FILES
    }


@pytest.mark.parametrize("item", ITEMS, ids=[i.id for i in ITEMS])
def test_planted_item_extracted_at_expected_locator(
    docs: dict[str, Document], item: object
) -> None:
    found = matches(docs[item.file], item)  # type: ignore[attr-defined]
    assert found, f"{item.id} ({item.type}, {item.channel}) not found at {item.expect}"  # type: ignore[attr-defined]


@pytest.mark.parametrize("item", [i for i in ITEMS if i.expect.get("once")], ids=lambda i: i.id)
def test_merged_cells_and_textbox_extracted_once(docs: dict[str, Document], item: object) -> None:
    hits = [s for s in docs[item.file].segments if norm(item.value) in norm(s.text)]  # type: ignore[attr-defined]
    assert len(hits) == 1, [s.locator.model_dump(exclude_none=True) for s in hits]


def test_vmerge_continuation_cell_is_not_a_segment(docs: dict[str, Document]) -> None:
    cells = {
        (s.locator.table, s.locator.row, s.locator.col)
        for s in docs["planted.docx"].segments
        if s.kind == "table_cell"
    }
    assert (1, 1, 2) in cells
    assert (1, 2, 2) not in cells  # continuation of the vertical merge
    assert (1, 1, 1) not in cells  # covered by the gridSpan of (1, 1, 0)


@pytest.mark.parametrize(
    "region", load_manifest()["regions"], ids=lambda r: f"{r['file']}-{r['kind']}"
)
def test_expected_regions_are_found(docs: dict[str, Document], region: dict[str, object]) -> None:
    found = [
        r
        for r in docs[str(region["file"])].regions
        if r.kind == region["kind"]
        and ("page" not in region or r.locator.page == region["page"])
        and ("slide" not in region or r.locator.slide == region["slide"])
        and r.locator.part.startswith(str(region.get("part_prefix", "")))
    ]
    assert found, region


def test_illegible_region_is_not_read_as_text(docs: dict[str, Document]) -> None:
    # The fixture is only meaningful if OCR really cannot read the planted value there.
    item = next(i for i in planted_items() if i.type == "UNREADABLE_IMAGE_REGION")
    doc = docs[item.file]
    best = max(
        (fuzz.partial_ratio(norm(item.value), norm(s.text)) for s in doc.segments), default=0
    )
    assert best < 90
    assert any(r.kind == "unreadable" and r.locator.page == 1 for r in doc.regions)


@pytest.mark.parametrize(
    "name", ["planted.docx", "planted_native.pdf", "planted_scanned.pdf", "planted.png"]
)
def test_coverage_is_complete(docs: dict[str, Document], name: str) -> None:
    cov = docs[name].coverage
    assert cov.uninspected == [], [(i.locator.part, i.code) for i in cov.issues]
    assert cov.parts_inspected == cov.parts_total > 0


def test_pptx_printer_settings_binary_is_uninspected(docs: dict[str, Document]) -> None:
    issues = [(i.locator.part, i.code) for i in docs["planted.pptx"].coverage.issues]
    assert issues == [("ppt/printerSettings/printerSettings1.bin", "EMBEDDED_OBJECT")]


def test_segments_are_in_reading_order(docs: dict[str, Document]) -> None:
    for doc in docs.values():
        idx = [s.order_index for s in doc.segments]
        assert idx == list(range(len(idx)))
        assert all(s.segment_id == f"{doc.doc_id}:{s.order_index}" for s in doc.segments)
    texts = [s.text for s in docs["planted.docx"].segments if s.locator.part == "word/document.xml"]
    order = [
        next(i for i, t in enumerate(texts) if key in t)
        for key in ("Vendor Onboarding Review", "On 3 March", "Led by", "Contract review")
    ]
    assert order == sorted(order)


def test_heading_level_and_list_membership(docs: dict[str, Document]) -> None:
    segs = docs["planted.docx"].segments
    heading = next(s for s in segs if s.text == "Vendor Onboarding Review")
    assert (heading.kind, heading.heading_level) == ("heading", 1)
    assert any(s.kind == "list_item" and "Escalate to" in s.text for s in segs)


def test_ocr_segments_carry_word_confidences(docs: dict[str, Document]) -> None:
    for seg in docs["planted_scanned.pdf"].segments:
        if seg.method == "ocr":
            assert seg.ocr_word_conf is not None
            assert len(seg.ocr_word_conf) == len(seg.text.split())
            assert seg.locator.bbox is not None
            assert seg.locator.image_ref == "page-raster"


# --- differential checks: a second, independent library must agree -----------------


@pytest.mark.parametrize("name", ["planted_native.pdf", "planted_scanned.pdf"])
def test_pdf_page_count_pymupdf_vs_pdfplumber(docs: dict[str, Document], name: str) -> None:
    with pdfplumber.open(SYNTHETIC / name) as pdf, pymupdf.open(SYNTHETIC / name) as mu:
        assert docs[name].units["pages"] == len(pdf.pages) == mu.page_count


def test_docx_units_vs_python_docx(docs: dict[str, Document]) -> None:
    d = DocxDocument(str(SYNTHETIC / "planted.docx"))
    units = docs["planted.docx"].units
    assert units["paragraphs"] == len(d.paragraphs)
    assert units["tables"] == len(d.tables)
    assert units["inline_images"] == len(d.inline_shapes)


def test_pptx_units_vs_python_pptx(docs: dict[str, Document]) -> None:
    prs = Presentation(str(SYNTHETIC / "planted.pptx"))
    assert docs["planted.pptx"].units["slides"] == len(prs.slides)


def test_scanned_pdf_has_no_native_text_and_all_pages_ocr(docs: dict[str, Document]) -> None:
    doc = docs["planted_scanned.pdf"]
    assert doc.units["ocr_pages"] == doc.units["pages"] == 2
    assert all(s.method == "ocr" for s in doc.segments if s.locator.part == "page")


def test_mixed_page_routes_to_ocr_and_drops_duplicate_ocr_lines(
    ocr_settings: Settings, tmp_path: Path
) -> None:
    """TR-EX-02: image coverage > 60 % routes to OCR; native text is kept and OCR lines
    overlapping it are dropped, so the same words are not extracted twice."""
    from PIL import ImageDraw

    from tests.fixtures.make_fixtures import font, png_bytes

    raster = Image.new("RGB", (2550, 3300), "white")
    d = ImageDraw.Draw(raster)
    d.text((300, 300), "Scanned header Ilvana Brecht", fill="black", font=font(48))
    d.text((300, 2890), "Native footer Corwen Ashby", fill="black", font=font(48))
    pdf = pymupdf.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_image(page.rect, stream=png_bytes(raster))
    page.insert_text((72, 706), "Native footer Corwen Ashby", fontsize=11)  # native copy
    path = tmp_path / "mixed.pdf"
    pdf.save(str(path))
    doc = extract_file(path, ocr_settings, tmp_path)
    assert doc.units["ocr_pages"] == 1
    footer = [s for s in doc.segments if "Corwen" in s.text]
    assert [s.method for s in footer] == ["native"]
    assert any(s.method == "ocr" and "Ilvana" in s.text for s in doc.segments)


def test_repeated_logo_is_analysed_once(docs: dict[str, Document]) -> None:
    """TR-EX-21: the logo appears on all 3 slides; one coverage entry per media part."""
    parts = [loc.part for loc in [*docs["planted.pptx"].coverage.uninspected]]
    assert parts == ["ppt/printerSettings/printerSettings1.bin"]
    media = [s.locator.part for s in docs["planted.pptx"].segments if s.kind == "ocr_line"]
    northwind = [s for s in docs["planted.pptx"].segments if "NORTHWIND" in s.text.upper()]
    assert len(northwind) == 1, [s.locator.model_dump(exclude_none=True) for s in northwind]
    assert media


def test_wordless_picture_with_content_becomes_a_whole_image_region(
    ocr_settings: Settings, tmp_path: Path
) -> None:
    """A picture with ink but no recognised words is not 'PII-free': mask it whole."""
    from PIL import ImageDraw

    from tests import filegen

    img = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(img).ellipse((50, 50, 350, 250), fill=(30, 90, 160))
    path = tmp_path / "shape.png"
    img.save(path)
    doc = extract_file(path, ocr_settings, tmp_path)
    regions = [r for r in doc.regions if r.kind == "unreadable"]
    assert len(regions) == 1
    assert regions[0].area_ratio == 1.0
    blank = extract_file(
        filegen.png(tmp_path / "blank.png", size=(400, 300)), ocr_settings, tmp_path
    )
    assert blank.regions == []
