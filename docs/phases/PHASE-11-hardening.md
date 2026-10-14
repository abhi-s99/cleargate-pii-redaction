# Phase 11: Hardening, Docker image, demo script
Tag: v0.11.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built            (requirements covered: TR-SEC-07, TR-SEC-09, TR-PF-01, TR-PF-04, PRD 8 portability)
- `RLIMIT_AS` on the PDF OCR workers (`cleargate/core/limits.py`,
  `CLEARGATE_WORKER_MEM_MB`, default 6144 MiB); the OCR pool now uses `spawn` on every
  platform (ADR-34).
- `Dockerfile` (two stages: UI build, then Python 3.13 slim with Tesseract and the pinned
  spaCy model, non-root), `docker-compose.yml` (loopback port, data volume, read-only root,
  `cap_drop: ALL`, memory limit), `.dockerignore` (no samples, gold, `.env` or databases).
- `docs/DEMO.md`: a 12-minute walkthrough with pre-warm and fallbacks.
- Performance tests for TR-PF-01 and TR-PF-04; a README test for the TR-SEC-09 limits.
- README: quickstart, Docker and CLI sections corrected (they named Streamlit, a
  `cleargate eval` command and a `role_title_policy` option, none of which exist).

## Files added / changed
- `cleargate/core/limits.py`, `cleargate/core/config.py`, `cleargate/extract/pdf.py`:
  memory limit and spawned pool.
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`: image and stack.
- `tests/unit/test_limits.py`, `tests/unit/test_docs.py`,
  `tests/integration/test_performance.py`,
  `tests/integration/test_extract_failclosed.py` (pool vs in-process OCR): new tests.
- `docs/DEMO.md`, `docs/DECISIONS.md` (ADR-34), `README.md`, `docs/VERIFICATION.md`.

## How to verify (copy-paste)
```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_limits.py tests/unit/test_docs.py tests/integration/test_performance.py -q
.venv\Scripts\python.exe -m pytest -m "not samples and not slow" -q
docker compose up -d --build      # then http://127.0.0.1:8000 (CLEARGATE_PORT for another port)
```

## Actual results
- Fast suite: `835 passed, 1 skipped, 14 deselected` (the skip is the POSIX-only memory
  test, run in the image instead). mypy: no issues in 74 files. `check_style`: 0
  violations. `check_matrix`: 0 problems (PASS 72, PARTIAL 22, TODO 3).
- Performance tests: `3 passed in 27.82s`. Pool regression test: `1 passed in 9.82s`.
- Docker image `cleargate:0.11.0`, 2.56 GB. Inside it: Tesseract 5.3.0, spaCy model loads,
  uid 10001; under `limit_memory(256)` a 1 GiB allocation raises `MemoryError`.
- Container round trip on synthetic fixtures (port 8765): `planted.png` and
  `planted_native.pdf` VALIDATED_SAFE (G7); `planted.pptx` REVIEW_REQUIRED (G6), then
  confirmed, VALIDATED_SAFE, downloaded with 0 planted values left; `planted_scanned.pdf`
  and `planted.docx` REVIEW_REQUIRED (G6) with no crash in the logs.
- Found and fixed while testing the image: the forked OCR pool inherited the service's
  4.4 GB address space and every worker failed under the limit (the job ended `FAILED`,
  fail closed). Spawned workers need about 3.7 GB of virtual space; 3072 MiB broke OCR,
  4096 MiB worked, so the default is 6144 MiB.
- Real-sample timings (earlier `make smoke` run, 12 CPUs, 4 OCR workers; not re-run in
  this phase): scanned PDF 212.2 s for 35 pages = 6.1 s/page (TR-PF-03 target 20 s/page);
  DOCX with 36 images 199.4 s (TR-PF-02 target 180 s: missed); PPTX with 9 pictures 32.4 s.

## Deviations from spec
- ADR-34: memory limit default 6144 MiB of virtual address space and a spawned OCR pool.

## Known gaps / risks carried forward
- TR-PF-02 missed on the DOCX sample (199 s vs 180 s); TR-PF-02/03 have no automated test.
  The 2 vCPU reference machine was not measured.
- DOCX/PPTX image OCR runs in the service process: bounded only by the container limit.
- The image uses Tesseract 5.3 (Debian), the development machine 5.4.
- Real-sample evaluation needs the annotated gold set (Phase 10, ADR-33).
- `REFERENCE_GAP_ANALYSIS.md` and the stakeholder deck are not written.

## Next phase entry criteria
- None: this is the last build phase. Remaining items are listed above and in PROGRESS.
