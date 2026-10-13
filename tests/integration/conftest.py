"""Fixtures for pipeline-level tests: isolated data dir, fresh keys, default policy, and the
session-wide extraction of the synthetic fixtures (shared by extraction and detection tests)."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from cleargate.core.config import Policy, Settings, load_policy
from cleargate.core.db import MetaStore
from cleargate.core.models import Document
from cleargate.ingest.validator import validate
from cleargate.pipeline import JobContext, default_stages
from tests.fixtures.manifest import SYNTHETIC, planted_items

FILES = sorted({i.file for i in planted_items()})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
    )


@pytest.fixture
def policy() -> Policy:
    return load_policy()


@pytest.fixture
def store(settings: Settings) -> Iterator[MetaStore]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    s = MetaStore.open(settings.data_dir / "meta.db")
    yield s
    s.close()


def extract_file(path: Path, settings: Settings, job_dir: Path) -> Document:
    policy = load_policy()
    vf = validate(path, policy.limits)
    ctx = JobContext("fixture", "none", job_dir, policy, "", settings, None)  # type: ignore[arg-type]
    return default_stages().extractor_for(vf.fmt).extract(path, vf.fmt, ctx)


@pytest.fixture(scope="session")
def ocr_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    from cleargate.core.config import load_settings

    base = load_settings({})
    return Settings(
        data_dir=tmp_path_factory.mktemp("data"),
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=base.tesseract_cmd,
        ocr_workers=1,
    )


@pytest.fixture(scope="session")
def docs(ocr_settings: Settings, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Document]:
    if not ocr_settings.tesseract_cmd:
        pytest.skip("Tesseract not installed")
    return {
        f: extract_file(SYNTHETIC / f, ocr_settings, tmp_path_factory.mktemp("job")) for f in FILES
    }
