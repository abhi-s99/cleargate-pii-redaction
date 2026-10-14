# Phase 07: Independent verification
Tag: v0.7.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built
`verify/`: V1 two-parser reopen, V2 Aho-Corasick leak search over the raw re-read output
(XML parts, paragraphs, attributes, PDF text via PyMuPDF and pdfplumber, OCR of every output
raster) and the sanitized text, V3 residual scan with the verify profile, V4 coverage and
unit counts, V5 token consistency against the vault, V6 SRS/CRS; one repair pass for hits
located in output rasters. Interpretations: ADR-30.

## How to verify (copy-paste)
```powershell
.venv\Scripts\python.exe -m pytest tests\integration\test_verify_faults.py -q
.venv\Scripts\python.exe -m pytest tests\integration\test_pipeline_samples.py -q   # needs Data/, ~6 min
make smoke
```

## Actual results
- Fault injection: `6 passed` (value left in output: `BLOCKED` G1; new SSN planted in output
  only: `BLOCKED` G2; output does not reopen: `FAILED` G0; token missing from vault: `BLOCKED`
  G5; pixels missed by the writer: repaired and re-verified; verifier crash: `FAILED` G0).
- Samples end to end (`test_pipeline_samples.py`): `2 passed in 368.48s`.
- `make smoke` (12 CPUs, counts only, batch wall 385 s):

| File | State | Review findings | Actions applied | V2 leaks | V3 det/other | V4 unread | SRS | CRS |
|---|---|---:|---|---:|---|---:|---:|---:|
| Risk policy PDF | REVIEW_REQUIRED (91 items, 11 regions, 27 residual) | 91 | 915/915 | 0 | 0/27 | 0 | 1.0 | 1.0 |
| TPRM DOCX | REVIEW_REQUIRED (103 items, 16 regions, 9 residual) | 103 | 156/156 | 0 | 0/9 | 0 | 1.0 | 1.0 |
| Org pack PPTX | REVIEW_REQUIRED (3 items) | 3 | 124/124 | 0 | 0/0 | 0 | 1.0 | 1.0 |

The PDF ends `REVIEW_REQUIRED` as TRD 14 expects (Fig. 3 face and illegible regions).

## Deviations from spec
- ADR-30 (needle rules, "new" residual definition, repair pass, mask-effect OCR codes, SRS units).

## Known gaps / risks carried forward
- Residual scanning cannot prove zero PII; OCR noise on redacted rasters creates review items.
- Repair boxes assume `verify_ocr_dpi == ocr.dpi` (both 300).
