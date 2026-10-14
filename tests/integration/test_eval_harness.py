"""Evaluation harness end to end on synthetic fixtures (FR-15, TRD sections 9 and 14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cleargate.core.config import load_settings
from eval import run_eval
from eval.gold import from_manifest
from eval.harness import evaluate
from tests.fixtures.manifest import SYNTHETIC

TESS = load_settings({}).tesseract_cmd
pytestmark = pytest.mark.skipif(not TESS, reason="Tesseract not installed")


def test_planted_docx_and_png_score_without_leaks() -> None:
    files = [SYNTHETIC / "planted.docx", SYNTHETIC / "planted.png"]
    run = evaluate(files, lambda docs: from_manifest(docs, SYNTHETIC))
    assert [j.file for j in run.jobs] == ["planted.docx", "planted.png"]
    for j in run.jobs:
        assert j.state in ("VALIDATED_SAFE", "REVIEW_REQUIRED")
        assert j.leaks == {}
        assert j.gold_unextracted == 0
        assert j.srs is not None
        assert j.srs >= 0.8
    found = sum(p.found for j in run.jobs for p in j.overlap.values())
    gold = sum(p.gold for j in run.jobs for p in j.overlap.values())
    assert gold >= 25
    assert found / gold >= 0.95
    docx = run.jobs[0]
    assert (docx.regions_found, docx.regions_gold) == (1, 1)
    assert docx.keeps_redacted == 0


def test_report_renders_counts_only(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    code = run_eval.main(["--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert code == 0
    assert "Leak rate" in text
    assert "Calibration of the review threshold" in text
    from tests.fixtures.manifest import planted_items

    for item in planted_items():
        assert item.value not in text, item.id


def test_samples_mode_refuses_without_gold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run_eval, "GOLD_DIR", tmp_path)
    assert run_eval.main(["--samples", "--out", str(tmp_path / "x.md")]) == 2
    assert "eval/gold" in capsys.readouterr().out
    assert not (tmp_path / "x.md").exists()


def test_threshold_is_never_written_from_synthetic_data(tmp_path: Path) -> None:
    before = run_eval.POLICY.read_bytes()
    assert run_eval.main(["--out", str(tmp_path / "r.md"), "--write-threshold"]) == 2
    assert run_eval.POLICY.read_bytes() == before
