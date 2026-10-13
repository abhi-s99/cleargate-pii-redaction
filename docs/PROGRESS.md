# Progress (hand-off file)

Resume by reading `CLAUDE.md`, then this file, then the latest phase report.

| Field | Value |
|---|---|
| Current phase | Phase 0 (bootstrap): **complete**, waiting for "continue" |
| Branch | `main` (no phase branches, ADR-18) |
| Last green commit | tagged `v0.0.0` (see `git log --oneline -1 v0.0.0`) |
| Latest report | [phases/PHASE-00-bootstrap.md](phases/PHASE-00-bootstrap.md) |
| Samples | present in `Data/` (git-ignored, ADR-15) |

## In progress

Nothing. Phase 0 is closed.

## Next three steps (Phase 1: gate core)

1. SQLite schema for `meta.db` (WAL): `batches`, `jobs` with the state `CHECK`
   constraint, append-only `state_history`, `findings` (no raw values), `review_log`,
   `reports`, plus the TR-GT-02 trigger.
2. `gate/machine.py` `transition()` with the TR-GT-01 whitelist; `gate/rules.py` G0..G7 as
   pure functions over a `GateInput`; `gate/handle.py` SafeHandle mint/verify (TR-GT-03).
3. Tests: every illegal transition raises; direct SQL `UPDATE ... VALIDATED_SAFE` rejected;
   tampered handle refused (each field, and the sanitized file changed on disk);
   table-driven G0..G7 including ordering; hypothesis search finds no path to SAFE.

## Open questions

- None blocking. PRD section 13 defaults apply (corporate emails are PII, role titles kept,
  external contacts in scope, HQ address kept, illegible screenshots mask + review,
  tokens stable within a batch).
- To decide in Phase 2: how TR-SEC-04 (`0700`) and TR-SEC-07 (`RLIMIT_AS`) are met on
  Windows (ADR-16).
- To decide in Phase 3: TR-EX-40 wants an error code per uninspected part, but the TRD 4
  `Coverage.uninspected` is a plain `list[Locator]`.
- To handle in Phase 4/5: Presidio depends on `tldextract`, which can download the public
  suffix list at runtime; it must be forced offline (TR-SEC-01).
