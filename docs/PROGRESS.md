# Progress (hand-off file)

Resume by reading `CLAUDE.md`, then this file, then the latest phase report.

| Field | Value |
|---|---|
| Current phase | Phase 1 (gate core): **complete**, waiting for user feedback / "continue" |
| Branch | `main` (no phase branches, ADR-18) |
| Last green commit | tagged `v0.1.0` (see `git log --oneline -1 v0.1.0`) |
| Latest report | [phases/PHASE-01-gate.md](phases/PHASE-01-gate.md) |
| Samples | present in `Data/` (git-ignored, ADR-15) |

## In progress

Nothing. Phase 1 is closed. The user reviews it with `make check` and `make gate-demo`
and may send feedback before Phase 2.

## Next three steps (Phase 2: walking skeleton)

1. `ingest/validator.py` (TR-IN-01..06): magic bytes, OOXML content types, extension
   agreement, size/page/zip-bomb/encryption/macro checks, safe storage as `original.<ext>`
   (TR-SEC-04, Windows treatment per ADR-16).
2. `pipeline.py` with `JobContext` and stub stages (extractor registers parts but inspects
   none, no-op detector, identity writer, verifier reporting coverage) feeding `decide()`;
   any exception becomes G0.
3. Typer CLI `cleargate process|status|extract`; tests: valid file ends BLOCKED by G3,
   each invalid input ends FAILED with its code, a crash in each stage ends FAILED.

## Open questions

- None blocking. PRD section 13 defaults apply.
- Phase 2: keep, hash or mask the uploaded display filename in `jobs.filename`.
- Phase 2: TR-SEC-04 (`0700`) and TR-SEC-07 (`RLIMIT_AS`) on Windows (ADR-16).
- Phase 3: TR-EX-40 error code per uninspected part vs `Coverage.uninspected: list[Locator]`.
- Phase 4/5: force `tldextract` offline (TR-SEC-01).
