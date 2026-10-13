"""meta.db schema and database-level gate guards (TR-GT-02, TR-SEC-02, TR-SEC-06, FR-16)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cleargate.core.db import ALLOWED_TRANSITIONS, MetaStore
from cleargate.core.errors import HandleError
from cleargate.core.models import EntityType, Evidence, Finding
from cleargate.core.states import JobState
from cleargate.gate.handle import SafeHandle, verify_against_store
from cleargate.gate.machine import decide, transition
from tests.unit.gate_support import (
    GATE_KEY,
    clean_input,
    new_job,
    open_store,
    processing_job,
    sanitized_file,
)

RAW = "Wilhelmina Trevaskis-Oduya"  # invented


@pytest.fixture
def store(tmp_path: Path) -> MetaStore:
    s = open_store(tmp_path / "meta.db")
    yield s
    s.close()


def state(store: MetaStore, job_id: str = "job-1") -> str:
    return str(store.get_job(job_id)["state"])


def test_wal_mode_and_foreign_keys(store: MetaStore) -> None:
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_whitelist_table_matches_trd(store: MetaStore) -> None:
    rows = {
        (JobState(a), JobState(b))
        for a, b in store.conn.execute("SELECT from_state, to_state FROM allowed_transitions")
    }
    assert rows == ALLOWED_TRANSITIONS
    assert len(rows) == 8


def test_reopen_is_idempotent(tmp_path: Path) -> None:
    open_store(tmp_path / "m.db").close()
    s = open_store(tmp_path / "m.db")
    assert s.conn.execute("SELECT COUNT(*) FROM allowed_transitions").fetchone()[0] == 8
    assert s.conn.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0] == 1
    s.close()


@pytest.mark.parametrize("target", [s.value for s in JobState if s is not JobState.RECEIVED])
def test_direct_update_from_received_is_rejected(store: MetaStore, target: str) -> None:
    new_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="GATE"):
        store.conn.execute("UPDATE jobs SET state = ? WHERE job_id = 'job-1'", (target,))
    assert state(store) == "RECEIVED"


def test_direct_update_to_safe_from_processing_is_rejected(store: MetaStore) -> None:
    processing_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="without matching history"):
        store.conn.execute("UPDATE jobs SET state = 'VALIDATED_SAFE' WHERE job_id = 'job-1'")
    assert state(store) == "PROCESSING"


def test_direct_update_on_allowed_edge_still_needs_history(store: MetaStore) -> None:
    processing_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="without matching history"):
        store.conn.execute("UPDATE jobs SET state = 'BLOCKED' WHERE job_id = 'job-1'")


def forge(
    store: MetaStore,
    src: str,
    dst: str,
    *,
    ticket: str = "newest",
    handle_json: str | None = None,
) -> None:
    """Attack the gate with raw SQL in one transaction, the way a buggy caller might.

    ticket: "none" (history only), "newest" (ticket for the forged row) or
    "stale" (ticket pointing at an older history row).
    """
    with store.transaction():
        cur = store.conn.execute(
            "INSERT INTO state_history (job_id, from_state, to_state, rule, reason, created_at)"
            " VALUES ('job-1', ?, ?, 'G7', 'forged', 'x')",
            (src, dst),
        )
        if ticket != "none":
            hid = cur.lastrowid
            if ticket == "stale":
                hid = store.conn.execute("SELECT MIN(history_id) FROM state_history").fetchone()[0]
            store.conn.execute(
                "INSERT INTO transition_tickets VALUES ('job-1', ?, ?, ?)", (src, dst, hid)
            )
        if handle_json is not None:
            store.conn.execute("INSERT INTO safe_handles VALUES ('job-1', ?, 'x')", (handle_json,))
        store.conn.execute("UPDATE jobs SET state = ? WHERE job_id = 'job-1'", (dst,))


def test_forged_history_row_without_ticket_is_rejected(store: MetaStore) -> None:
    processing_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="without matching history"):
        forge(store, "PROCESSING", "BLOCKED", ticket="none")
    assert state(store) == "PROCESSING"
    assert len(store.history("job-1")) == 1  # forged row rolled back


def test_ticket_must_point_at_newest_history_row(store: MetaStore) -> None:
    processing_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="without matching history"):
        forge(store, "PROCESSING", "BLOCKED", ticket="stale")
    assert state(store) == "PROCESSING"


def test_forged_history_and_ticket_to_safe_without_handle_is_rejected(store: MetaStore) -> None:
    processing_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="requires a SafeHandle"):
        forge(store, "PROCESSING", "VALIDATED_SAFE")
    assert state(store) == "PROCESSING"


def test_whitelist_edge_not_in_table_is_rejected_even_with_ticket(store: MetaStore) -> None:
    new_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="whitelist"):
        forge(store, "RECEIVED", "BLOCKED")
    assert state(store) == "RECEIVED"


def test_fully_forged_safe_row_is_refused_by_handle_check(store: MetaStore, tmp_path: Path) -> None:
    # Someone with raw DB access forges every row, including a handle. The database
    # cannot stop that; the HMAC can, because the forger does not have the gate key.
    processing_job(store)
    path = sanitized_file(tmp_path)
    fake = SafeHandle(
        job_id="job-1",
        sanitized_sha256="0" * 64,
        policy_hash="a" * 64,
        verification_sha256="0" * 64,
        issued_at="2026-10-13T12:00:00+00:00",
        mac="f" * 64,
    )
    forge(store, "PROCESSING", "VALIDATED_SAFE", handle_json=fake.to_json())
    assert state(store) == "VALIDATED_SAFE"  # documented limit: SQLite is not the boundary
    with pytest.raises(HandleError) as exc_info:
        verify_against_store(store, fake, GATE_KEY, path)
    assert exc_info.value.details["reason"] == "mac_mismatch"


def test_check_constraint_rejects_unknown_state(store: MetaStore) -> None:
    new_job(store)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE jobs SET state = 'APPROVED' WHERE job_id = 'job-1'")


def test_jobs_can_only_be_created_in_received(store: MetaStore) -> None:
    store.create_batch("batch-1", "p", "a" * 64)
    with pytest.raises(sqlite3.IntegrityError, match="RECEIVED"):
        store.conn.execute(
            "INSERT INTO jobs (job_id, batch_id, filename, policy_hash, state, created_at,"
            " updated_at) VALUES ('j', 'batch-1', 'f', 'h', 'VALIDATED_SAFE', 'x', 'x')"
        )


def test_policy_hash_is_immutable(store: MetaStore) -> None:
    new_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.conn.execute("UPDATE jobs SET policy_hash = 'b' WHERE job_id = 'job-1'")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE state_history SET to_state = 'VALIDATED_SAFE'",
        "UPDATE state_history SET reason = 'edited'",
        "DELETE FROM state_history",
    ],
)
def test_history_is_append_only(store: MetaStore, sql: str) -> None:
    processing_job(store)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(sql)
    assert len(store.history("job-1")) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO allowed_transitions VALUES ('RECEIVED', 'VALIDATED_SAFE')",
        "DELETE FROM allowed_transitions",
        "UPDATE allowed_transitions SET to_state = 'VALIDATED_SAFE'",
    ],
)
def test_whitelist_table_is_frozen(store: MetaStore, sql: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        store.conn.execute(sql)


def test_handles_are_immutable(store: MetaStore, tmp_path: Path) -> None:
    processing_job(store)
    decide(store, clean_input(), gate_key=GATE_KEY, sanitized_path=sanitized_file(tmp_path))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.conn.execute("UPDATE safe_handles SET handle_json = '{}'")


def test_ticket_is_consumed_by_transition(store: MetaStore) -> None:
    processing_job(store)
    assert store.conn.execute("SELECT COUNT(*) FROM transition_tickets").fetchone()[0] == 0


def test_history_records_every_change_with_rule_reason_and_time(store: MetaStore) -> None:
    processing_job(store)
    transition(store, "job-1", JobState.REVIEW_REQUIRED, rule="G6", reason="OPEN_REVIEW_ITEMS=2")
    transition(store, "job-1", JobState.PROCESSING, rule="review", reason="decisions_submitted")
    rows = [
        (r["from_state"], r["to_state"], r["rule"], r["reason"]) for r in store.history("job-1")
    ]
    assert rows == [
        ("RECEIVED", "PROCESSING", "ingest", "validated"),
        ("PROCESSING", "REVIEW_REQUIRED", "G6", "OPEN_REVIEW_ITEMS=2"),
        ("REVIEW_REQUIRED", "PROCESSING", "review", "decisions_submitted"),
    ]
    stamps = [r["created_at"] for r in store.history("job-1")]
    assert stamps == sorted(stamps)
    assert all(s.startswith("2026-10-13T12:00:") for s in stamps)


def test_delete_batch_removes_jobs_history_and_findings(store: MetaStore) -> None:
    processing_job(store)
    store.add_findings("job-1", [make_finding()])
    store.delete_batch("batch-1")
    for table in ("jobs", "state_history", "findings", "batches", "transition_tickets"):
        assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0  # noqa: S608


def make_finding() -> Finding:
    return Finding(
        finding_id="f1",
        segment_id="doc1:4",
        start=3,
        end=3 + len(RAW),
        entity_type=EntityType.PERSON,
        risk="MEDIUM",
        tier="CORROBORATED",
        evidence=[Evidence(detector="ner", layer="L3", rule_id="spacy.PERSON")],
        value=RAW,
        value_hmac="c" * 64,
        preview="Wi****ya",
        decision="auto_redact",
        token="[PERSON_1]",
    )


def test_findings_are_stored_without_raw_values(store: MetaStore, tmp_path: Path) -> None:
    new_job(store)
    assert store.add_findings("job-1", [make_finding()]) == 1
    (row,) = store.findings("job-1")
    assert row["entity_type"] == "PERSON"
    assert row["token"] == "[PERSON_1]"
    assert "value" not in row.keys()  # noqa: SIM118 (sqlite3.Row has no __contains__ on names)
    assert all(RAW not in str(v) for v in tuple(row))
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    blob = b"".join(p.read_bytes() for p in tmp_path.glob("meta.db*"))
    assert RAW.encode() not in blob
    assert b"Wilhelmina" not in blob
