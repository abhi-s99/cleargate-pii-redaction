# Phase 08: API, review backend, reports, handoff
Tag: v0.8.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built
FastAPI under `/api/v1` (TRD 10): batches (synchronous validation, background processing
with progress), job status, findings (masked), value-grouped review queue with raw segment
text and masked thumbnails for reviewers, decisions (confirm, reject with justification,
retype, add span, add region, reject document; HIGH-risk deterministic findings cannot be
rejected), re-redaction and re-verification, JSON/Markdown reports without values,
SafeHandle-checked downloads (403 unless `VALIDATED_SAFE`), MockAgent handoff (409 unless
SAFE), batch delete and a TTL sweeper. `cleargate serve` runs it. Details: ADR-31.

## How to verify (copy-paste)
```powershell
.venv\Scripts\python.exe -m pytest tests\integration\test_api.py -q
```
Expected: `10 passed`.

## Actual results
- `test_api.py`: 10 passed (upload -> poll -> review -> SAFE -> download -> handoff on a
  synthetic batch; 401/403 role rules; 403 downloads and 409 handoff before SAFE; reject of a
  HIGH deterministic region refused; justification required; reviewer document rejection
  ends `BLOCKED`; batch delete; planted values absent from reports, findings, job status and
  logs; outbound connections stay blocked).
- Live HTTP check against `cleargate serve`: health shows the model loaded and Tesseract
  5.4.0; a synthetic native PDF reached `VALIDATED_SAFE` and downloaded; a synthetic PPTX
  reached `REVIEW_REQUIRED` with 2 review items and its downloads returned 403.

## Deviations from spec
- ADR-31 (service layer, grouped review, findings visible to submitters as masked previews,
  null fields omitted, loopback-only API tests).

## Known gaps / risks carried forward
- Static bearer tokens, single worker, single node (prototype limits, TR-SEC-09).
