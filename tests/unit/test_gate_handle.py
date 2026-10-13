"""SafeHandle mint/verify and the TR-GT-04 store checks (TR-GT-03, TR-GT-04)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cleargate.core.db import MetaStore
from cleargate.core.errors import HandleError
from cleargate.core.states import JobState
from cleargate.gate.handle import (
    SafeHandle,
    mint,
    verification_sha256,
    verify_against_store,
    verify_handle,
)
from cleargate.gate.machine import decide, transition
from tests.unit.gate_support import (
    GATE_KEY,
    OTHER_KEY,
    POLICY_HASH,
    clean_input,
    clean_report,
    open_store,
    processing_job,
    sanitized_file,
)


@pytest.fixture
def store(tmp_path: Path) -> MetaStore:
    s = open_store(tmp_path / "meta.db")
    yield s
    s.close()


@pytest.fixture
def safe_job(store: MetaStore, tmp_path: Path) -> tuple[SafeHandle, Path]:
    processing_job(store)
    path = sanitized_file(tmp_path)
    decide(store, clean_input(), gate_key=GATE_KEY, sanitized_path=path)
    stored = store.handle_json("job-1")
    assert stored is not None
    return SafeHandle.from_json(stored), path


def reason(exc: pytest.ExceptionInfo[HandleError]) -> object:
    return exc.value.details["reason"]


def test_valid_handle_passes_all_checks(
    store: MetaStore, safe_job: tuple[SafeHandle, Path]
) -> None:
    handle, path = safe_job
    verify_handle(handle, GATE_KEY, path)
    verify_against_store(store, handle, GATE_KEY, path)
    assert handle.policy_hash == POLICY_HASH
    assert handle.verification_sha256 == verification_sha256(clean_report())


@pytest.mark.parametrize(
    "field",
    ["job_id", "sanitized_sha256", "policy_hash", "verification_sha256", "issued_at", "mac"],
)
def test_tampering_any_field_is_refused(
    store: MetaStore, safe_job: tuple[SafeHandle, Path], field: str
) -> None:
    handle, path = safe_job
    original = getattr(handle, field)
    tampered = handle.model_copy(
        update={field: ("0" if original[0] != "0" else "1") + original[1:]}
    )
    with pytest.raises(HandleError) as exc:
        verify_handle(tampered, GATE_KEY, path)
    assert reason(exc) == "mac_mismatch"
    with pytest.raises(HandleError):
        verify_against_store(store, tampered, GATE_KEY, path)


def test_wrong_key_is_refused(safe_job: tuple[SafeHandle, Path]) -> None:
    handle, path = safe_job
    with pytest.raises(HandleError) as exc:
        verify_handle(handle, OTHER_KEY, path)
    assert reason(exc) == "mac_mismatch"


def test_sanitized_file_changed_on_disk_is_refused(
    store: MetaStore, safe_job: tuple[SafeHandle, Path]
) -> None:
    handle, path = safe_job
    path.write_bytes(path.read_bytes().replace(b"[PERSON_1]", b"[PERSON_2]"))
    with pytest.raises(HandleError) as exc:
        verify_against_store(store, handle, GATE_KEY, path)
    assert reason(exc) == "sanitized_changed"


def test_single_appended_byte_is_refused(safe_job: tuple[SafeHandle, Path]) -> None:
    handle, path = safe_job
    with path.open("ab") as fh:
        fh.write(b" ")
    with pytest.raises(HandleError) as exc:
        verify_handle(handle, GATE_KEY, path)
    assert reason(exc) == "sanitized_changed"


def test_sanitized_file_deleted_is_refused(safe_job: tuple[SafeHandle, Path]) -> None:
    handle, path = safe_job
    path.unlink()
    with pytest.raises(HandleError) as exc:
        verify_handle(handle, GATE_KEY, path)
    assert reason(exc) == "sanitized_missing"


def test_validly_signed_handle_for_non_safe_job_is_refused(
    store: MetaStore, tmp_path: Path
) -> None:
    # Even a correctly signed handle is useless unless the gate put the job in SAFE.
    processing_job(store)
    transition(store, "job-1", JobState.BLOCKED, rule="G1", reason="V2_LEAK_HITS=1")
    path = sanitized_file(tmp_path)
    handle = mint(
        GATE_KEY,
        job_id="job-1",
        sanitized_path=path,
        policy_hash=POLICY_HASH,
        verification=clean_report(),
        issued_at="2026-10-13T12:00:00+00:00",
    )
    verify_handle(handle, GATE_KEY, path)  # signature alone is fine
    with pytest.raises(HandleError) as exc:
        verify_against_store(store, handle, GATE_KEY, path)
    assert reason(exc) == "job_not_safe"


def test_handle_under_a_different_policy_is_refused(
    store: MetaStore, safe_job: tuple[SafeHandle, Path]
) -> None:
    _, path = safe_job
    other = mint(
        GATE_KEY,
        job_id="job-1",
        sanitized_path=path,
        policy_hash="b" * 64,
        verification=clean_report(),
        issued_at="2026-10-13T12:00:00+00:00",
    )
    with pytest.raises(HandleError) as exc:
        verify_against_store(store, other, GATE_KEY, path)
    assert reason(exc) == "policy_changed"


def test_handle_not_issued_by_the_gate_is_refused(
    store: MetaStore, safe_job: tuple[SafeHandle, Path]
) -> None:
    issued, path = safe_job
    reminted = mint(
        GATE_KEY,
        job_id="job-1",
        sanitized_path=path,
        policy_hash=POLICY_HASH,
        verification=clean_report(),
        issued_at="2099-01-01T00:00:00+00:00",
    )
    assert reminted != issued
    with pytest.raises(HandleError) as exc:
        verify_against_store(store, reminted, GATE_KEY, path)
    assert reason(exc) == "not_issued"


def test_unknown_job_is_refused(store: MetaStore, safe_job: tuple[SafeHandle, Path]) -> None:
    _, path = safe_job
    ghost = mint(
        GATE_KEY,
        job_id="job-404",
        sanitized_path=path,
        policy_hash=POLICY_HASH,
        verification=clean_report("job-404"),
        issued_at="2026-10-13T12:00:00+00:00",
    )
    with pytest.raises(HandleError) as exc:
        verify_against_store(store, ghost, GATE_KEY, path)
    assert reason(exc) == "job_unknown"


def test_verification_hash_tracks_report_content() -> None:
    a = clean_report()
    assert verification_sha256(a) == verification_sha256(clean_report())
    assert verification_sha256(a) != verification_sha256(a.model_copy(update={"crs": 0.5}))


def test_handle_json_round_trip_and_no_key_material(safe_job: tuple[SafeHandle, Path]) -> None:
    handle, _ = safe_job
    assert SafeHandle.from_json(handle.to_json()) == handle
    assert GATE_KEY.get_secret_value() not in handle.to_json()
