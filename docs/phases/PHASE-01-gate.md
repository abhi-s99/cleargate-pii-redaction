# Phase 01: Gate core
Tag: v0.1.0 · Date: 13 Oct 2026 · Branch: `main` (ADR-18)

## What was built

The privacy gate, built before any pipeline stage so that every later stage has to flow
through it:

- `meta.db` (SQLite, WAL) with `batches`, `jobs` (state `CHECK` constraint),
  append-only `state_history`, `transition_tickets`, `safe_handles`, `findings` (no raw
  values), `review_log`, `reports`, and database triggers that reject any state change the
  gate did not make (ADR-20).
- `gate/machine.py`: the TR-GT-01 whitelist; `transition()` for every edge except into
  SAFE; `decide()` as the only way into `VALIDATED_SAFE` (ADR-22).
- `gate/rules.py`: G0..G7 as pure functions over a `GateInput`, first match wins, with
  every reason reported (ADR-21).
- `gate/handle.py`: SafeHandle mint and verify (HMAC-SHA256 over canonical JSON, content
  re-hash) plus the TR-GT-04 store checks the Phase 8 handoff will call.
- `scripts/gate_demo.py` (`make gate-demo`): a readable end-to-end walkthrough for manual
  checking.

Requirements covered: TR-GT-01, TR-GT-02, TR-GT-03, G0..G7 (PASS); TR-GT-04, FR-11, FR-16,
TR-SEC-02, TR-SEC-06, TR-RD-40 (PARTIAL, remaining parts scheduled).

## Files added / changed

- `cleargate/core/db.py` (new): `MetaStore`, schema, triggers, migrations, findings rows.
- `cleargate/core/models.py`: `VerificationReport` (counts for V1..V6, the gate's input).
- `cleargate/core/errors.py`: `JOB_NOT_FOUND`.
- `cleargate/gate/machine.py`, `rules.py`, `handle.py`: implemented (were placeholders).
- `scripts/gate_demo.py`, `Makefile` (`gate-demo` target), `pyproject.toml` (S608
  per-file ignore for the constant-built schema SQL).
- Tests: `tests/unit/gate_support.py` (helpers), `test_db.py` (29), `test_gate_machine.py`
  (63), `test_gate_rules.py` (48), `test_gate_handle.py` (17), `test_gate_properties.py` (4,
  one of them a stateful machine).
- Docs: `DECISIONS.md` (ADR-20..22), `VERIFICATION.md`, this report, README, CHANGELOG,
  PROGRESS.

## How to verify (copy-paste)

```bash
make check                      # lint + mypy strict on gate + 285 tests + matrix + style
make gate-demo                  # 16 expectations, printed one per line
python scripts/gate_demo.py --keep out/gate-demo     # keep meta.db to inspect by hand
.venv/Scripts/python -m pytest tests/unit/test_gate_properties.py -v   # hypothesis runs
```

Expected: `make check` exits 0 with `285 passed, 4 deselected`; the demo ends with
`gate_demo: 16/16 expectations met`.

## Actual results

**Static checks** (`make lint`): `ruff check` All checks passed; `ruff format --check` 98
files already formatted; `mypy` Success: no issues found in 60 source files (strict on
`cleargate.core.*` and `cleargate.gate.*`).

**Tests:** `make check` gives `285 passed, 4 deselected in 7.74s`; `make test-all` gives
`289 passed in 7.21s`. 0 xfailed, 0 skipped. Phase 0 tests unchanged and green.

**Exit criteria**

| Criterion (brief Phase 1) | Evidence | Result |
|---|---|---|
| Every illegal transition raises | `test_gate_machine.py::test_illegal_transition_raises_and_changes_nothing`: all 28 non-whitelisted pairs of the 6x6 state grid raise `IllegalTransition`, leave state, history and tickets unchanged; the 8 allowed pairs succeed | PASS |
| Direct SQL `UPDATE jobs SET state='VALIDATED_SAFE'` rejected by the trigger | `test_db.py::test_direct_update_to_safe_from_processing_is_rejected` and `test_direct_update_from_received_is_rejected` (all 5 targets); also forged history without ticket, stale ticket, forged ticket without handle, non-whitelisted edge with ticket, unknown state (CHECK) | PASS |
| Tampered handle refused (any field, or sanitized file changed) | `test_gate_handle.py::test_tampering_any_field_is_refused` (all 6 fields), `test_sanitized_file_changed_on_disk_is_refused`, `test_single_appended_byte_is_refused`, `test_sanitized_file_deleted_is_refused`, wrong key, not-safe job, other policy, re-minted handle, unknown job | PASS |
| G0..G7 table-driven incl. rule ordering | `test_gate_rules.py`: 17 single-trigger cases, 6 SAFE boundary cases, all 21 rule pairs (first wins and both reported), all rules at once gives G0 | PASS |
| Hypothesis finds no path to SAFE from illegal states | `test_gate_properties.py::test_gate_state_machine`: 150 random sequences of up to 25 steps mixing legal moves, illegal moves, raw SQL updates and `decide()` with random inputs, against a real `meta.db`. Invariants: DB equals model; history is an unbroken chain of whitelisted edges; SAFE entered only from PROCESSING by G7; SAFE implies an issued handle that verifies | PASS |

**Cross-checks run**

- *Differential:* the transition whitelist exists twice, in Python (`ALLOWED_TRANSITIONS`)
  and in the database (`allowed_transitions`). `test_db.py::test_whitelist_table_matches_trd`
  asserts they are equal; the stateful test exercises both paths.
- *Property tests:* SAFE iff no rule fires, and the verdict is the first firing rule
  (`test_safe_iff_no_rule_fires`); adding any of 15 faults never relaxes the outcome
  (`test_adding_a_fault_never_relaxes_the_outcome`); reasons are identifier-like.
- *Fault injection* (Architecture 6, gate side): verification missing gives FAILED;
  sanitized file missing at mint time gives FAILED `HANDLE_MINT_FAILED`; invalid gate key
  at mint time gives FAILED; vault unavailable gives FAILED (rule test); unapplied action
  gives BLOCKED.
- *Mutation check* (bugs planted one at a time, then restored; script kept outside the
  repo):

  | Planted bug | Result |
  |---|---|
  | G3 rule always returns nothing | 12 tests fail |
  | Database whitelist check removed | 1 test fails (the Python whitelist still guards; the raw-SQL test catches it) |
  | Content re-hash skipped in `verify_handle` | 2 tests fail |
  | Public `transition()` stops refusing SAFE | 0 fail: equivalent mutant, because `_apply` still requires a gate-minted handle, so SAFE stays unreachable (ADR-22, defence in depth) |

- *No raw values in meta.db:* `test_db.py::test_findings_are_stored_without_raw_values`
  checkpoints the WAL and searches the database bytes for an invented raw value: absent.

**Manual walkthrough** (`make gate-demo`): `gate_demo: 16/16 expectations met`. The
direct SQL update to SAFE is refused with `GATE: state change without matching history in
this transaction`; the four demo jobs end FAILED/G0, BLOCKED/G3, REVIEW_REQUIRED/G6 and
VALIDATED_SAFE/G7; only the G7 job holds a handle; an edited handle, a different key and
an edited sanitized file are each refused.

**Sample smoke:** not applicable (no extraction yet); `make smoke` unchanged from Phase 0.

## Deviations from spec

- ADR-20: `core/db.py` is a new module (not in TRD 3); "same transaction" in TR-GT-02 is
  realised with a single-use ticket consumed by the trigger.
- ADR-21: gate interpretations (missing verification and handle-mint failure are G0;
  masked regions depend on `unreadable_policy`; unmeasured SRS is G6).
- ADR-22: two entry points (`transition`, `decide`) over one internal `_apply` instead of
  ADR-09's single `transition`; only `decide` can reach SAFE.

## Known gaps / risks carried forward

- SQLite triggers are not a security boundary against someone with raw write access to
  `meta.db`; the SafeHandle HMAC is (tested). Documented in ADR-20 and for TR-SEC-09.
- `jobs.filename` stores the uploaded file's display name, which could itself contain a
  person's name. Phase 2 stores files as `original.<ext>`; whether the display name is
  kept, hashed or masked is decided there.
- `review_log.justification` is reviewer free text; TR-RV-04 handling is Phase 8.
- G1, G2, G4, G5 and V-checks are only as good as their inputs, which arrive in Phases 6-7.
- `transition()` raises for an unknown job before checking the target; harmless, noted.

## Next phase entry criteria

- `make check` green at `v0.1.0`.
- Phase 2 (walking skeleton): ingest validator (TR-IN-01..06), pipeline orchestrator with
  stub stages flowing through `decide()`, Typer CLI; any valid file ends `BLOCKED` via G3;
  invalid inputs end `FAILED` with specific codes; an injected crash in any stage ends
  `FAILED`.
