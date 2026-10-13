"""The confidential sample set is where tests expect it (brief section 1). No content is read."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import ROOT, SAMPLE_FILES

# Approximate sizes from the design-time profile (brief section 1): within a factor of 2.
EXPECTED_BYTES = {
    "Cadence_Group_Risk_Management_Policy__v6.0.pdf": 14_000_000,
    "Cadence_TPRM_Training.docx": 4_800_000,
    "Cadence_Financial_Group_Organizational_Pack.pptx": 72_000,
}


@pytest.mark.samples
@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_sample_file_present_with_expected_size(samples_dir: Path, name: str) -> None:
    size = (samples_dir / name).stat().st_size
    assert EXPECTED_BYTES[name] / 2 < size < EXPECTED_BYTES[name] * 2


@pytest.mark.samples
def test_samples_dir_is_git_ignored(samples_dir: Path) -> None:
    rel = samples_dir.resolve().relative_to(ROOT)
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(rel / SAMPLE_FILES[0])], cwd=ROOT, check=False
    )
    assert result.returncode == 0, "sample directory must be git-ignored"
