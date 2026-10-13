"""Metadata store ``meta.db`` (SQLite, WAL) with database-level gate guards.

Tables: ``batches``, ``jobs``, ``state_history`` (append-only), ``transition_tickets``,
``safe_handles``, ``findings`` (no raw values), ``review_log``, ``reports``.

Guards enforced by SQLite itself, so a stray ``UPDATE`` cannot bypass the gate
(TR-GT-02, ADR-09, ADR-20):

* ``jobs.state`` has a ``CHECK`` constraint on the six state names, and a new job
  can only be inserted in ``RECEIVED``.
* An ``AFTER UPDATE OF state`` trigger aborts unless (a) the edge is in the
  ``allowed_transitions`` table (a copy of the TR-GT-01 whitelist), (b) a ticket for
  exactly this ``(job_id, from_state, to_state)`` exists, and (c) the ticket points
  at the newest ``state_history`` row, whose states match. The trigger then
  consumes the ticket. ``gate.machine.transition`` writes history, ticket and
  update in one transaction, which is how "inserted in the same transaction" is
  realised: SQLite has no transaction id.
* Entering ``VALIDATED_SAFE`` additionally needs a ``safe_handles`` row.
* ``state_history`` rows can never be updated, and only deleted after their job
  is gone (batch deletion, TR-SEC-06).

Anyone with raw write access to the file can still drop the triggers; SQLite is
not a security boundary. The boundary is the HMAC on the SafeHandle, which a
forged row cannot reproduce without the gate key (tested).

No column holds raw document content. ``findings`` rows are built from
``Finding.model_dump``, which excludes the raw value (TR-SEC-02).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cleargate.core.models import Finding
from cleargate.core.states import JobState

SCHEMA_VERSION = 2

ALLOWED_TRANSITIONS: frozenset[tuple[JobState, JobState]] = frozenset(
    {
        (JobState.RECEIVED, JobState.PROCESSING),
        (JobState.RECEIVED, JobState.FAILED),
        (JobState.PROCESSING, JobState.FAILED),
        (JobState.PROCESSING, JobState.BLOCKED),
        (JobState.PROCESSING, JobState.REVIEW_REQUIRED),
        (JobState.PROCESSING, JobState.VALIDATED_SAFE),
        (JobState.REVIEW_REQUIRED, JobState.PROCESSING),
        (JobState.REVIEW_REQUIRED, JobState.BLOCKED),
    }
)

_STATES_SQL = ", ".join(f"'{s.value}'" for s in JobState)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS batches (
    batch_id    TEXT PRIMARY KEY,
    policy_name TEXT NOT NULL,
    policy_hash TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    batch_id    TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    fmt         TEXT,
    sha256      TEXT,
    size_bytes  INTEGER,
    policy_hash TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'RECEIVED' CHECK (state IN ({_STATES_SQL})),
    rule        TEXT,
    reason      TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS allowed_transitions (
    from_state TEXT NOT NULL,
    to_state   TEXT NOT NULL,
    PRIMARY KEY (from_state, to_state)
);

CREATE TABLE IF NOT EXISTS state_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL,
    from_state TEXT NOT NULL CHECK (from_state IN ({_STATES_SQL})),
    to_state   TEXT NOT NULL CHECK (to_state IN ({_STATES_SQL})),
    rule       TEXT NOT NULL,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transition_tickets (
    job_id     TEXT PRIMARY KEY,
    from_state TEXT NOT NULL,
    to_state   TEXT NOT NULL,
    history_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS safe_handles (
    job_id      TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
    handle_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    finding_id     TEXT PRIMARY KEY,
    job_id         TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    segment_id     TEXT NOT NULL,
    start_offset   INTEGER NOT NULL,
    end_offset     INTEGER NOT NULL,
    entity_type    TEXT NOT NULL,
    risk           TEXT NOT NULL,
    tier           TEXT NOT NULL,
    decision       TEXT NOT NULL,
    format_invalid INTEGER NOT NULL,
    value_hmac     TEXT NOT NULL,
    preview        TEXT NOT NULL,
    person_key     TEXT,
    token          TEXT,
    evidence_json  TEXT NOT NULL,
    locator_json   TEXT
);

CREATE TABLE IF NOT EXISTS review_log (
    review_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    finding_id    TEXT,
    reviewer_id   TEXT NOT NULL,
    action        TEXT NOT NULL,
    justification TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    job_id       TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
    report_json  TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    timings_json TEXT NOT NULL,
    versions_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    job_id     TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    format     TEXT NOT NULL CHECK (format IN ('json', 'md')),
    sha256     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, format)
);

CREATE TRIGGER IF NOT EXISTS jobs_insert_received
BEFORE INSERT ON jobs
WHEN NEW.state <> 'RECEIVED'
BEGIN
    SELECT RAISE(ABORT, 'GATE: jobs must be created in RECEIVED');
END;

CREATE TRIGGER IF NOT EXISTS jobs_state_guard
AFTER UPDATE OF state ON jobs
WHEN NEW.state IS NOT OLD.state
BEGIN
    SELECT RAISE(ABORT, 'GATE: transition not in whitelist')
    WHERE NOT EXISTS (
        SELECT 1 FROM allowed_transitions
        WHERE from_state = OLD.state AND to_state = NEW.state);
    SELECT RAISE(ABORT, 'GATE: state change without matching history in this transaction')
    WHERE NOT EXISTS (
        SELECT 1 FROM transition_tickets t
        JOIN state_history h ON h.history_id = t.history_id
        WHERE t.job_id = NEW.job_id
          AND t.from_state = OLD.state AND t.to_state = NEW.state
          AND h.job_id = NEW.job_id
          AND h.from_state = OLD.state AND h.to_state = NEW.state
          AND h.history_id = (SELECT MAX(history_id) FROM state_history
                              WHERE job_id = NEW.job_id));
    SELECT RAISE(ABORT, 'GATE: VALIDATED_SAFE requires a SafeHandle')
    WHERE NEW.state = 'VALIDATED_SAFE'
      AND NOT EXISTS (SELECT 1 FROM safe_handles WHERE job_id = NEW.job_id);
    DELETE FROM transition_tickets WHERE job_id = NEW.job_id;
END;

CREATE TRIGGER IF NOT EXISTS jobs_id_immutable
BEFORE UPDATE OF job_id, policy_hash ON jobs
WHEN NEW.job_id IS NOT OLD.job_id OR NEW.policy_hash IS NOT OLD.policy_hash
BEGIN
    SELECT RAISE(ABORT, 'GATE: job_id and policy_hash are immutable');
END;

CREATE TRIGGER IF NOT EXISTS history_no_update
BEFORE UPDATE ON state_history
BEGIN
    SELECT RAISE(ABORT, 'GATE: state_history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS history_no_delete
BEFORE DELETE ON state_history
WHEN EXISTS (SELECT 1 FROM jobs WHERE job_id = OLD.job_id)
BEGIN
    SELECT RAISE(ABORT, 'GATE: state_history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS handles_no_update
BEFORE UPDATE ON safe_handles
BEGIN
    SELECT RAISE(ABORT, 'GATE: SafeHandles are immutable');
END;

CREATE TRIGGER IF NOT EXISTS allowed_transitions_frozen_insert
BEFORE INSERT ON allowed_transitions
WHEN (SELECT COUNT(*) FROM allowed_transitions) >= {len(ALLOWED_TRANSITIONS)}
BEGIN
    SELECT RAISE(ABORT, 'GATE: whitelist is frozen');
END;

CREATE TRIGGER IF NOT EXISTS allowed_transitions_frozen_update
BEFORE UPDATE ON allowed_transitions
BEGIN
    SELECT RAISE(ABORT, 'GATE: whitelist is frozen');
END;

CREATE TRIGGER IF NOT EXISTS allowed_transitions_frozen_delete
BEFORE DELETE ON allowed_transitions
BEGIN
    SELECT RAISE(ABORT, 'GATE: whitelist is frozen');
END;
"""

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="microseconds")


class MetaStore:
    """Thin wrapper over one SQLite connection to ``meta.db``."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock = utc_now) -> None:
        self.conn = conn
        self.clock = clock

    @classmethod
    def open(cls, path: Path | str, clock: Clock = utc_now) -> MetaStore:
        conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        store = cls(conn, clock)
        store._migrate()
        return store

    def close(self) -> None:
        self.conn.close()

    def now(self) -> str:
        return iso(self.clock())

    def _migrate(self) -> None:
        # executescript manages its own transaction; run it outside ours.
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(findings)")}
        if "locator_json" not in cols:  # schema 1 -> 2
            self.conn.execute("ALTER TABLE findings ADD COLUMN locator_json TEXT")
        with self.transaction():
            if self.conn.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0] == 0:
                self.conn.execute("INSERT INTO schema_info VALUES (?)", (SCHEMA_VERSION,))
            have = {
                (r["from_state"], r["to_state"])
                for r in self.conn.execute("SELECT from_state, to_state FROM allowed_transitions")
            }
            for src, dst in sorted(ALLOWED_TRANSITIONS):
                if (src.value, dst.value) not in have:
                    self.conn.execute(
                        "INSERT INTO allowed_transitions VALUES (?, ?)", (src.value, dst.value)
                    )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE`` ... ``COMMIT``; rolls back on any exception."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ------------------------------------------------------------------ batches/jobs

    def create_batch(self, batch_id: str, policy_name: str, policy_hash: str) -> None:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO batches VALUES (?, ?, ?, ?)",
                (batch_id, policy_name, policy_hash, self.now()),
            )

    def create_job(
        self,
        job_id: str,
        batch_id: str,
        filename: str,
        policy_hash: str,
        *,
        fmt: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
    ) -> None:
        now = self.now()
        with self.transaction():
            self.conn.execute(
                "INSERT INTO jobs (job_id, batch_id, filename, fmt, sha256, size_bytes,"
                " policy_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, batch_id, filename, fmt, sha256, size_bytes, policy_hash, now, now),
            )

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row

    def job_state(self, job_id: str) -> JobState | None:
        row = self.get_job(job_id)
        return JobState(row["state"]) if row else None

    def history(self, job_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM state_history WHERE job_id = ? ORDER BY history_id", (job_id,)
            )
        )

    def handle_json(self, job_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT handle_json FROM safe_handles WHERE job_id = ?", (job_id,)
        ).fetchone()
        return str(row[0]) if row else None

    def delete_batch(self, batch_id: str) -> None:
        """TR-SEC-06: jobs, findings, handles, reports cascade; then their history."""
        with self.transaction():
            job_ids = [
                r[0]
                for r in self.conn.execute(
                    "SELECT job_id FROM jobs WHERE batch_id = ?", (batch_id,)
                )
            ]
            self.conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
            self.conn.executemany(
                "DELETE FROM state_history WHERE job_id = ?", [(j,) for j in job_ids]
            )
            self.conn.executemany(
                "DELETE FROM transition_tickets WHERE job_id = ?", [(j,) for j in job_ids]
            )

    # ------------------------------------------------------------------ findings

    def add_findings(self, job_id: str, findings: Iterable[Finding]) -> int:
        rows = [_finding_row(job_id, f) for f in findings]
        with self.transaction():
            self.conn.executemany(
                "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
        return len(rows)

    def replace_findings(self, job_id: str, findings: Iterable[Finding]) -> int:
        """Findings of the latest run (a review re-run replaces the previous set)."""
        rows = [_finding_row(job_id, f) for f in findings]
        with self.transaction():
            self.conn.execute("DELETE FROM findings WHERE job_id = ?", (job_id,))
            self.conn.executemany(
                "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
        return len(rows)

    def save_run(
        self,
        job_id: str,
        report: Any,
        actions: Iterable[Any],
        timings: dict[str, float],
        versions: dict[str, str],
    ) -> None:
        """Verification report, action summary, timings, stage versions: content-free."""
        acts = [
            {
                "finding_ids": a.finding_ids,
                "method": a.method,
                "applied": a.applied,
                "error_code": a.error_code,
                "part": a.locator.part,
                "page": a.locator.page,
                "slide": a.locator.slide,
            }
            for a in actions
        ]
        with self.transaction():
            self.conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    report.model_dump_json(),
                    json.dumps(acts, sort_keys=True),
                    json.dumps(timings, sort_keys=True),
                    json.dumps(versions, sort_keys=True),
                    self.now(),
                ),
            )

    def run(self, job_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM runs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row

    def findings(self, job_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM findings WHERE job_id = ? ORDER BY finding_id", (job_id,)
            )
        )


def _finding_row(job_id: str, finding: Finding) -> tuple[Any, ...]:
    # model_dump excludes the raw value field; nothing else carries content.
    d = finding.model_dump(mode="json")
    return (
        d["finding_id"],
        job_id,
        d["segment_id"],
        d["start"],
        d["end"],
        d["entity_type"],
        d["risk"],
        d["tier"],
        d["decision"],
        int(d["format_invalid"]),
        d["value_hmac"],
        d["preview"],
        d["person_key"],
        d["token"],
        json.dumps(d["evidence"], sort_keys=True),
        json.dumps(d["locator"], sort_keys=True) if d.get("locator") else None,
    )
