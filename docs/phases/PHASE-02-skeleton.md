# Phase 02: Walking skeleton
Tag: v0.2.0 · Date: 13 Oct 2026 · Branch: `main` (ADR-18)

## What was built

A thin end-to-end slice through the real gate: validate, store, extract, detect, redact,
verify, decide. The stages are stubs, so the skeleton proves fail-closed behaviour from day
one: every valid file ends `BLOCKED` by G3 because nothing was inspected.

- `ingest/validator.py`: content-based type detection with extension agreement; size,
  page, image and zip-bomb limits; encrypted PDF, encrypted OOXML (OLE `EncryptedPackage`)
  and encrypted zip entries; macro-enabled content types, `vbaProject.bin` and macro
  extensions; legacy OLE files; XLSX and templates rejected; `[Content_Types].xml` parsed
  with DTDs and entities refused (XXE, billion laughs).
- `ingest/storage.py`: owner-only job directories (POSIX `0700`, Windows ACL, ADR-25), upload
  written once with `O_EXCL` as `original.<ext>`, sanitised display names.
- `pipeline.py`: stage protocols, `JobContext` (timings, progress), stub stages, batch and
  job runner. Every exception becomes a G0 decision; a crash in the gate itself forces
  `FAILED`.
- `cli.py`: `cleargate process | status | extract --dump` (console script `cleargate`).
- Gate fix found while planning this phase (ADR-24): a verification check that did not run
  now counts as failed. Without this, real extraction plus a partial verifier would have
  been able to reach `VALIDATED_SAFE`.

Requirements: TR-IN-01..04, TR-IN-06, FR-01, TR-SEC-04 (PASS); TR-IN-05, TR-SEC-07 (PARTIAL);
G0 and G3 extended with pipeline-level tests.

## Files added / changed

- `cleargate/ingest/validator.py`, `cleargate/ingest/storage.py`, `cleargate/pipeline.py`,
  `cleargate/cli.py` (new or implemented).
- `cleargate/core/models.py`: `PartIssue`, `Coverage.issues`, `Coverage.register`,
  `VerificationReport.checks_run`, `ALL_CHECKS`.
- `cleargate/gate/rules.py`: unrun checks map to G0/G3/G6 (ADR-24).
- `cleargate/core/config.py`: `load_env_file` (moved from the doctor).
- `pyproject.toml`: `cleargate` console script; mypy leniency made explicit outside the
  strict packages.
- Tests: `tests/filegen.py` (builders for valid and hostile files),
  `tests/unit/test_validator.py`, `tests/unit/test_storage.py`,
  `tests/integration/test_pipeline.py`, `tests/integration/test_cli.py`,
  `tests/integration/conftest.py`; gate tests extended for `checks_run`.

## How to verify (copy-paste)

```bash
make check
cleargate process Data/*.pptx Data/*.docx Data/*.pdf --data-dir out/p2      # real samples
cleargate status <batch_id printed above> --data-dir out/p2
cleargate process tests/... any invalid file ... --data-dir out/p2
```

Expected: `make check` exits 0; the three samples end `BLOCKED G3` with
`UNINSPECTED_PARTS=n`; `status` shows `RECEIVED -> PROCESSING -> BLOCKED` with rule and
reason per step.

## Actual results

**Static checks:** ruff All checks passed; ruff format 107 files already formatted; mypy
Success: no issues found in 62 source files.

**Tests:** `make check`: `380 passed, 7 deselected in 11.35s`; `make test-all`:
`387 passed in 10.40s` (7 samples-marked tests ran against `Data/`). Phase 0-1 tests green.

**Exit criteria**

| Criterion | Evidence | Result |
|---|---|---|
| Any valid file ends `BLOCKED` via G3 | `test_pipeline.py::test_valid_file_ends_blocked_by_g3` (docx, pptx, pdf, png); sample run below | PASS |
| Invalid inputs end `FAILED` with specific codes: wrong extension, encrypted PDF, `.docm`, zip bomb, oversize | `test_pipeline.py::test_invalid_input_ends_failed_with_specific_code` (plus legacy `.doc`); history is `RECEIVED -> FAILED` only, rule `ingest`; 33 validator unit tests cover the rest | PASS |
| A crash injected into any stage ends `FAILED` | `test_crash_in_any_stage_ends_failed` (extract, detect, redact, verify), `test_typed_stage_error_keeps_its_code`, `test_crash_in_gate_decision_ends_failed`; the exception text (an invented name and SSN) never reaches the database | PASS |

**Cross-checks**

- *Fault injection:* each Architecture 6 failure path that exists so far (validator reject,
  stage crash, gate crash, missing keys) ends non-SAFE.
- *Fail-open probe:* an extractor that marks everything inspected plus the partial
  verifier ends `BLOCKED G3 V2_NOT_RUN,V3_NOT_RUN,V5_NOT_RUN`
  (`test_partial_verifier_cannot_produce_safe_even_with_full_coverage`). Only a test double
  that declares all six checks clean reaches SAFE, and its handle verifies against the
  sanitized output (`test_safe_path_mints_a_handle_over_the_sanitized_output`).
- *Hostile input:* XXE and billion-laughs `[Content_Types].xml`, zip bomb by ratio and by
  total size, encrypted zip entries, broken zip, truncated PNG, corrupt PDF: all `FAILED`.
- *ACL check:* on this Windows machine `icacls` on a job dir lists exactly one entry, the
  current user with full control.

**Sample smoke** (`cleargate process` on the three real files, stub stages):

| File | State | Rule | Reason | Time |
|---|---|---|---|---|
| Org pack PPTX | BLOCKED | G3 | `UNINSPECTED_PARTS=64` + V2, V3, V5 not run | 0.03 s |
| TPRM DOCX | BLOCKED | G3 | `UNINSPECTED_PARTS=98` + V2, V3, V5 not run | 0.05 s |
| Risk policy PDF | BLOCKED | G3 | `UNINSPECTED_PARTS=35` + V2, V3, V5 not run | 0.43 s |

(Parts here are zip entries for OOXML and pages for the PDF; Phase 3 replaces the stub.)

## Deviations from spec

- ADR-23: `Coverage.issues` added; `ingest/storage.py` and `cli.py` added to the TRD 3 layout.
- ADR-24: unrun verification checks count as failed (gate change).
- ADR-25: Windows owner-only ACL instead of `0700`; display filename kept and sanitised.

## Known gaps / risks carried forward

- `RLIMIT_AS` worker memory limit: POSIX only, Phase 11 Docker.
- The encrypted-OOXML check looks for the `EncryptedPackage` stream name in the first 4 MB
  of an OLE file, not a full CFB parse. Legacy OLE files are rejected either way, so the
  only effect is which code is reported.
- Display filenames can contain personal names (ADR-25).
- `cleargate process` exits 0 even when jobs are not SAFE; the per-job state is the result.

## Next phase entry criteria

- `make check` green at `v0.2.0`. Phase 3 replaces `RegisterOnlyExtractor` with the real
  PDF/DOCX/PPTX/image extractors and adds the synthetic planted-PII fixtures.
