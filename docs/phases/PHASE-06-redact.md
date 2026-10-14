# Phase 06: Redaction
Tag: v0.6.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built
Batch-scoped typed tokens and a Fernet vault (TR-RD-01/02); format-native writers: DOCX/PPTX
run-level edits through shared text maps, images swapped in place, metadata and author
attributes scrubbed, thumbnail removed (TR-RD-10/11); scanned PDF raster burn-in and native
PDF true redaction (TR-RD-20/21); PNG/JPEG/TIFF with EXIF stripped (FR-18); the sanitized
text renderer (TR-RD-30); unapplied actions block the gate (TR-RD-40). The pipeline now runs
per batch with an encrypted job state for review re-runs. Details and deviations: ADR-29.

Code landed in `b718ec2` together with Phase 7 (the pipeline wiring needs both).

## How to verify (copy-paste)
```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_redact_units.py tests\integration\test_redact_fixtures.py -q
```
Expected: `32 passed`.

## Actual results
- `test_redact_units.py`: 18 passed (span across 3 runs keeps first-run formatting; vault
  ciphertext unreadable without the key; token consistency and styles; renderer markers;
  EMF rebuild keeps its frame; EXIF stripped).
- `test_redact_fixtures.py`: 14 passed (every planted value absent from the raw output and
  the sanitized text, OCR values absent from output OCR; two-parser reopen; page/slide
  counts unchanged; media part names and rIds kept; `docProps` scrubbed; no original image
  XObject in the scanned PDF; same person gets the same token across files; forced
  unapplied action ends `BLOCKED` G4).
- Visual spot check (synthetic only): two redacted PDF pages and the redacted DOCX/PPTX
  pictures were rendered to `out/visual/` and inspected: names, IDs, the face and the
  illegible region are black boxes; `INC-7720` and `GRP-POL-007` remain readable. Slides
  cannot be rendered (no LibreOffice), so their pictures were checked instead.

## Deviations from spec
- ADR-29 (writers, part removal, EMF rebuild, batch pipeline, encrypted state).

## Known gaps / risks carried forward
- WMF pictures with findings cannot be rewritten (unapplied, blocks); none in the samples.
- No invisible text layer on rebuilt scanned pages (TR-RD-20 MAY, PRD cut line).
