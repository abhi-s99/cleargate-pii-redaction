"""Shared pytest configuration.

* Sockets are disabled for every test via ``--disable-socket`` in pyproject
  (TR-SEC-01).
* Tests marked ``samples`` need the confidential case files. They are looked up
  in ``CLEARGATE_SAMPLES_DIR``, then ``samples/``, then ``Data/`` (ADR-15) and
  are skipped when the files are absent, so a clean clone stays green.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest
from hypothesis import settings

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FILES = (
    "Cadence_Group_Risk_Management_Policy__v6.0.pdf",
    "Cadence_TPRM_Training.docx",
    "Cadence_Financial_Group_Organizational_Pack.pptx",
)

settings.register_profile("ci", max_examples=200, deadline=None)
settings.register_profile("dev", max_examples=100, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


def find_samples_dir(root: Path = ROOT, env: Mapping[str, str] = os.environ) -> Path | None:
    candidates = [env.get("CLEARGATE_SAMPLES_DIR"), root / "samples", root / "Data"]
    for cand in candidates:
        if cand and all((Path(cand) / f).is_file() for f in SAMPLE_FILES):
            return Path(cand)
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if find_samples_dir() is not None:
        return
    skip = pytest.mark.skip(reason="sample files not present (samples/ or Data/)")
    for item in items:
        if "samples" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    found = find_samples_dir()
    if found is None:
        pytest.skip("sample files not present")
    return found
