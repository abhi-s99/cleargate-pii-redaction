# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow the
phase tags (`v0.NN.0`).

## [Unreleased]

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
