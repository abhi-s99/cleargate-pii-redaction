"""Gate state machine (TR-GT-01/02/03, ADR-09).

``_apply`` is the only code path that changes ``jobs.state``. In one
``BEGIN IMMEDIATE`` transaction it re-reads the current state, checks the
TR-GT-01 whitelist, appends a ``state_history`` row, writes the single-use ticket
the database trigger requires, stores the SafeHandle when entering
``VALIDATED_SAFE``, and updates the job. Any failure rolls everything back.

Two entry points use it:

* ``transition`` (public) for every edge **except** into ``VALIDATED_SAFE``, which
  it always refuses, whatever handle is passed.
* ``decide`` evaluates G0..G7 and, on G7, mints the SafeHandle itself with the gate
  key. It is therefore the only way into ``VALIDATED_SAFE``: a caller cannot
  supply a handle of its own (ADR-22).

Rule ids and reasons must be identifier-like strings, so history can never hold
document content.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import SecretStr

from cleargate.core.db import ALLOWED_TRANSITIONS, MetaStore
from cleargate.core.errors import ClearGateError, ErrorCode, IllegalTransition
from cleargate.core.states import JobState
from cleargate.gate.handle import SafeHandle, mint
from cleargate.gate.rules import GateInput, Verdict, evaluate

_RULE_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
_REASON_RE = re.compile(r"^[A-Za-z0-9_.:=,/\-]{1,200}$")


def is_allowed(src: JobState, dst: JobState) -> bool:
    return (src, dst) in ALLOWED_TRANSITIONS


def _check_labels(rule: str, reason: str) -> None:
    if not _RULE_RE.match(rule) or not _REASON_RE.match(reason):
        raise ClearGateError(ErrorCode.INTERNAL, stage="gate_reason_not_identifier")


def transition(
    store: MetaStore, job_id: str, to_state: JobState, *, rule: str, reason: str
) -> JobState:
    """Move ``job_id`` to any state except ``VALIDATED_SAFE``. Returns the previous state."""
    if to_state is JobState.VALIDATED_SAFE:
        state = store.job_state(job_id)
        raise IllegalTransition(
            job_id=job_id, from_state=state.value if state else "?", to_state=to_state.value
        )
    return _apply(store, job_id, to_state, rule=rule, reason=reason, handle=None)


def _apply(
    store: MetaStore,
    job_id: str,
    to_state: JobState,
    *,
    rule: str,
    reason: str,
    handle: SafeHandle | None,
) -> JobState:
    _check_labels(rule, reason)
    with store.transaction() as conn:
        row = conn.execute("SELECT state FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise ClearGateError(ErrorCode.JOB_NOT_FOUND, job_id=job_id)
        src = JobState(row["state"])
        if not is_allowed(src, to_state):
            raise IllegalTransition(job_id=job_id, from_state=src.value, to_state=to_state.value)
        if to_state is JobState.VALIDATED_SAFE:
            if rule != "G7" or handle is None or handle.job_id != job_id:
                raise IllegalTransition(
                    job_id=job_id, from_state=src.value, to_state=to_state.value
                )
        elif handle is not None:
            raise IllegalTransition(job_id=job_id, from_state=src.value, to_state=to_state.value)
        now = store.now()
        cur = conn.execute(
            "INSERT INTO state_history (job_id, from_state, to_state, rule, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, src.value, to_state.value, rule, reason, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO transition_tickets VALUES (?, ?, ?, ?)",
            (job_id, src.value, to_state.value, cur.lastrowid),
        )
        if handle is not None:
            conn.execute(
                "INSERT INTO safe_handles VALUES (?, ?, ?)", (job_id, handle.to_json(), now)
            )
        conn.execute(
            "UPDATE jobs SET state = ?, rule = ?, reason = ?, updated_at = ? WHERE job_id = ?",
            (to_state.value, rule, reason, now, job_id),
        )
    return src


def decide(
    store: MetaStore,
    gate_input: GateInput,
    *,
    gate_key: SecretStr,
    sanitized_path: Path,
) -> Verdict:
    """Evaluate G0..G7 for a job in PROCESSING and apply the verdict.

    On G7 a SafeHandle is minted over the sanitized file. If minting fails for any
    reason the job ends ``FAILED`` (G0, ``HANDLE_MINT_FAILED``): no handle, no SAFE.
    """
    job_id = gate_input.job_id
    job = store.get_job(job_id)
    if job is None:
        raise ClearGateError(ErrorCode.JOB_NOT_FOUND, job_id=job_id)
    if job["state"] != JobState.PROCESSING.value:
        raise IllegalTransition(job_id=job_id, from_state=job["state"], to_state="decide")
    verdict = evaluate(gate_input)
    handle: SafeHandle | None = None
    if verdict.state is JobState.VALIDATED_SAFE:
        assert gate_input.verification is not None  # G0 guarantees it
        try:
            handle = mint(
                gate_key,
                job_id=job_id,
                sanitized_path=sanitized_path,
                policy_hash=job["policy_hash"],
                verification=gate_input.verification,
                issued_at=store.now(),
            )
        except (ClearGateError, OSError):
            verdict = Verdict(state=JobState.FAILED, rule="G0", reasons=("HANDLE_MINT_FAILED",))
    _apply(store, job_id, verdict.state, rule=verdict.rule, reason=verdict.reason, handle=handle)
    return verdict


def fail(store: MetaStore, job_id: str, code: ErrorCode, *, rule: str = "G0") -> None:
    """Record a failure from RECEIVED (validation) or PROCESSING (crash)."""
    transition(store, job_id, JobState.FAILED, rule=rule, reason=code.value)
