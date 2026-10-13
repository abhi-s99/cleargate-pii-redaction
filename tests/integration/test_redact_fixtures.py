"""Redaction end to end on the synthetic fixtures (TR-RD-01..40, TR-SEC-08, FR-08, FR-09).

One batch runs the full pipeline over the five planted fixtures; the tests then read the
outputs back with libraries independent of the writers.
"""

from __future__ import annotations

import io
import re
import secrets
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pdfplumber
import pymupdf
import pytest
from cryptography.fernet import Fernet
from PIL import Image
from pptx import Presentation
from pydantic import SecretStr
from rapidfuzz import fuzz

from cleargate.core.config import Settings, load_policy, load_settings
from cleargate.core.db import MetaStore
from cleargate.core.models import FileFormat
from cleargate.core.states import JobState
from cleargate.pipeline import BatchResult, Pipeline, default_stages
from cleargate.verify import reextract
from tests import filegen
from tests.fixtures.manifest import SYNTHETIC, norm, planted_items

TESS = load_settings({}).tesseract_cmd
pytestmark = pytest.mark.skipif(not TESS, reason="Tesseract not installed")
FILES = ["planted.docx", "planted.pptx", "planted_native.pdf", "planted_scanned.pdf", "planted.png"]
EXPECTED = {
    "planted.docx": JobState.REVIEW_REQUIRED,  # NER-only names and a masked photo
    "planted.pptx": JobState.REVIEW_REQUIRED,
    "planted_native.pdf": JobState.VALIDATED_SAFE,
    "planted_scanned.pdf": JobState.REVIEW_REQUIRED,  # face and illegible region masked
    "planted.png": JobState.VALIDATED_SAFE,
}


def make_settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=TESS,
        ocr_workers=1,
    )


@pytest.fixture(scope="module")
def run(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[Settings, MetaStore, BatchResult]]:
    settings = make_settings(tmp_path_factory.mktemp("redact"))
    store = MetaStore.open(settings.data_dir / "meta.db")
    pipeline = Pipeline(settings, load_policy(), store)
    batch = pipeline.process_batch([SYNTHETIC / f for f in FILES])
    yield settings, store, batch
    pipeline.close()
    store.close()


def out_dir(settings: Settings, batch: BatchResult, name: str) -> Path:
    job = next(j for j in batch.jobs if j.filename == name)
    return settings.data_dir / "jobs" / job.job_id / "out"


def output(settings: Settings, batch: BatchResult, name: str) -> Path:
    return next(out_dir(settings, batch, name).glob("redacted.*"))


def raw_text(path: Path) -> str:
    if path.suffix in (".docx", ".pptx"):
        with zipfile.ZipFile(path) as zf:
            return "\n".join(
                zf.read(n).decode("utf-8", "ignore")
                for n in zf.namelist()
                if n.endswith((".xml", ".rels"))
            )
    if path.suffix == ".pdf":
        with pymupdf.open(path) as pdf:
            text = (
                "\n".join(p.get_text() for p in pdf)
                + str(pdf.metadata)
                + (pdf.get_xml_metadata() or "")
            )
        with pdfplumber.open(path) as plumb:
            return text + "\n".join(p.extract_text() or "" for p in plumb.pages)
    with Image.open(path) as img:
        return str(img.info) + str(dict(img.getexif()))


def test_end_states(run: tuple[Settings, MetaStore, BatchResult]) -> None:
    _, _, batch = run
    assert {j.filename: j.state for j in batch.jobs} == EXPECTED


@pytest.mark.parametrize("name", FILES)
def test_planted_values_absent_from_output_and_sanitized_text(
    run: tuple[Settings, MetaStore, BatchResult], name: str
) -> None:
    settings, _, batch = run
    out = output(settings, batch, name)
    raw = raw_text(out).casefold()
    sanitized = (
        (out_dir(settings, batch, name) / "sanitized.txt").read_text(encoding="utf-8").casefold()
    )
    ctx = SimpleNamespace(settings=settings, policy=load_policy(), job_id=f"t-{name}")
    fmt = {
        "docx": FileFormat.DOCX,
        "pptx": FileFormat.PPTX,
        "pdf": FileFormat.PDF,
        "png": FileFormat.PNG,
    }[out.suffix[1:]]
    ocr_text = norm(" ".join(reextract.haystacks(out, fmt, ctx)[0]))
    for item in (i for i in planted_items() if i.file == name):
        value = item.value.casefold()
        assert value not in raw, item.id
        assert value not in sanitized, item.id
        if item.channel in ("ocr", "image-only"):
            assert fuzz.partial_ratio(norm(item.value), ocr_text) < 90, item.id


def test_outputs_reopen_in_two_parsers_with_unchanged_counts(
    run: tuple[Settings, MetaStore, BatchResult],
) -> None:
    settings, _, batch = run
    for name in FILES:
        src, out = SYNTHETIC / name, output(settings, batch, name)
        fmt = FileFormat(src.suffix[1:]) if src.suffix != ".png" else FileFormat.PNG
        assert reextract.reopen(out, fmt), name
        if fmt is FileFormat.PDF:
            with pymupdf.open(src) as a, pdfplumber.open(out) as b:
                assert a.page_count == len(b.pages)
        if fmt is FileFormat.PPTX:
            assert len(Presentation(str(src)).slides) == len(Presentation(str(out)).slides)


def test_ooxml_parts_rels_and_metadata(run: tuple[Settings, MetaStore, BatchResult]) -> None:
    settings, _, batch = run
    for name in ("planted.docx", "planted.pptx"):
        with (
            zipfile.ZipFile(SYNTHETIC / name) as a,
            zipfile.ZipFile(output(settings, batch, name)) as b,
        ):
            removed = set(a.namelist()) - set(b.namelist())
            assert set(b.namelist()) <= set(a.namelist())
            assert all("thumbnail" in n or "printerSettings" in n for n in removed), removed
            assert not any("thumbnail" in n for n in b.namelist())
            media = [n for n in a.namelist() if "/media/" in n]
            assert media
            assert all(n in b.namelist() for n in media)
            core = b.read("docProps/core.xml").decode()
            assert "<dc:creator>[REDACTED]</dc:creator>" in core
            assert "<cp:lastModifiedBy>[REDACTED]</cp:lastModifiedBy>" in core
            main_rels = (
                "word/_rels/document.xml.rels"
                if name.endswith("docx")
                else "ppt/slides/_rels/slide3.xml.rels"
            )
            ids_a = re.findall(rb'Id="(rId\d+)"', a.read(main_rels))
            assert ids_a == re.findall(rb'Id="(rId\d+)"', b.read(main_rels))
            ct_a = set(re.findall(rb'PartName="([^"]+)"', a.read("[Content_Types].xml")))
            ct_b = set(re.findall(rb'PartName="([^"]+)"', b.read("[Content_Types].xml")))
            assert {p for p in ct_a - ct_b} <= {
                p for p in ct_a if b"thumbnail" in p or b"printerSettings" in p
            }


def test_scanned_output_has_no_original_image_objects(
    run: tuple[Settings, MetaStore, BatchResult],
) -> None:
    settings, _, batch = run

    def images(path: Path) -> set[bytes]:
        with pymupdf.open(path) as pdf:
            return {pdf.extract_image(x[0])["image"] for p in pdf for x in p.get_images()}

    original, redacted = (
        images(SYNTHETIC / "planted_scanned.pdf"),
        images(output(settings, batch, "planted_scanned.pdf")),
    )
    assert original
    assert redacted
    assert not original & redacted  # TR-SEC-08: no original XObject survives
    with pymupdf.open(output(settings, batch, "planted_scanned.pdf")) as pdf:
        assert pdf.metadata.get("producer") == "ClearGate"
        assert not pdf.metadata.get("author")


def test_image_output_has_no_exif(run: tuple[Settings, MetaStore, BatchResult]) -> None:
    settings, _, batch = run
    with Image.open(output(settings, batch, "planted.png")) as img:
        assert not img.getexif()
        assert img.size == Image.open(SYNTHETIC / "planted.png").size


def test_sanitized_text_uses_typed_tokens(run: tuple[Settings, MetaStore, BatchResult]) -> None:
    settings, _, batch = run
    text = (out_dir(settings, batch, "planted.docx") / "sanitized.txt").read_text(encoding="utf-8")
    assert re.search(
        r"analyst \[PERSON_\d+\] \(SSN \[SSN\], passport \[PASSPORT\], PAN \[NATIONAL_ID\]", text
    )
    assert "Escalate to [EMAIL_" in text
    assert "OneTrust and Torii" in text  # business context kept


def test_same_person_gets_the_same_token_across_files(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "data")
    store = MetaStore.open(tmp_path / "meta.db")
    pipeline = Pipeline(settings, load_policy(), store)
    try:
        files = [
            filegen.docx(
                tmp_path / "a.docx",
                text="Escalation contact: Imogen Quarrie, mobile +44 20 7946 0999.",
            ),
            filegen.pptx(tmp_path / "b.pptx", text="Chair: Imogen Quarrie"),
            filegen.pdf(tmp_path / "c.pdf"),
        ]
        batch = pipeline.process_batch(files)
        tokens = []
        for job in batch.jobs[:2]:
            text = (settings.data_dir / "jobs" / job.job_id / "out" / "sanitized.txt").read_text(
                encoding="utf-8"
            )
            tokens.append(re.findall(r"\[PERSON_\d+\]", text))
        assert tokens[0]
        assert tokens[0] == tokens[1]
    finally:
        pipeline.close()
        store.close()


class UnappliedWriter:
    """Wraps the real writer and reports its first action as not applied."""

    name, version = "unapplied-writer", "test"

    def __init__(self) -> None:
        self.inner = default_stages().writer

    def apply(self, *args: Any) -> Any:
        result = self.inner.apply(*args)
        result.actions[0] = result.actions[0].model_copy(
            update={"applied": False, "error_code": "FORCED"}
        )
        return result


def test_unapplied_action_blocks_g4(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "data")
    store = MetaStore.open(tmp_path / "meta.db")
    pipeline = Pipeline(
        settings, load_policy(), store, stages=replace(default_stages(), writer=UnappliedWriter())
    )
    try:
        (job,) = pipeline.process_batch(
            [filegen.docx(tmp_path / "a.docx", text="SSN 900-12-3456")]
        ).jobs
        assert (job.state, job.rule, job.reason) == (JobState.BLOCKED, "G4", "UNAPPLIED_ACTIONS=1")
    finally:
        pipeline.close()
        store.close()


def test_writer_outputs_are_bytes_identical_when_nothing_to_redact(tmp_path: Path) -> None:
    """A clean PNG keeps its pixels (no spurious masks)."""
    settings = make_settings(tmp_path / "data")
    store = MetaStore.open(tmp_path / "meta.db")
    pipeline = Pipeline(settings, load_policy(), store)
    try:
        src = filegen.png(tmp_path / "clean.png", size=(120, 60))
        (job,) = pipeline.process_batch([src]).jobs
        out = settings.data_dir / "jobs" / job.job_id / "out" / "redacted.png"
        a, b = (
            Image.open(src).convert("RGB"),
            Image.open(io.BytesIO(out.read_bytes())).convert("RGB"),
        )
        assert a.tobytes() == b.tobytes()
    finally:
        pipeline.close()
        store.close()
