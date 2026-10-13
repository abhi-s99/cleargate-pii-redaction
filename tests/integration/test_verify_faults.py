"""Independent verification fault injection (TRD 8.1, TRD 14, Architecture 6, FR-10).

Each test wraps the real writer with a fault and checks that verification, reading the
output file back on its own path, ends the job in the state TRD 8.2 prescribes.
"""

from __future__ import annotations

import json
import secrets
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from cryptography.fernet import Fernet
from PIL import Image
from pydantic import SecretStr

from cleargate.core.config import Settings, load_policy, load_settings
from cleargate.core.db import MetaStore
from cleargate.core.models import Document, Finding, RedactionAction
from cleargate.core.states import JobState
from cleargate.pipeline import JobResult, Pipeline, default_stages
from cleargate.redact.writers.pdf import encode_page
from tests import filegen
from tests.fixtures.manifest import SYNTHETIC

TESS = load_settings({}).tesseract_cmd
pytestmark = pytest.mark.skipif(not TESS, reason="Tesseract not installed")


def run_with(tmp_path: Path, writer: Any, src: Path) -> tuple[JobResult, MetaStore, Settings]:
    settings = Settings(
        data_dir=tmp_path / "data",
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=TESS,
        ocr_workers=1,
    )
    store = MetaStore.open(tmp_path / "meta.db")
    pipeline = Pipeline(
        settings, load_policy(), store, stages=replace(default_stages(), writer=writer)
    )
    try:
        (job,) = pipeline.process_batch([src]).jobs
    finally:
        pipeline.close()
    return job, store, settings


class Wrap:
    """Real writer, then ``after(result, findings)`` corrupts its output."""

    name, version = "faulty-writer", "test"

    def __init__(
        self, after: Callable[[Any, list[Finding], Document], None], drop: str | None = None
    ) -> None:
        self.inner = default_stages().writer
        self.after = after
        self.drop = drop

    def apply(
        self, src: Path, doc: Document, findings: list[Finding], out_dir: Path, ctx: Any
    ) -> Any:
        kept = [f for f in findings if not (self.drop and self.drop in f.value)]
        result = self.inner.apply(src, doc, kept, out_dir, ctx)
        for f in findings:  # claim the dropped finding was applied: verification must not trust it
            if f not in kept:
                result.actions.append(
                    RedactionAction(
                        finding_ids=[f.finding_id],
                        locator=f.locator or doc.segments[0].locator,
                        method="token_replace",
                        applied=True,
                    )
                )
        self.after(result, findings, doc)
        return result

    def repair(self, *args: Any) -> int:
        result: int = self.inner.repair(*args)  # the real repair pass (ADR-30)
        return result


def nothing(*_a: object) -> None:
    return None


def rewrite_docx(path: Path, part: str, edit: Callable[[str], str]) -> None:
    with zipfile.ZipFile(path) as zf:
        items = [(i, zf.read(i)) for i in zf.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in items:
            zf.writestr(info, edit(data.decode()).encode() if info.filename == part else data)


def test_value_left_in_the_output_is_blocked_g1(tmp_path: Path) -> None:
    src = filegen.docx(tmp_path / "a.docx", text="Refund to SSN 900-12-3456 approved.")
    job, _store, _ = run_with(tmp_path, Wrap(nothing, drop="900-12-3456"), src)
    assert (job.state, job.rule) == (JobState.BLOCKED, "G1")
    assert job.reason.startswith("V2_LEAK_HITS=")


def test_new_identifier_planted_in_output_only_is_blocked_g2(tmp_path: Path) -> None:
    def plant(result: Any, _f: list[Finding], _d: Document) -> None:
        rewrite_docx(
            result.output_path,
            "word/document.xml",
            lambda xml: xml.replace(
                "</w:body>", "<w:p><w:r><w:t>SSN 900-77-6543</w:t></w:r></w:p></w:body>"
            ),
        )

    src = filegen.docx(tmp_path / "a.docx", text="Quarterly vendor review.")
    job, _, _ = run_with(tmp_path, Wrap(plant), src)
    assert (job.state, job.rule) == (JobState.BLOCKED, "G2")
    assert job.reason == "V3_RESIDUAL_DETERMINISTIC=1"


def test_output_that_does_not_reopen_fails_g0(tmp_path: Path) -> None:
    def corrupt(result: Any, _f: list[Finding], _d: Document) -> None:
        result.output_path.write_bytes(b"PK\x03\x04 not a package")

    job, _, _ = run_with(tmp_path, Wrap(corrupt), filegen.docx(tmp_path / "a.docx"))
    assert (job.state, job.rule, job.reason) == (JobState.FAILED, "G0", "V1_REOPEN_FAILED")


def test_token_without_vault_entry_is_blocked_g5(tmp_path: Path) -> None:
    def foreign(result: Any, _f: list[Finding], _d: Document) -> None:
        rewrite_docx(
            result.output_path,
            "word/document.xml",
            lambda xml: xml.replace(
                "Quarterly vendor review.", "Quarterly vendor review [PERSON_99]."
            ),
        )

    job, _, _ = run_with(tmp_path, Wrap(foreign), filegen.docx(tmp_path / "a.docx"))
    assert (job.state, job.rule, job.reason) == (JobState.BLOCKED, "G5", "V5_INCONSISTENT")


def test_pixels_missed_by_the_writer_are_repaired_then_reverified(
    tmp_path: Path, docs: dict[str, Document]
) -> None:
    """A writer that leaves a name's pixels on a scanned page: V2 reads it in the output OCR,
    the repair pass burns the located boxes, and a fresh verification passes (ADR-30)."""
    src = SYNTHETIC / "planted_scanned.pdf"
    line = next(s for s in docs["planted_scanned.pdf"].segments if "Fenella" in s.text)
    assert line.locator.bbox is not None
    x0, y0, x1, y1 = (int(v) for v in line.locator.bbox)

    def restore_pixels(result: Any, _f: list[Finding], _d: Document) -> None:
        with pymupdf.open(src) as original:
            pix = original[0].get_pixmap(dpi=300, alpha=False)
            clean = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).crop(
                (x0, y0, x1, y1)
            )
        with pymupdf.open(result.output_path) as pdf:
            page = pdf[0]
            pix = page.get_pixmap(dpi=300, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img.paste(clean, (x0, y0))
            page.add_redact_annot(page.rect, fill=(1, 1, 1))
            page.apply_redactions(images=2)  # remove the old raster
            page.insert_image(page.rect, stream=encode_page(img))
            tmp = result.output_path.with_name("tmp.pdf")
            pdf.save(tmp)
        tmp.replace(result.output_path)

    job, store, _ = run_with(tmp_path, Wrap(restore_pixels), src)

    assert job.state is JobState.REVIEW_REQUIRED  # same as without the fault: regions to review
    run = store.run(job.job_id)
    assert run is not None
    report = json.loads(run["report_json"])
    assert report["leak_hits"] == 0
    assert any(a["finding_ids"] == [] and a["applied"] for a in json.loads(run["actions_json"]))


def test_verification_crash_fails_closed(tmp_path: Path) -> None:
    class Boom:
        name, version = "boom", "test"

        def verify(self, *_a: object) -> None:
            raise RuntimeError("verifier exploded")

    settings = Settings(
        data_dir=tmp_path / "data",
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=TESS,
    )
    store = MetaStore.open(tmp_path / "meta.db")
    pipeline = Pipeline(
        settings, load_policy(), store, stages=replace(default_stages(), verifier=Boom())
    )
    try:
        (job,) = pipeline.process_batch([filegen.docx(tmp_path / "a.docx")]).jobs
    finally:
        pipeline.close()
    assert (job.state, job.rule) == (JobState.FAILED, "G0")
