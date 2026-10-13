"""Gate state machine: whitelist, SAFE preconditions, decide() (TR-GT-01, TR-GT-03, ADR-09)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from pydantic import SecretStr

from cleargate.core.db import ALLOWED_TRANSITIONS, MetaStore
from cleargate.core.errors import ClearGateError, ErrorCode, IllegalTransition
from cleargate.core.models import Locator
from cleargate.core.states import JobState
from cleargate.gate.handle import SafeHandle, mint, verify_against_store
from cleargate.gate.machine import _apply, decide, fail, is_allowed, transition
from cleargate.gate.rules import GateInput
from tests.unit.gate_support import (
    GATE_KEY,
    POLICY_HASH,
    clean_input,
    clean_report,
    new_job,
    open_store,
    processing_job,
    sanitized_file,
)

S = JobState

# A legal path from RECEIVED to every state (used to set up a source state).
PATH_TO: dict[JobState, list[JobState]] = {
    S.RECEIVED: [],
    S.PROCESSING: [S.PROCESSING],
    S.FAILED: [S.FAILED],
    S.BLOCKED: [S.PROCESSING, S.BLOCKED],
    S.REVIEW_REQUIRED: [S.PROCESSING, S.REVIEW_REQUIRED],
    S.VALIDATED_SAFE: [S.PROCESSING, S.VALIDATED_SAFE],
}


@pytest.fixture
def store(tmp_path: Path) -> MetaStore:
    s = open_store(tmp_path / "meta.db")
    yield s
    s.close()


def a_handle(tmp_path: Path, job_id: str = "job-1") -> SafeHandle:
    return mint(
        GATE_KEY,
        job_id=job_id,
        sanitized_path=sanitized_file(tmp_path),
        policy_hash=POLICY_HASH,
        verification=clean_report(job_id),
        issued_at="2026-10-13T12:00:00+00:00",
    )


def step(store: MetaStore, tmp_path: Path, to: JobState, job_id: str = "job-1") -> None:
    # The only way into SAFE is decide() with a clean GateInput.
    if to is S.VALIDATED_SAFE:
        decide(
            store, clean_input(job_id), gate_key=GATE_KEY, sanitized_path=sanitized_file(tmp_path)
        )
    else:
        transition(store, job_id, to, rule="test", reason="step")


def drive(store: MetaStore, tmp_path: Path, src: JobState) -> None:
    new_job(store)
    for to in PATH_TO[src]:
        step(store, tmp_path, to)


ALL_PAIRS = list(itertools.product(list(JobState), repeat=2))


@pytest.mark.parametrize(
    ("src", "dst"), [p for p in ALL_PAIRS if p in ALLOWED_TRANSITIONS], ids=str
)
def test_allowed_transition_succeeds(
    store: MetaStore, tmp_path: Path, src: JobState, dst: JobState
) -> None:
    drive(store, tmp_path, src)
    step(store, tmp_path, dst)
    assert store.job_state("job-1") is dst


@pytest.mark.parametrize(
    ("src", "dst"), [p for p in ALL_PAIRS if p not in ALLOWED_TRANSITIONS], ids=str
)
def test_illegal_transition_raises_and_changes_nothing(
    store: MetaStore, tmp_path: Path, src: JobState, dst: JobState
) -> None:
    drive(store, tmp_path, src)
    before = len(store.history("job-1"))
    with pytest.raises(IllegalTransition) as exc_info:
        step(store, tmp_path, dst)
    assert exc_info.value.code is ErrorCode.ILLEGAL_TRANSITION
    assert store.job_state("job-1") is src
    assert len(store.history("job-1")) == before
    assert store.conn.execute("SELECT COUNT(*) FROM transition_tickets").fetchone()[0] == 0


def test_whitelist_is_exactly_trd_gt_01() -> None:
    assert len(ALLOWED_TRANSITIONS) == 8
    assert not any(is_allowed(S.VALIDATED_SAFE, d) for d in JobState)
    assert not any(is_allowed(S.BLOCKED, d) for d in JobState)
    assert not any(is_allowed(S.FAILED, d) for d in JobState)
    assert {d for d in JobState if is_allowed(S.PROCESSING, d)} == {
        S.FAILED,
        S.BLOCKED,
        S.REVIEW_REQUIRED,
        S.VALIDATED_SAFE,
    }


@pytest.mark.parametrize("rule", ["G7", "G6", "review", "ingest"])
def test_public_transition_can_never_enter_safe(store: MetaStore, rule: str) -> None:
    processing_job(store)
    with pytest.raises(IllegalTransition):
        transition(store, "job-1", S.VALIDATED_SAFE, rule=rule, reason="ok")
    assert store.job_state("job-1") is S.PROCESSING
    assert store.handle_json("job-1") is None


@pytest.mark.parametrize("rule", ["G6", "G1", "review"])
def test_internal_apply_requires_rule_g7(store: MetaStore, tmp_path: Path, rule: str) -> None:
    processing_job(store)
    with pytest.raises(IllegalTransition):
        _apply(store, "job-1", S.VALIDATED_SAFE, rule=rule, reason="x", handle=a_handle(tmp_path))
    assert store.job_state("job-1") is S.PROCESSING


def test_internal_apply_requires_a_handle(store: MetaStore) -> None:
    processing_job(store)
    with pytest.raises(IllegalTransition):
        _apply(store, "job-1", S.VALIDATED_SAFE, rule="G7", reason="ok", handle=None)
    assert store.handle_json("job-1") is None


def test_internal_apply_requires_handle_for_the_same_job(store: MetaStore, tmp_path: Path) -> None:
    processing_job(store)
    other = a_handle(tmp_path, "job-2")
    with pytest.raises(IllegalTransition):
        _apply(store, "job-1", S.VALIDATED_SAFE, rule="G7", reason="ok", handle=other)


def test_internal_apply_refuses_handle_for_non_safe_target(
    store: MetaStore, tmp_path: Path
) -> None:
    processing_job(store)
    with pytest.raises(IllegalTransition):
        _apply(store, "job-1", S.BLOCKED, rule="G1", reason="x", handle=a_handle(tmp_path))


@pytest.mark.parametrize(
    ("rule", "reason"),
    [
        ("G1", "leak of Hortensia Blyth"),  # spaces: free text
        ("G1", "x" * 201),
        ("G 1", "ok"),
        ("G1", ""),
        ("G1", "name\nline"),
    ],
)
def test_history_labels_must_be_identifiers(store: MetaStore, rule: str, reason: str) -> None:
    processing_job(store)
    with pytest.raises(ClearGateError):
        transition(store, "job-1", S.BLOCKED, rule=rule, reason=reason)
    assert store.job_state("job-1") is S.PROCESSING


def test_unknown_job(store: MetaStore) -> None:
    with pytest.raises(ClearGateError) as exc_info:
        transition(store, "nope", S.PROCESSING, rule="ingest", reason="x")
    assert exc_info.value.code is ErrorCode.JOB_NOT_FOUND


def test_fail_from_received(store: MetaStore) -> None:
    new_job(store)
    fail(store, "job-1", ErrorCode.ENCRYPTED, rule="ingest")
    assert store.job_state("job-1") is S.FAILED
    assert store.history("job-1")[-1]["reason"] == "ENCRYPTED"


# --------------------------------------------------------------------- decide()


def test_decide_clean_input_mints_handle_and_is_safe(store: MetaStore, tmp_path: Path) -> None:
    processing_job(store)
    path = sanitized_file(tmp_path)
    verdict = decide(store, clean_input(), gate_key=GATE_KEY, sanitized_path=path)
    assert (verdict.state, verdict.rule) == (S.VALIDATED_SAFE, "G7")
    assert store.job_state("job-1") is S.VALIDATED_SAFE
    stored = store.handle_json("job-1")
    assert stored is not None
    verify_against_store(store, SafeHandle.from_json(stored), GATE_KEY, path)
    assert store.get_job("job-1")["rule"] == "G7"


def test_decide_blocking_input_issues_no_handle(store: MetaStore, tmp_path: Path) -> None:
    processing_job(store)
    gi = clean_input().model_copy(
        update={
            "coverage": clean_input().coverage.model_copy(
                update={"uninspected": [Locator(part="page", page=3)]}
            )
        }
    )
    verdict = decide(store, gi, gate_key=GATE_KEY, sanitized_path=sanitized_file(tmp_path))
    assert (verdict.state, verdict.rule) == (S.BLOCKED, "G3")
    assert store.job_state("job-1") is S.BLOCKED
    assert store.handle_json("job-1") is None
    assert store.history("job-1")[-1]["reason"] == "UNINSPECTED_PARTS=1"


def test_decide_without_sanitized_file_fails_closed(store: MetaStore, tmp_path: Path) -> None:
    processing_job(store)
    verdict = decide(store, clean_input(), gate_key=GATE_KEY, sanitized_path=tmp_path / "missing")
    assert (verdict.state, verdict.rule, verdict.reasons) == (
        S.FAILED,
        "G0",
        ("HANDLE_MINT_FAILED",),
    )
    assert store.job_state("job-1") is S.FAILED
    assert store.handle_json("job-1") is None


def test_decide_with_invalid_gate_key_fails_closed(store: MetaStore, tmp_path: Path) -> None:
    processing_job(store)
    verdict = decide(
        store, clean_input(), gate_key=SecretStr("short"), sanitized_path=sanitized_file(tmp_path)
    )
    assert verdict.state is S.FAILED
    assert store.handle_json("job-1") is None


@pytest.mark.parametrize("src", [S.RECEIVED, S.REVIEW_REQUIRED, S.BLOCKED, S.VALIDATED_SAFE])
def test_decide_only_from_processing(store: MetaStore, tmp_path: Path, src: JobState) -> None:
    drive(store, tmp_path, src)
    with pytest.raises(IllegalTransition):
        decide(store, clean_input(), gate_key=GATE_KEY, sanitized_path=sanitized_file(tmp_path))
    assert store.job_state("job-1") is src


def test_review_loop_reaches_safe_only_through_re_decision(
    store: MetaStore, tmp_path: Path
) -> None:
    processing_job(store)
    path = sanitized_file(tmp_path)
    first = decide(
        store,
        GateInput(job_id="job-1", verification=clean_report(), open_review_items=2),
        gate_key=GATE_KEY,
        sanitized_path=path,
    )
    assert first.state is S.REVIEW_REQUIRED
    transition(store, "job-1", S.PROCESSING, rule="review", reason="decisions_submitted")
    second = decide(store, clean_input(), gate_key=GATE_KEY, sanitized_path=path)
    assert second.state is S.VALIDATED_SAFE
    assert [r["to_state"] for r in store.history("job-1")] == [
        "PROCESSING",
        "REVIEW_REQUIRED",
        "PROCESSING",
        "VALIDATED_SAFE",
    ]
