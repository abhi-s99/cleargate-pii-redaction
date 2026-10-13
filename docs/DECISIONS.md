# Decisions log (ADR-14 onwards)

ADR-01..13 are in [Architecture.md](Architecture.md#4-technical-decisions-adr-log). This file
records every later decision and every deviation from the TRD, Architecture or PRD, with
context, decision, alternatives and consequences.

---

### ADR-14: Scrub sample-derived values from the design documents
- **Context:** The design documents (Architecture D4, D6, D8, D9, D10, ADR-04; TRD 4, 6.2,
  7, 14) quoted literal values: person names, a person's email local part, phone numbers,
  number suffixes, an SSN last-four and an OCR-garbled risk ID. A count-only check
  confirmed that three of the quoted surnames occur in the sample PPTX. The brief forbids
  any sample value in committed docs.
- **Decision:** Replace each such value with an invented placeholder of the same shape
  (for example an initial-plus-surname example, `+1 (555) 01NN`, `ending NNNN`) before the
  first commit of `docs/`. The meaning of every requirement is unchanged.
- **Alternatives:** keep the docs out of git (loses the spec from the repo); commit as-is
  (breaks confidentiality).
- **Consequences:** The docs illustrate patterns with invented values only. Tests follow
  the same rule.

### ADR-15: Accept `Data/` as the sample directory alongside `samples/`
- **Context:** The brief expects the real files in `samples/`; the team placed them in
  `Data/`.
- **Decision:** Sample-marked tests and `make smoke` look in `CLEARGATE_SAMPLES_DIR`, then
  `samples/`, then `Data/`. Both directories are git-ignored, and a pre-commit hook refuses
  any staged file under them (and any `.pdf/.docx/.pptx` outside the synthetic fixtures).
- **Alternatives:** move the user's files (unrequested change to their workspace).
- **Consequences:** None for behaviour. A test asserts the sample directory is git-ignored.

### ADR-16: Development platform is Windows 11 with Python 3.13 and Tesseract 5.4.0
- **Context:** The design profile used 2-vCPU Linux, Tesseract 5.3.4 and Python 3.13. The
  team machine is Windows 11 (12 logical CPUs). The system Python was 3.11 (below the
  3.12 floor) and 3.14, which spaCy 3.8 and Presidio do not support reliably yet.
- **Decision:** Install Python 3.13.15 (user scope) and use it for `.venv`. Install
  Tesseract 5.4.0 (UB Mannheim build, the current Windows build) and GNU make via winget.
  Tesseract is found through `CLEARGATE_TESSERACT_CMD`, then `PATH`, then the default
  Windows install path.
- **Alternatives:** WSL or Docker for development (Docker arrives in Phase 11 as the Linux
  reference build).
- **Consequences:** OCR confidences and timings may differ from the design numbers; Phase 3
  re-measures and records the difference. Every timing states its CPU count. POSIX-only
  controls in TR-SEC-04/07 (`0700` mode, `RLIMIT_AS`) need a Windows-specific treatment
  in Phase 2; the Docker image provides the POSIX behaviour.

### ADR-17: Dependency pins differ from TRD section 15 in five places
- **Context:** Versions were re-checked at install time (13 Oct 2026), as the brief asks.
- **Decision:** Pin what resolved on Python 3.13: uvicorn 0.54.0 (TRD 0.53), pydantic
  2.14.1 (TRD 2.13), lxml 6.1.3 (TRD 5.x), cryptography 50.0.2 (TRD 4x). OpenCV is pinned
  to **4.14.0.94** although 5.0.0 is the latest, because OpenCV 5.0 no longer ships the
  Haar face cascades that TR-EX-06 relies on (verified: `cv2.data` has no face cascade in
  5.0.0, both frontal and profile cascades exist in 4.14.0).
- **Alternatives:** pin the TRD versions exactly (older pydantic/lxml have no advantage).
- **Consequences:** The TRD 15 table is a floor, `pyproject.toml` is the source of truth.

### ADR-18: Work on `main` without phase branches; no emoji and no em dashes
- **Context:** The brief asks for a `phase/NN-name` branch per phase merged with `--no-ff`.
  The user instructed: no phase branches, commit and push to `main` directly; and no emoji
  and no em dashes anywhere in the project.
- **Decision:** Commit directly on `main`, tag the last commit of each phase `v0.NN.0`,
  push to the private `origin`. Status marks use words (PASS, PARTIAL, XFAIL, TODO), the
  TRD's raw-content marker is `[RAW]`. `scripts/check_style.py` enforces the character rule
  in `make check`, in a test, and in a pre-commit hook.
- **Alternatives:** none; this is a user instruction.
- **Consequences:** The phase-report header shows the tag only. The design docs were
  converted (emoji removed or replaced by words, em dashes replaced by colons or commas).

### ADR-19: Policy file additions: `limits` section and the fourth employee-ID pattern
- **Context:** TRD 2 says validation limits are configurable but TRD 11 has no key for
  them. TR-DT-10 lists four default employee-ID patterns (including the OCR variant
  `EMP\.\d{5}`) while the TRD 11 YAML lists three. Architecture ADR-04 shows a generic
  vendor-staff pattern where TR-DT-10 has a specific one.
- **Decision:** Add a `limits` section with the TRD 2 defaults. Use the four TR-DT-10
  patterns. Follow the TRD over the Architecture for the vendor-staff pattern.
- **Consequences:** Both additions are part of `policy_hash`.
