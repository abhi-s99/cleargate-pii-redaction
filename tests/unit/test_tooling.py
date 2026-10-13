"""Repository tooling: style rule, verification matrix, doctor checks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.conftest import SAMPLE_FILES, find_samples_dir

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_matrix  # noqa: E402
import check_style  # noqa: E402
import doctor  # noqa: E402


def test_repository_has_no_emoji_or_em_dash() -> None:
    files = check_style.tracked_files(ROOT)
    problems = [v for p in files if p.is_file() for v in check_style.violations(p)]
    assert problems == []


@pytest.mark.parametrize("bad", ["\u2014", "\u2705", "\U0001f512", "\u2b1c", "\u26a0\ufe0f"])
def test_style_checker_catches_banned_characters(tmp_path: Path, bad: str) -> None:
    f = tmp_path / "x.md"
    f.write_text(f"line one\nline {bad} two\n", encoding="utf-8")
    found = check_style.violations(f)
    assert len(found) == 1
    assert found[0].startswith(f"{f}:2: U+")


def test_style_checker_allows_arrows_and_math(tmp_path: Path) -> None:
    f = tmp_path / "ok.md"
    # arrow, >=, section sign, middle dot, en dash: all allowed
    allowed = " ".join(chr(cp) for cp in (0x2192, 0x2265, 0x00A7, 0x00B7, 0x2013))
    f.write_text(f"x {allowed} y\n", encoding="utf-8")
    assert check_style.violations(f) == []


def test_samples_lookup_returns_none_without_files(tmp_path: Path) -> None:
    (tmp_path / "samples").mkdir()
    assert find_samples_dir(tmp_path, {}) is None


@pytest.mark.parametrize("where", ["samples", "Data", "custom"])
def test_samples_lookup_finds_complete_set_only(tmp_path: Path, where: str) -> None:
    target = tmp_path / where
    target.mkdir()
    env = {"CLEARGATE_SAMPLES_DIR": str(target)} if where == "custom" else {}
    for name in SAMPLE_FILES[:-1]:
        (target / name).write_bytes(b"dummy")
    assert find_samples_dir(tmp_path, env) is None  # incomplete set is not accepted
    (target / SAMPLE_FILES[-1]).write_bytes(b"dummy")
    assert find_samples_dir(tmp_path, env) == target


def test_verification_matrix_is_complete() -> None:
    assert check_matrix.main() == 0


def test_doctor_python_check_passes() -> None:
    name, ok, _ = doctor.check_python()
    assert ok, name


def test_doctor_reports_missing_tesseract() -> None:
    _, ok, detail = doctor.check_tesseract(None)
    assert not ok
    assert "not found" in detail


def test_doctor_reports_missing_spacy_model() -> None:
    _, ok, _ = doctor.check_spacy_model("en_core_web_doesnotexist")
    assert not ok


def test_doctor_reports_unwritable_data_dir(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    _, ok, _ = doctor.check_data_dir(blocker / "sub")
    assert not ok
