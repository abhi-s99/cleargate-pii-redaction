# Phase 00: Bootstrap
Tag: v0.0.0 · Date: 13 Oct 2026 · Branch: `main` (ADR-18)

## What was built

The repository foundation every later phase builds on: pinned dependencies, the TRD
section 3 package skeleton, the TRD section 4 data models with raw-content fields that
cannot serialise, the policy loader and `policy_hash`, typed content-free errors, the
PII-safe structured logger, an environment doctor, and the verification tooling (`make
check`, verification matrix, style rule, sample smoke stub).

Requirements touched (all PARTIAL; see `docs/VERIFICATION.md`): TR-SEC-01 (suite runs
socket-blocked), TR-SEC-02 (raw fields never serialise; errors content-free), TR-SEC-03
(`PiiSafeFilter`), FR-17 (policy load/validate/hash), TR-GT-05 (LLM requires approval in
config), TR-RD-02 and TR-GT-03 (key presence and format checks).

## Files added / changed

- `pyproject.toml`: package metadata, exact pins, ruff/mypy/pytest config (`--disable-socket`).
- `Makefile`: `setup keys doctor lint format test test-all smoke eval run check clean`.
- `.pre-commit-config.yaml`, `.secrets.baseline`: ruff, ruff-format, detect-secrets,
  no-emoji/no-em-dash, confidential-file blocker.
- `.gitignore`, `.gitattributes`: samples, gold, outputs, secrets, DBs ignored; LF endings.
- `cleargate/` (57 modules): TRD section 3 skeleton. Implemented in this phase:
  - `core/models.py`: Locator, Segment, Coverage, Document, Evidence, Finding,
    RedactionAction, FileFormat, EntityType, DEFAULT_RISK, TOKEN_LABEL, `raw_field()`.
  - `core/config.py`: Policy model, `load_policy`, `parse_policy`, `policy_hash`,
    `load_settings`, key checks, Tesseract resolution.
  - `core/errors.py`: ErrorCode, templates, `safe_detail`, ClearGateError hierarchy.
  - `core/logging.py`: PiiSafeFilter, JsonFormatter, `configure_logging`.
  - `core/states.py`: JobState.
- `config/policy.default.yaml`: TRD section 11 policy plus `limits` (ADR-19).
- `scripts/doctor.py`, `genkeys.py`, `check_matrix.py`, `check_style.py`, `smoke.py`.
- `tests/`: `conftest.py` (sample discovery, skip logic, hypothesis profiles) and 7 test
  modules (128 tests).
- `docs/`: TRD, PRD, Architecture moved here and scrubbed (ADR-14, ADR-18);
  `DECISIONS.md`, `PROGRESS.md`, `VERIFICATION.md`, this report. Root: `README.md`
  (status, links), `CLAUDE.md`, `CHANGELOG.md`.

## How to verify (copy-paste)

```bash
make setup          # venv (Python 3.13 on Windows via py -3.13), deps, spaCy model, .env keys
make doctor         # 7 environment checks
make check          # ruff, ruff format --check, mypy, pytest (not samples/slow), matrix, style
make test-all       # includes the samples-marked tests when Data/ or samples/ exists
make smoke          # writes out/smoke.md (Phase 0: file presence and sizes only)
```

Expected: doctor `7/7 checks passed`; `make check` exits 0 with `124 passed, 4 deselected`,
`check_matrix: 97 rows ... 0 problem(s)` and `check_style: 0 violation(s)`; `make test-all`
`128 passed`.

## Actual results

**Environment** (`make doctor`, after `make keys`):
```
[PASS] python>=3.12                3.13.15
[PASS] tesseract>=5 with eng       5.4.0, eng=yes
[PASS] spacy model en_core_web_lg  3.8.0 (spacy 3.8.16)
[PASS] opencv face cascades        opencv 4.14.0, missing=[]
[PASS] data dir writable           D:\Projects\Optiv_Case_Study\data
[PASS] CLEARGATE_VAULT_KEY         set, valid
[PASS] CLEARGATE_GATE_KEY          set, valid
doctor: 7/7 checks passed
```
Without keys the same command reports `[FAIL] CLEARGATE_VAULT_KEY KEY_MISSING`,
`[FAIL] CLEARGATE_GATE_KEY KEY_MISSING`, `doctor: 5/7 checks passed`, exit 1.

**Static checks** (`make lint`):
```
ruff check .            All checks passed!
ruff format --check .   90 files already formatted
mypy                    Success: no issues found in 59 source files
```

**Tests**: `make check` gives `124 passed, 4 deselected`; `make test-all` gives
`128 passed` (the 4 samples-marked tests ran against `Data/`). 0 xfailed, 0 skipped.

| Module | Tests | What it proves |
|---|---:|---|
| `tests/unit/test_models.py` | 11 | Segment.text and Finding.value absent from `model_dump`, `model_dump(mode="json")`, `model_dump_json`, `repr`, `str`, nested Document, explicit `include`; hypothesis property over arbitrary text; still present after pickling (worker transfer) |
| `tests/unit/test_config.py` | 24 | default policy loads; hash is deterministic, stable under key reordering in the YAML file (5 shuffles) and in a hypothesis property, changes when a value changes, ignores omitted defaults; 8 invalid policies rejected with the field named; duplicate YAML keys rejected; key validation |
| `tests/unit/test_errors.py` | 14 | every code has a template; content-like details redacted from message, `repr` and API body; `args` holds only the code |
| `tests/unit/test_logging.py` | 8 | needle records dropped (case-insensitive, in extras, from third-party loggers); exception args and tracebacks stripped; per-job needle release |
| `tests/unit/test_skeleton.py` | 49 | every TRD section 3 module imports; JobState values match the TRD |
| `tests/unit/test_tooling.py` | 16 | no emoji/em dash in the repo; checker catches 5 banned characters and allows arrows/math; matrix complete; doctor failure paths; sample lookup needs the complete set |
| `tests/security/test_network.py` | 2 | outbound connect and raw socket creation raise `SocketBlockedError` |
| `tests/integration/test_samples_present.py` | 4 (samples) | the three files exist with sizes within 2x of the design profile; the sample dir is git-ignored |

**Exit criteria**

| Criterion | Evidence | Result |
|---|---|---|
| `make check` green | exit 0, output above | PASS |
| `scripts/doctor.py` output pasted | above | PASS |
| A test proves raw fields never serialise | `test_models.py::test_raw_fields_declared_for_every_raw_model`, `test_segment_text_never_serialises`, `test_finding_value_never_serialises`, `test_property_any_text_is_absent_from_dumps` | PASS |
| Policy hash stable across key reordering | `test_config.py::test_policy_hash_stable_across_key_reordering_in_yaml`, `test_property_hash_independent_of_mapping_order` | PASS |

**Cross-checks run:** pre-commit hooks on all files (ruff, ruff-format, detect-secrets,
style rule all Passed; confidential-file blocker found no files to check, i.e. nothing
under `Data/` is staged). `git check-ignore` confirms `Data/` and `.env` are ignored.

**Sample smoke** (`make smoke`, no pipeline stages yet): all three sample files present;
sizes 14,094,994 / 4,830,291 / 72,043 bytes (PDF / DOCX / PPTX), consistent with the
design profile (~14 MB / ~4.8 MB / ~72 KB).

**Pinned versions** (resolved 13 Oct 2026; differences from TRD section 15 in ADR-17):
fastapi 0.143.0, uvicorn 0.54.0, pydantic 2.14.1, streamlit 1.65.0, pymupdf 1.28.2,
pdfplumber 0.11.10, python-docx 1.2.0, python-pptx 1.0.2, lxml 6.1.3, pytesseract 0.3.13,
presidio-analyzer 2.2.364, spacy 3.8.16 + en_core_web_lg 3.8.0, phonenumbers 9.0.41,
rapidfuzz 3.14.6, opencv-python-headless 4.14.0.94, pyahocorasick 2.3.1, cryptography
50.0.2, pillow 12.3.0; dev: pytest 9.1.1, hypothesis 6.169.0, pytest-socket 0.8.1,
pytest-cov 7.1.0, ruff 0.17.0, mypy 2.4.0, pre-commit 4.7.0, detect-secrets 1.5.0.

## Deviations from spec

- ADR-14: sample-derived names and numbers in the design docs replaced by invented values.
- ADR-15: `Data/` accepted as the sample directory alongside `samples/`.
- ADR-16: Windows 11, Python 3.13.15, Tesseract 5.4.0 (design profile used 5.3.4 on Linux).
- ADR-17: five pins differ from TRD 15; OpenCV held at 4.14 because 5.0 dropped the
  Haar face cascades.
- ADR-18: no phase branches (user instruction); no emoji or em dashes, enforced by a check.
- ADR-19: `limits` section added to the policy; four employee-ID patterns per TR-DT-10.
- TRD 4 lists `heading_level`, `ocr_word_conf`, `parent_id` without defaults; they default
  to `None` here so extractors need not pass them (no behavioural change).

## Known gaps / risks carried forward

- `Coverage.uninspected` is `list[Locator]` (TRD 4) but TR-EX-40 wants an error code per
  part. To resolve in Phase 3 with an ADR.
- Presidio's email recognizer uses `tldextract`, which can fetch the public suffix list
  over the network. Must be forced offline when detection lands (TR-SEC-01).
- `0700` permissions and `RLIMIT_AS` (TR-SEC-04/07) do not exist on Windows; Phase 2 needs
  a Windows treatment and the Phase 11 Docker image provides the POSIX behaviour.
- `PiiSafeFilter` uses a linear scan over needles; fine for tests, to be replaced by
  Aho-Corasick if needle sets grow (Phase 7 builds the automaton anyway).
- The policy path resolves relative to the repository; a non-editable install needs
  `CLEARGATE_POLICY`. Acceptable for the prototype.
- The development machine has 12 logical CPUs, not the 2-vCPU reference; every timing in
  later phases must state its CPU count.

## Next phase entry criteria

- `make check` green on `main` at tag `v0.0.0`.
- Phase 1 scope agreed: `meta.db` schema with the TR-GT-02 trigger, `gate/machine.py`,
  `gate/rules.py` (G0..G7), `gate/handle.py`, with the Phase 1 exit tests from the brief.
