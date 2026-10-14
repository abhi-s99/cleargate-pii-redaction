"""Extraction failure paths end non-SAFE (Architecture 6, TRD 14 fault injection)."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from cleargate.core.config import Policy, Settings, load_settings
from cleargate.core.db import MetaStore
from cleargate.core.errors import ErrorCode, OcrError
from cleargate.extract.ocr import OcrEngine
from cleargate.pipeline import Pipeline
from tests import filegen
from tests.fixtures.manifest import SYNTHETIC

TESS = load_settings({}).tesseract_cmd
pytestmark = pytest.mark.skipif(not TESS, reason="Tesseract not installed")


def settings_for(tmp_path: Path, tesseract: str | None) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=tesseract,
        ocr_workers=1,
    )


def run_one(settings: Settings, policy: Policy, path: Path) -> tuple[str, str, str]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = MetaStore.open(settings.data_dir / "meta.db")
    try:
        (job,) = Pipeline(settings, policy, store).process_batch([path]).jobs
        return job.state.value, job.rule, job.reason
    finally:
        store.close()


@pytest.mark.parametrize("tesseract", [None, "C:/nowhere/tesseract.exe"])
def test_ocr_disabled_scanned_pdf_ends_blocked_g3(
    tmp_path: Path, policy: Policy, tesseract: str | None
) -> None:
    state, rule, reason = run_one(
        settings_for(tmp_path, tesseract), policy, SYNTHETIC / "planted_scanned.pdf"
    )
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=2")


def test_ocr_disabled_docx_with_body_images_ends_blocked(tmp_path: Path, policy: Policy) -> None:
    # Body images cannot be read without OCR and cannot be dropped: never SAFE.
    state, rule, reason = run_one(settings_for(tmp_path, None), policy, SYNTHETIC / "planted.docx")
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=")


def test_ocr_disabled_unread_thumbnail_is_removed_not_trusted(
    tmp_path: Path, policy: Policy
) -> None:
    # python-docx's template thumbnail is unread without OCR; the writer removes it (TR-RD-10),
    # so nothing unread reaches the output and the job can be verified (ADR-29).
    import zipfile

    settings = settings_for(tmp_path, None)
    state, rule, _ = run_one(settings, policy, filegen.docx(tmp_path / "plain.docx"))
    assert (state, rule) == ("VALIDATED_SAFE", "G7")
    (out,) = (settings.data_dir / "jobs").glob("*/out/redacted.docx")
    with zipfile.ZipFile(out) as zf:
        assert not [n for n in zf.namelist() if "thumbnail" in n]


def test_ocr_disabled_native_pdf_with_image_ends_blocked(tmp_path: Path, policy: Policy) -> None:
    state, rule, reason = run_one(
        settings_for(tmp_path, None), policy, SYNTHETIC / "planted_native.pdf"
    )
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=1")  # the embedded image


def test_ocr_timeout_marks_page_uninspected(
    tmp_path: Path, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(self: OcrEngine, *_a: object, **_k: object) -> None:
        raise OcrError(ErrorCode.OCR_TIMEOUT, page=1, timeout_s=1)

    monkeypatch.setattr(OcrEngine, "ocr", timeout)
    base = load_settings({})
    state, rule, reason = run_one(
        settings_for(tmp_path, base.tesseract_cmd),
        policy,
        filegen.png(tmp_path / "x.png", size=(300, 120)),
    )
    assert (state, rule) == ("BLOCKED", "G3")
    assert "UNINSPECTED_PARTS=1" in reason


def test_corrupt_image_part_in_docx_ends_blocked(tmp_path: Path, policy: Policy) -> None:
    src = SYNTHETIC / "planted.docx"
    bad = filegen.rewrite_zip(
        src,
        tmp_path / "corrupt.docx",
        replace={"word/media/image1.png": b"\x89PNG\r\n\x1a\nbroken"},
    )
    base = load_settings({})
    state, rule, reason = run_one(settings_for(tmp_path, base.tesseract_cmd), policy, bad)
    assert (state, rule) == ("BLOCKED", "G3")
    assert "UNINSPECTED_PARTS=1" in reason


XXE = (
    b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///c:/windows/win.ini">]><d>&x;</d>'
)


def test_xxe_in_a_referenced_part_is_uninspected_and_blocks(tmp_path: Path, policy: Policy) -> None:
    # styles.xml is referenced by the document: it cannot be dropped, so the gate blocks.
    src = filegen.docx(tmp_path / "src.docx")
    bad = filegen.rewrite_zip(src, tmp_path / "xxe.docx", replace={"word/styles.xml": XXE})
    state, rule, reason = run_one(settings_for(tmp_path, TESS), policy, bad)
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=1,")


def test_xxe_in_an_unreferenced_part_is_never_parsed_and_is_removed(
    tmp_path: Path, policy: Policy
) -> None:
    import zipfile

    src = filegen.docx(tmp_path / "src.docx")
    bad = filegen.rewrite_zip(src, tmp_path / "xxe.docx", add={"customXml/item9.xml": XXE})
    settings = settings_for(tmp_path, TESS)
    state, _, _ = run_one(settings, policy, bad)
    assert state == "VALIDATED_SAFE"
    (out,) = (settings.data_dir / "jobs").glob("*/out/redacted.docx")
    with zipfile.ZipFile(out) as zf:
        assert "customXml/item9.xml" not in zf.namelist()


def test_full_pipeline_verifies_a_clean_docx_with_all_checks(
    tmp_path: Path, policy: Policy
) -> None:
    # Phase 7: every check V1..V6 ran, so a clean file can reach SAFE (ADR-24 satisfied).
    import json

    settings = settings_for(tmp_path, TESS)
    state, rule, reason = run_one(settings, policy, filegen.docx(tmp_path / "plain.docx"))
    assert (state, rule, reason) == ("VALIDATED_SAFE", "G7", "all_rules_passed")
    store = MetaStore.open(settings.data_dir / "meta.db")
    try:
        (row,) = store.conn.execute("SELECT report_json FROM runs").fetchall()
        assert sorted(json.loads(row[0])["checks_run"]) == ["V1", "V2", "V3", "V4", "V5", "V6"]
    finally:
        store.close()


@pytest.mark.samples
def test_ocr_disabled_sample_pdf_ends_blocked_g3(
    tmp_path: Path, policy: Policy, samples_dir: Path
) -> None:
    pdf = samples_dir / "Cadence_Group_Risk_Management_Policy__v6.0.pdf"
    state, rule, reason = run_one(settings_for(tmp_path, None), policy, pdf)
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=35,")


def test_ocr_worker_pool_matches_in_process_ocr(ocr_settings: Settings, tmp_path: Path) -> None:
    """TR-SEC-07, ADR-34: the spawned, memory-limited OCR pool gives the same text."""
    from tests.integration.conftest import extract_file

    pooled = ocr_settings.model_copy(
        update={"ocr_workers": 2, "data_dir": tmp_path / "pool", "worker_mem_mb": 6144}
    )
    (tmp_path / "pool").mkdir()
    a = extract_file(SYNTHETIC / "planted_scanned.pdf", ocr_settings, tmp_path / "j1")
    b = extract_file(SYNTHETIC / "planted_scanned.pdf", pooled, tmp_path / "j2")
    assert b.coverage.issues == a.coverage.issues
    assert [s.text for s in b.segments] == [s.text for s in a.segments]
    assert len(b.regions) == len(a.regions)
