# Phase 09: Web UI (React, integrated)
Tag: v0.9.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built
The user-supplied React 18 + TypeScript UI (`cleargate-ui/`) replaces Streamlit (ADR-32) and
talks to the real API: upload, batch and job tracking, findings, report, review workspace,
downloads (enabled only when SAFE) and the AI handoff. `make ui` builds it in live mode;
`make run` serves API and UI on http://127.0.0.1:8000.

## How to verify (copy-paste)
```powershell
make ui
make run          # then open http://127.0.0.1:8000
make e2e          # Edge-driven browser smoke test
```

## Actual results
- UI unit tests `npm test`: `23 passed`; `npm run lint`: clean; the production bundle
  contains no mock worker.
- `tests/e2e/test_ui_smoke.py` (Playwright driving Edge, synthetic PPTX): `1 passed`:
  connect -> upload -> REVIEW_REQUIRED -> confirm all -> re-verify -> VALIDATED_SAFE ->
  download (no planted value in the file) -> handoff. Screenshots: `docs/img/`.

## Deviations from spec
- ADR-32: React UI instead of Streamlit (user decision), with small integration changes.

## Known gaps / risks carried forward
- The "Add region" tool in the UI uses a fixed sample box (UI limitation carried over).
