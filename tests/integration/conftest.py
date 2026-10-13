"""Fixtures for pipeline-level tests: isolated data dir, fresh keys, default policy."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from cleargate.core.config import Policy, Settings, load_policy
from cleargate.core.db import MetaStore


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
