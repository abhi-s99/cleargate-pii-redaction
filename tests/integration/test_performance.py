"""Performance targets that a test can hold (TR-PF-01, TR-PF-04). Invented content only.

TR-PF-01: a DOCX or PPTX without images, end to end (validate .. gate), within 15 s once
the worker is warm (TR-PF-05: the spaCy model loads once per process; the first document
pays for it, which the warm-up absorbs). TR-PF-04: OCR progress is reported per page, so
the UI's poll sees a change at least every page; the measured gap must stay under 5 s.
TR-PF-02/03 depend on the real files and are measured by ``make smoke`` (Phase 11 report).
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from pptx import Presentation
from pptx.util import Inches

from cleargate.core.config import Settings, load_policy, load_settings
from cleargate.core.db import MetaStore
from cleargate.pipeline import Pipeline
from tests import filegen
from tests.fixtures.manifest import SYNTHETIC
from tests.integration.test_redact_fixtures import make_settings

TESS = load_settings({}).tesseract_cmd
pytestmark = pytest.mark.skipif(not TESS, reason="Tesseract not installed")
NAMES = ["Hedda Lindqvist", "Tomasz Wrobel", "Ines Carvalho", "Kofi Mensah", "Aiko Tanabe"]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Settings, Pipeline, Path]]:
    tmp = tmp_path_factory.mktemp("perf")
    settings = make_settings(tmp)
    store = MetaStore.open(settings.data_dir / "meta.db")
    pipeline = Pipeline(settings, load_policy(), store)
    pipeline.process_batch([filegen.docx(tmp / "warm.docx", "Warm-up by Hedda Lindqvist.")])
    yield settings, pipeline, tmp
    pipeline.close()
    store.close()


def big_docx(path: Path) -> Path:
    d = DocxDocument()
    d.add_heading("Vendor review", level=1)
    for i in range(60):
        name = NAMES[i % len(NAMES)]
        d.add_paragraph(
            f"Item {i}: owner {name}, contact {name.split()[0].lower()}@example.test, "
            f"phone +1 (555) 01{i % 100:02d}, status open. Renewal tracked in OneTrust."
        )
    t = d.add_table(rows=6, cols=3)
    for r in range(6):
        for c, text in enumerate([NAMES[r % 5], f"EMP-{10000 + r}", "Reviewer"]):
            t.cell(r, c).text = text
    d.save(str(path))
    return path


def big_pptx(path: Path) -> Path:
    prs = Presentation()
    for i in range(12):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = f"Workstream {i}"
        box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3))
        name = NAMES[i % len(NAMES)]
        box.text_frame.text = f"Lead {name}, {name.split()[0].lower()}@example.test"
    prs.save(str(path))
    return path


@pytest.mark.parametrize("maker", [big_docx, big_pptx], ids=["docx", "pptx"])
def test_office_file_without_images_within_15_s(
    env: tuple[Settings, Pipeline, Path], maker: object
) -> None:
    _, pipeline, tmp = env
    path = maker(tmp / ("big.docx" if maker is big_docx else "big.pptx"))  # type: ignore[operator]
    start = time.perf_counter()
    batch = pipeline.process_batch([path])
    elapsed = time.perf_counter() - start
    assert batch.jobs[0].state.value in ("VALIDATED_SAFE", "REVIEW_REQUIRED")
    assert elapsed <= 15.0, f"{elapsed:.1f} s"


def test_ocr_progress_is_reported_per_page_within_5_s(
    env: tuple[Settings, Pipeline, Path],
) -> None:
    _, pipeline, _ = env
    events: list[tuple[float, str, int, int]] = []

    def record(job_id: str, stage: str, done: int, total: int) -> None:
        del job_id
        events.append((time.perf_counter(), stage, done, total))

    pipeline.progress = record
    try:
        start = time.perf_counter()
        pipeline.process_batch([SYNTHETIC / "planted_scanned.pdf"])
    finally:
        pipeline.progress = None
    ocr = [e for e in events if e[1] == "ocr"]
    assert [e[2] for e in ocr] == list(range(1, ocr[0][3] + 1))
    stamps = [start] + [e[0] for e in ocr]
    gaps = [b - a for a, b in itertools.pairwise(stamps)]
    assert max(gaps) < 5.0, [round(g, 2) for g in gaps]
