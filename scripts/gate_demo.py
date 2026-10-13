"""Phase 1 walkthrough: python scripts/gate_demo.py [--keep DIR]

Drives the real gate against a throwaway meta.db and prints one line per
expectation (PASS/FAIL). Uses invented data only. With --keep, the database and
sanitized file are left in DIR so you can inspect them, e.g.:

    python -c "import sqlite3; c=sqlite3.connect('DIR/meta.db');
               print(c.execute('select * from state_history').fetchall())"
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import SecretStr

from cleargate.core.db import MetaStore
from cleargate.core.errors import ClearGateError
from cleargate.core.models import Coverage, Locator, VerificationReport
from cleargate.core.states import JobState
from cleargate.gate.handle import SafeHandle, verify_against_store
from cleargate.gate.machine import decide, transition
from cleargate.gate.rules import GateInput

RESULTS: list[bool] = []


def expect(label: str, fn: Callable[[], object], *, raises: bool) -> None:
    try:
        fn()
        ok, got = not raises, "accepted"
    except (ClearGateError, sqlite3.IntegrityError) as exc:
        ok, got = raises, f"refused ({type(exc).__name__}: {exc})"
    RESULTS.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}\n        -> {got}")


def check(label: str, cond: bool, detail: str) -> None:
    RESULTS.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {label}\n        -> {detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", type=Path, help="directory to keep the demo files in")
    args = parser.parse_args(argv)
    work = args.keep or Path(tempfile.mkdtemp(prefix="cleargate-gate-demo-"))
    work.mkdir(parents=True, exist_ok=True)
    key = SecretStr(secrets.token_urlsafe(32))
    store = MetaStore.open(work / "meta.db")
    sanitized = work / "sanitized.txt"
    sanitized.write_text("[PERSON_1] approved the vendor review.\n", encoding="utf-8")
    store.create_batch("demo-batch", "cadence-default", "a" * 64)
    clean = VerificationReport(job_id="", reopen_ok=True, srs=0.97, crs=0.95)

    def job(job_id: str) -> str:
        store.create_job(job_id, "demo-batch", "original.docx", "a" * 64)
        return job_id

    print(f"Working in {work}\n\n== 1. Transition whitelist (TR-GT-01)")
    a = job("job-a")
    expect(
        "RECEIVED -> BLOCKED is illegal",
        lambda: transition(store, a, JobState.BLOCKED, rule="G1", reason="x"),
        raises=True,
    )
    expect(
        "RECEIVED -> PROCESSING is legal",
        lambda: transition(store, a, JobState.PROCESSING, rule="ingest", reason="validated"),
        raises=False,
    )
    expect(
        "public transition() can never enter VALIDATED_SAFE",
        lambda: transition(store, a, JobState.VALIDATED_SAFE, rule="G7", reason="ok"),
        raises=True,
    )

    print("\n== 2. Database guards (TR-GT-02)")
    expect(
        "direct SQL UPDATE ... SET state='VALIDATED_SAFE'",
        lambda: store.conn.execute("UPDATE jobs SET state='VALIDATED_SAFE' WHERE job_id='job-a'"),
        raises=True,
    )
    expect(
        "direct SQL UPDATE on a legal edge (PROCESSING -> BLOCKED)",
        lambda: store.conn.execute("UPDATE jobs SET state='BLOCKED' WHERE job_id='job-a'"),
        raises=True,
    )
    expect(
        "editing state_history",
        lambda: store.conn.execute("UPDATE state_history SET reason='edited'"),
        raises=True,
    )
    expect(
        "unknown state value (CHECK constraint)",
        lambda: store.conn.execute("UPDATE jobs SET state='APPROVED' WHERE job_id='job-a'"),
        raises=True,
    )

    print("\n== 3. Rules G0..G7 decide the outcome (TRD 8.2)")
    cases = [
        ("job-g0", GateInput(job_id="job-g0", verification=None), JobState.FAILED),
        (
            "job-g3",
            GateInput(
                job_id="job-g3",
                verification=clean.model_copy(update={"job_id": "job-g3"}),
                coverage=Coverage(uninspected=[Locator(part="page", page=9)]),
            ),
            JobState.BLOCKED,
        ),
        (
            "job-g6",
            GateInput(
                job_id="job-g6",
                verification=clean.model_copy(update={"job_id": "job-g6"}),
                masked_regions=1,
            ),
            JobState.REVIEW_REQUIRED,
        ),
        (
            "job-g7",
            GateInput(job_id="job-g7", verification=clean.model_copy(update={"job_id": "job-g7"})),
            JobState.VALIDATED_SAFE,
        ),
    ]
    for jid, gi, want in cases:
        transition(store, job(jid), JobState.PROCESSING, rule="ingest", reason="validated")
        verdict = decide(store, gi, gate_key=key, sanitized_path=sanitized)
        check(
            f"{jid}: expected {want.value}",
            verdict.state is want,
            f"{verdict.state.value} by {verdict.rule} ({verdict.reason})",
        )
    check(
        "only job-g7 holds a SafeHandle",
        [j for j, *_ in cases if store.handle_json(j)] == ["job-g7"],
        f"handles for {[j for j, *_ in cases if store.handle_json(j)]}",
    )

    print("\n== 4. SafeHandle (TR-GT-03/04)")
    stored = store.handle_json("job-g7")
    assert stored is not None
    handle = SafeHandle.from_json(stored)
    expect(
        "issued handle verifies",
        lambda: verify_against_store(store, handle, key, sanitized),
        raises=False,
    )
    forged = handle.model_copy(update={"policy_hash": "b" * 64})
    expect(
        "handle with an edited field",
        lambda: verify_against_store(store, forged, key, sanitized),
        raises=True,
    )
    expect(
        "handle checked with a different key",
        lambda: verify_against_store(
            store, handle, SecretStr(secrets.token_urlsafe(32)), sanitized
        ),
        raises=True,
    )
    sanitized.write_text("[PERSON_1] approved the vendor review. extra\n", encoding="utf-8")
    expect(
        "sanitized file changed after validation",
        lambda: verify_against_store(store, handle, key, sanitized),
        raises=True,
    )

    print("\n== 5. Audit trail for job-g7 (FR-16)")
    for row in store.history("job-g7"):
        print(
            f"        {row['created_at']}  {row['from_state']:>15} -> {row['to_state']:<15}"
            f" rule={row['rule']} reason={row['reason']}"
        )
    store.close()
    if args.keep is None:
        shutil.rmtree(work, ignore_errors=True)
    failed = RESULTS.count(False)
    print(f"\ngate_demo: {len(RESULTS) - failed}/{len(RESULTS)} expectations met")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
