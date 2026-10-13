"""Real-sample extraction checks against brief section 1 (counts only, no values)."""

from __future__ import annotations

import secrets
import zipfile
from pathlib import Path

import pdfplumber
import pytest
from cryptography.fernet import Fernet
from docx import Document as DocxDocument
from pptx import Presentation
from pydantic import SecretStr

from cleargate.core.config import Settings, load_policy, load_settings
from cleargate.core.models import Document
from cleargate.ingest.validator import validate
from cleargate.pipeline import JobContext, default_stages

PDF = "Cadence_Group_Risk_Management_Policy__v6.0.pdf"
DOCX = "Cadence_TPRM_Training.docx"
PPTX = "Cadence_Financial_Group_Organizational_Pack.pptx"
pytestmark = pytest.mark.samples


@pytest.fixture(scope="module")
def sample_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    base = load_settings({})
    if not base.tesseract_cmd:
        pytest.skip("Tesseract not installed")
    return Settings(
        data_dir=Path("out") / "test-ocr-cache"
        if Path("out").is_dir()
        else tmp_path_factory.mktemp("d"),
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=base.tesseract_cmd,
    )


def extract(path: Path, settings: Settings, tmp: Path) -> Document:
    policy = load_policy()
    vf = validate(path, policy.limits)
    ctx = JobContext("sample", "none", tmp, policy, "", settings, None)  # type: ignore[arg-type]
    return default_stages().extractor_for(vf.fmt).extract(path, vf.fmt, ctx)


def test_docx_structure_matches_profile(
    samples_dir: Path, sample_settings: Settings, tmp_path: Path
) -> None:
    doc = extract(samples_dir / DOCX, sample_settings, tmp_path)
    assert doc.units["paragraphs"] == 402
    assert doc.units["tables"] == 16
    assert doc.units["inline_images"] == 35
    # differential: python-docx agrees
    d = DocxDocument(str(samples_dir / DOCX))
    assert (len(d.paragraphs), len(d.tables), len(d.inline_shapes)) == (402, 16, 35)
    # 4 txbxContent elements = 2 boxes with Fallback copies -> 2 textbox groups
    with zipfile.ZipFile(samples_dir / DOCX) as zf:
        raw = sum(zf.read(n).count(b"<w:txbxContent") for n in zf.namelist() if n.endswith(".xml"))
    assert raw == 4
    assert len({s.locator.part for s in doc.segments if s.kind == "textbox"}) == 2
    assert sum(1 for s in doc.segments if s.kind == "alt_text") >= 56
    assert any(s.locator.part == "docProps/core.xml" for s in doc.segments)
    assert sum(1 for s in doc.segments if s.method == "ocr") > 0
    codes = {(i.locator.part, i.code) for i in doc.coverage.issues}
    assert codes == {("[trash]/0000.dat", "EMBEDDED_OBJECT")}


def test_pptx_structure_matches_profile(
    samples_dir: Path, sample_settings: Settings, tmp_path: Path
) -> None:
    doc = extract(samples_dir / PPTX, sample_settings, tmp_path)
    assert doc.units["slides"] == 9 == len(Presentation(str(samples_dir / PPTX)).slides)
    assert doc.units["tables"] == 3
    assert doc.coverage.uninspected == []
    assert all(s.method == "native" for s in doc.segments if s.kind != "ocr_line")


@pytest.mark.slow
def test_pdf_is_fully_scanned_and_fig3_is_flagged(
    samples_dir: Path, sample_settings: Settings, tmp_path: Path
) -> None:
    doc = extract(samples_dir / PDF, sample_settings, tmp_path)
    with pdfplumber.open(samples_dir / PDF) as pdf:
        assert len(pdf.pages) == 35
        # No native text anywhere: 33 pages carry a single space character, nothing else.
        assert sum(1 for p in pdf.pages for c in p.chars if c["text"].strip()) == 0
    assert doc.units["pages"] == doc.units["ocr_pages"] == 35
    assert doc.coverage.uninspected == []
    faces = [r for r in doc.regions if r.kind == "face"]
    assert [r.locator.page for r in faces] == [9]
    fig3 = [r for r in doc.regions if r.kind == "unreadable" and r.locator.page == 9]
    assert fig3, "Fig. 3 (p.9) must be an unreadable-region candidate"
    face_box = faces[0].locator.bbox
    assert any(
        r.locator.bbox[0] <= face_box[0]
        and r.locator.bbox[2] >= face_box[2]
        and r.locator.bbox[1] <= face_box[1]
        and r.locator.bbox[3] >= face_box[3]
        for r in fig3
    )
    assert any(r.kind == "unreadable" and r.locator.page == 18 for r in doc.regions)
    assert any(s.locator.part == "pdf:info" and s.locator.xpath == "author" for s in doc.segments)
