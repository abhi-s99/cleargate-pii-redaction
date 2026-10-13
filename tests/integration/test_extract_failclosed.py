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


def test_ocr_disabled_blocks_even_a_plain_docx_thumbnail(tmp_path: Path, policy: Policy) -> None:
    # python-docx's template carries docProps/thumbnail.jpeg; without OCR it is unread.
    state, rule, reason = run_one(
        settings_for(tmp_path, None), policy, filegen.docx(tmp_path / "plain.docx")
    )
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=1,")


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


def test_xxe_in_document_part_is_uninspected(tmp_path: Path, policy: Policy) -> None:
    src = filegen.docx(tmp_path / "src.docx")
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///c:/windows/win.ini">]>'
        b"<d>&x;</d>"
    )
    bad = filegen.rewrite_zip(src, tmp_path / "xxe.docx", add={"customXml/item9.xml": evil})
    state, rule, reason = run_one(settings_for(tmp_path, TESS), policy, bad)
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=1,")


def test_real_extraction_still_blocks_until_verification_exists(
    tmp_path: Path, policy: Policy
) -> None:
    # Everything inspected (the template thumbnail needs OCR), but V2, V3, V5 have not run:
    # never SAFE (ADR-24).
    state, rule, reason = run_one(
        settings_for(tmp_path, TESS), policy, filegen.docx(tmp_path / "plain.docx")
    )
    assert (state, rule, reason) == ("BLOCKED", "G3", "V2_NOT_RUN,V3_NOT_RUN,V5_NOT_RUN")


@pytest.mark.samples
def test_ocr_disabled_sample_pdf_ends_blocked_g3(
    tmp_path: Path, policy: Policy, samples_dir: Path
) -> None:
    pdf = samples_dir / "Cadence_Group_Risk_Management_Policy__v6.0.pdf"
    state, rule, reason = run_one(settings_for(tmp_path, None), policy, pdf)
    assert (state, rule) == ("BLOCKED", "G3")
    assert reason.startswith("UNINSPECTED_PARTS=35,")
