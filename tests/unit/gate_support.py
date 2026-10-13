"""Shared helpers for gate tests: a store with a deterministic clock, keys, inputs."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import SecretStr

from cleargate.core.db import MetaStore
from cleargate.core.models import ALL_CHECKS, VerificationReport
from cleargate.core.states import JobState
from cleargate.gate.machine import transition
from cleargate.gate.rules import GateInput

GATE_KEY = SecretStr("test-gate-key-" + "k" * 32)
OTHER_KEY = SecretStr("other-gate-key-" + "z" * 32)
POLICY_HASH = "a" * 64


def fixed_clock() -> Callable[[], datetime]:
    ticks = itertools.count()
    base = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    return lambda: base + timedelta(seconds=next(ticks))


def open_store(path: Path) -> MetaStore:
    return MetaStore.open(path, clock=fixed_clock())


def new_job(store: MetaStore, job_id: str = "job-1", batch_id: str = "batch-1") -> str:
    exists = store.conn.execute("SELECT 1 FROM batches WHERE batch_id = ?", (batch_id,))
    if exists.fetchone() is None:
        store.create_batch(batch_id, "cadence-default", POLICY_HASH)
    store.create_job(job_id, batch_id, "original.docx", POLICY_HASH, fmt="docx")
    return job_id


def processing_job(store: MetaStore, job_id: str = "job-1") -> str:
    new_job(store, job_id)
    transition(store, job_id, JobState.PROCESSING, rule="ingest", reason="validated")
    return job_id


def clean_report(job_id: str = "job-1") -> VerificationReport:
    return VerificationReport(
        job_id=job_id, checks_run=ALL_CHECKS, reopen_ok=True, srs=0.97, crs=0.95
    )


def clean_input(job_id: str = "job-1") -> GateInput:
    return GateInput(job_id=job_id, verification=clean_report(job_id))


def sanitized_file(tmp_path: Path, text: str = "[PERSON_1] approved the policy.\n") -> Path:
    path = tmp_path / "sanitized.txt"
    path.write_text(text, encoding="utf-8")
    return path
