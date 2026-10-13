"""The three PS-2 samples end to end (TRD 14 integration row; brief Phase 7 exit).

Counts only: no value from the samples is read into the test or its messages.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from cleargate.core.config import Settings, load_policy, load_settings
from cleargate.core.db import MetaStore
from cleargate.core.states import JobState
from cleargate.pipeline import BatchResult, Pipeline
from tests.conftest import SAMPLE_FILES

pytestmark = [pytest.mark.samples, pytest.mark.slow]


@pytest.fixture(scope="module")
def batch(
    samples_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[MetaStore, BatchResult]]:
    root = tmp_path_factory.mktemp("samples")
    settings = Settings(
        data_dir=root / "data",
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=load_settings({}).tesseract_cmd,
    )
    store = MetaStore.open(root / "meta.db")
    pipeline = Pipeline(settings, load_policy(), store)
    result = pipeline.process_batch([samples_dir / name for name in SAMPLE_FILES])
    yield store, result
    pipeline.close()
    store.close()


def test_samples_end_in_a_reviewable_state(batch: tuple[MetaStore, BatchResult]) -> None:
    _, result = batch
    states = {j.filename: j.state for j in result.jobs}
    assert set(states.values()) <= {JobState.REVIEW_REQUIRED, JobState.VALIDATED_SAFE}
    # Fig. 3 (face, illegible screenshot) must go to a human (TRD 14).
    assert states[SAMPLE_FILES[0]] is JobState.REVIEW_REQUIRED


def test_samples_verification_is_clean(batch: tuple[MetaStore, BatchResult]) -> None:
    store, result = batch
    for job in result.jobs:
        run = store.run(job.job_id)
        assert run is not None, job.filename
        report = json.loads(run["report_json"])
        actions = json.loads(run["actions_json"])
        assert report["leak_hits"] == 0, job.filename
        assert report["residual_deterministic"] == 0, job.filename
        assert report["uninspected_unmasked"] == 0, job.filename
        assert report["unit_counts_equal"], job.filename
        assert report["srs"] >= 0.8, job.filename
        assert all(a["applied"] for a in actions), job.filename
