# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow the
phase tags (`v0.NN.0`).

## [Unreleased]
### Fixed
- The synthetic `planted.docx` did not open in Word (its text box lacked the anchor and
  shape children Word requires); redacted outputs inherited the problem. Regenerated, and
  an opt-in test now opens fixtures and redacted outputs in Word and PowerPoint.
- The UI took the user's role from the Connect page selection; it now asks the server
  (`GET /whoami`, ADR-35).

### Added
- `REFERENCE_GAP_ANALYSIS.md`: Smart-Redact (as documented) vs ClearGate, 15 areas with
  test evidence.

## [0.11.0] - 2026-10-14: Phase 11, hardening, Docker, demo
### Added
- `RLIMIT_AS` for OCR workers (`CLEARGATE_WORKER_MEM_MB`, default 6144) and a spawned
  OCR pool (ADR-34); Dockerfile and `docker-compose.yml`; `docs/DEMO.md`; performance
  tests for TR-PF-01 and TR-PF-04.
### Fixed
- README quickstart named Streamlit and commands that do not exist; a policy option
  that does not exist was listed as available.

## [0.10.0] - 2026-10-14: Phase 10, evaluation harness
### Added
- `make eval`: metrics of TRD 9 with Wilson intervals, synthetic report `eval/report.md`,
  `--samples` mode for annotated gold, threshold calibration with k-fold (ADR-33),
  draft gold files for annotators.

## [0.9.0] - 2026-10-14: Phase 9, React web UI integrated
### Added
- The React UI in `cleargate-ui/` talks to the real API (ADR-32); `make ui`, `make run`,
  `make e2e`; Edge-driven browser smoke test.

## [0.8.0] - 2026-10-14: Phase 8, API
### Added
- FastAPI service: batches, jobs, findings, value-grouped review with re-verification,
  reports, SafeHandle-checked downloads, MockAgent handoff, batch delete, TTL sweeper
  (ADR-31); `cleargate serve`.

## [0.7.0] - 2026-10-14: Phase 7, independent verification
### Added
- V1..V6 on a separate re-extraction path, repair pass for raster hits (ADR-30).

## [0.6.0] - 2026-10-14: Phase 6, redaction
### Added
- Tokens and Fernet vault, DOCX/PPTX/PDF/image writers, sanitized text, batch pipeline with
  encrypted job state (ADR-29).

## [0.5.0] - 2026-10-14: Phase 5, context-aware detection

### Added
- Pre-split and normalisation with offset maps (TR-DT-01/02); Presidio + spaCy
  `en_core_web_lg` NER loaded once per process (TR-DT-13, TR-PF-05).
- Person context rules, batch person registry with variants, exact/fuzzy/surname
  propagation and opaque person keys (TR-DT-14/15); allowlist that suppresses only NER-only
  terms (FR-06); region findings for faces and unreadable areas (TR-DT-16).
- `DetectionEngine.detect_batch` with `default` and `verify` profiles; value propagation of
  every redacted value across the batch (ADR-28).
- `Finding.locator` and `findings.locator_json` (schema 2, migrated in place).

## [0.4.0] - 2026-10-14: Phase 4, deterministic detection

### Added
- L1 recognizers with validators: email, phone (`phonenumbers`), SSN (Presidio rules, 9xx
  allowed), PAN with holder type (business PANs discarded), PESEL (checksum, masked form),
  payment card (Luhn, IIN), passport (context), policy employee IDs (TR-DT-10).
- L2 label-anchored capture inline, by column header and by row label, with OCR-confusion
  repair on OCR segments (TR-DT-11, TR-DT-12); partial financial, SSN last four and home
  address captures (TR-DT-14 subset, ADR-28).
- `detect/merge.py`: overlap resolution, evidence retention, tiers and decisions (TRD 6.3),
  with hypothesis properties.

## [0.3.0] - 2026-10-14: Phase 3, extraction and synthetic fixtures

### Added
- PDF, DOCX, PPTX and image extractors (TRD 5) with OCR in a process pool, encrypted and
  versioned OCR cache, YuNet + Haar face detection, unreadable-block and non-text-region
  rules, metadata, and a generic part sweep so no package part goes unaccounted for
  (ADR-26, ADR-27).
- Deterministic planted-PII fixtures (`tests/fixtures/make_fixtures.py`, 63 items) and a
  manifest matcher shared by later phases.
- `make smoke` runs the full pipeline on the real samples (counts only).

### Fixed
- `.rels` parts were classified as embedded objects; list styles were not detected as lists.

## [0.2.0] - 2026-10-13: Phase 2, walking skeleton

### Added
- `ingest/validator.py`: content-based type detection, extension agreement, size/page/
  image/zip-bomb limits, encryption and macro detection, safe XML parsing (TR-IN-01..06).
- `ingest/storage.py`: owner-only job directories, `O_EXCL` upload storage, sanitised
  display names (TR-SEC-04, ADR-25).
- `pipeline.py`: stage protocols, `JobContext`, stub stages, fail-closed orchestration.
- `cli.py`: `cleargate process | status | extract --dump`.
- `Coverage.issues` with a code per uninspected part (ADR-23).

### Fixed
- Gate: a verification check that did not run now counts as failed (ADR-24).

## [0.1.0] - 2026-10-13: Phase 1, gate core

### Added
- `core/db.py`: `meta.db` (SQLite, WAL) with batches, jobs, append-only state history,
  single-use transition tickets, SafeHandles, findings without raw values, review log and
  reports; triggers reject direct state updates, non-whitelisted edges, SAFE without a
  handle, history edits and whitelist edits (ADR-20).
- `gate/machine.py`: TR-GT-01 whitelist, `transition()` (never into SAFE) and `decide()`,
  the only route to `VALIDATED_SAFE` (ADR-22).
- `gate/rules.py`: rules G0..G7 as pure functions with ordered evaluation (ADR-21).
- `gate/handle.py`: SafeHandle mint/verify and the TR-GT-04 store checks.
- `core/models.py`: `VerificationReport`.
- `scripts/gate_demo.py` and `make gate-demo` for manual verification.
- 161 gate tests including a hypothesis state machine over a real database.

## [0.0.0] - 2026-10-13: Phase 0, bootstrap

### Added
- `pyproject.toml` with exact dependency pins (Python >= 3.12; developed on 3.13.15) and
  `[dev]` extras; ruff, mypy (strict on `core`, `gate`, `verify`) and pytest configuration
  with sockets disabled for every test.
- Package skeleton exactly as TRD section 3; placeholder modules name their requirement
  IDs and target phase.
- `core/models.py`: all TRD section 4 models; raw-content fields are excluded from every
  serialisation and from `repr`.
- `core/config.py`: strict policy loader for `config/policy.default.yaml` (rejects unknown
  keys, duplicate YAML keys, bad regexes, out-of-range thresholds, unapproved LLM use) and
  `policy_hash` over canonical JSON; environment settings with secret types.
- `core/errors.py`: typed errors with fixed, content-free message templates.
- `core/logging.py`: JSON logging with `PiiSafeFilter` (drops records containing active
  needles, strips exception arguments and tracebacks).
- `scripts/doctor.py`, `scripts/genkeys.py`, `scripts/check_matrix.py`,
  `scripts/check_style.py`, `scripts/smoke.py`; `Makefile`; pre-commit hooks (ruff,
  detect-secrets, no-emoji/no-em-dash rule, confidential-file blocker).
- Process docs: `CLAUDE.md`, `docs/DECISIONS.md` (ADR-14..19), `docs/PROGRESS.md`,
  `docs/VERIFICATION.md`, `docs/phases/PHASE-00-bootstrap.md`.

### Changed
- Design documents moved to `docs/` (README stays at the root, links fixed), sample-derived
  values replaced by invented placeholders (ADR-14), emoji and em dashes removed (ADR-18).
