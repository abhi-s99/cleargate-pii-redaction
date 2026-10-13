# Phase 03: Extraction and synthetic fixtures
Tag: v0.3.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built

Real extractors replace the Phase 2 stub, plus a deterministic planted-PII fixture set that
every later phase asserts against.

- `extract/pdf.py`: per-page routing (native chars, image coverage), OCR pages rendered and
  analysed in a process pool (OCR, faces, ink, non-text regions per page), native/OCR
  merge, embedded-image OCR on native pages, Info/XMP, annotations with authors, links,
  outline, form fields; embedded files uninspected.
- `extract/docx.py`: ordered lxml walk of body, headers, footers, footnotes, endnotes,
  comments; merged cells once; text boxes once (Fallback ignored); tracked deletions and
  field codes; heading levels and list styles; both alt-text copies; every media part
  OCR'd; attribute authors; docProps; external relationship targets; generic sweep of all
  other parts.
- `extract/pptx.py`: recursive shapes, tables, charts, pictures (logo analysed once), alt
  text, notes; sweep of layouts, masters, comment authors and everything else.
- `extract/image.py`, `extract/ocr.py`, `extract/metadata.py`, `extract/xml.py`,
  `extract/base.py`: standalone images with EXIF; Tesseract wrapper with the encrypted
  TR-EX-08 cache, timeout and unreadable-block rule; YuNet + Haar faces; connected
  non-text regions; shared `analyse_raster` coverage rules.
- `tests/fixtures/make_fixtures.py` + committed `tests/fixtures/synthetic/`: 5 files, 63
  planted items (incl. 1 deliberately illegible region item), 7 decoys (risk/incident/policy
  IDs, products, a company PAN), 4 expected regions.
- `cleargate extract --dump` and `make smoke` now report real structure.

Requirements: TR-EX-01..08, 10, 13, 21, 22, 40 (PASS); TR-EX-11, 12, 20, 30, FR-03, FR-04, FR-18
(PARTIAL, gaps listed in the matrix).

## Files added / changed

- `cleargate/extract/{base,pdf,docx,pptx,image,ocr,metadata,xml}.py` (implemented/new),
  `cleargate/extract/models/` (YuNet model + provenance README).
- `cleargate/core/models.py`: `Region`, `Document.regions`, `Document.extractors`.
- `cleargate/core/config.py`: `Settings.ocr_workers` (`CLEARGATE_OCR_WORKERS`).
- `cleargate/pipeline.py`: default stages use the real extractors.
- `tests/fixtures/{make_fixtures.py, manifest.py, assets/, synthetic/}`.
- Tests: `tests/integration/test_extract_fixtures.py`, `test_extract_failclosed.py`,
  `test_extract_samples.py`, `tests/unit/test_extract_units.py`,
  `tests/unit/test_fixture_generator.py`; `test_cli.py` and `test_pipeline.py` extended.
- `scripts/smoke.py`: full pipeline on the samples, counts-only table to `out/smoke.md`.

## How to verify (copy-paste)

```bash
make check                                    # 490+ tests, lint, mypy, matrix, style
make test-all                                 # adds the samples tests (slow PDF test included)
make smoke                                    # out/smoke.md
cleargate extract Data/Cadence_TPRM_Training.docx --dump
cleargate extract tests/fixtures/synthetic/planted.docx --show-text   # invented data only
python tests/fixtures/make_fixtures.py out/fx && git diff --no-index tests/fixtures/synthetic/manifest.json out/fx/manifest.json
```

To judge the region candidates by eye (team only; images stay in git-ignored `out/`):
`python scripts/show_regions.py Data/Cadence_Group_Risk_Management_Policy__v6.0.pdf`
writes `out/regions/<file>/page-NN.png` with faces in red and unreadable regions in orange.

## Actual results

**Static checks:** ruff All checks passed; ruff format 118 files already formatted; mypy
Success: no issues found in 63 source files.

**Tests:** `make check`: `490 passed, 11 deselected in 25.99s` (before the last three tests
were added; final fast run `503 passed, 1 deselected` including non-slow samples tests);
`make test-all`: `501 passed in 118.24s`, and the final slow PDF test `1 passed in 35.75s`.

**Exit criteria**

| Criterion | Evidence | Result |
|---|---|---|
| Every planted item extracted at the right locator | `test_planted_item_extracted_at_expected_locator`: 62 parametrised cases (all items except the illegible one, which has its own test) | PASS |
| Differential: PyMuPDF vs pdfplumber pages | fixtures (`test_pdf_page_count_pymupdf_vs_pdfplumber`) and the real PDF (35 = 35) | PASS |
| Differential: python-docx vs raw XML | fixtures (`test_docx_units_vs_python_docx`) and real DOCX: 402 paragraphs, 16 tables, 35 inline images in both | PASS |
| Sample dump matches section 1 | table below | PASS, with two explained differences |
| OCR timing per page recorded | `ctx.timings` `ocr_page_p50_s` etc.; numbers below | PASS |
| Tesseract disabled: scanned PDF `BLOCKED` (G3) | fixture (2 variants: no binary, wrong path) and real PDF: `BLOCKED G3 UNINSPECTED_PARTS=35,...` | PASS |
| Fig. 3 (p.9): unreadable-region candidate and a face on that page | `test_pdf_is_fully_scanned_and_fig3_is_flagged`: one face, on p.9, inside the p.9 unreadable region | PASS after ADR-27 (failed with Haar only) |

**Section 1 re-confirmation** (real samples, counts only):

| Fact (design profile) | Measured now | Match |
|---|---|---|
| PDF 35 pages, 0 native text characters | 35 pages; 0 non-whitespace characters (33 pages carry a single space character) | Yes (detail added) |
| All 35 pages need OCR | `ocr_pages = 35` | Yes |
| Mean word confidence per page 79.1-95.7, lowest p.32 | 76.1-95.7, lowest p.32 | Range differs slightly (Tesseract 5.4.0 vs 5.3.4, ADR-16) |
| OCR about 14 s/page wall, 2 processes, 2 vCPU | cold: p50 3.76 s/page per worker, max 5.12 s, 35 pages in about 36 s with 4 workers on 12 logical CPUs | Faster hardware; per-page numbers are not comparable with the 2 vCPU baseline |
| p.9 Fig. 3 face photo, illegible | face detected on p.9 only; p.9 unreadable region (no recognised words) contains it | Yes |
| p.18 Fig. 8 photographed form | two unreadable regions on p.18 (mean word conf 59.5 and 50.4) | Yes |
| PDF Info `Author` holds a name | `pdf:info` `author` segment extracted | Yes |
| DOCX 402 paragraphs, 16 tables, 35 inline images | 402, 16, 35 (plus 1 anchored picture: 36 image references) | Yes |
| DOCX `txbxContent` 4 times incl. Fallback copies | 4 elements (2 body, 2 header3) = 2 boxes, each extracted once | Yes |
| DOCX 56 `descr` attributes | 28 on `wp:docPr` + 28 on `pic:cNvPr`; 58 alt-text segments (56 descr + 2 titles) | Yes |
| DOCX core `creator`/`lastModifiedBy` hold names | metadata segments from `docProps/core.xml` | Yes |
| DOCX: no email/phone in native text, names in screenshots | 829 OCR lines from screenshots; detection in Phase 4/5 | Extraction yes |
| PPTX 9 slides, all native text, 3 tables | 9 slides, 3 tables, 424 native segments, 1 OCR line (the logo, analysed once for its 9 placements) | Yes |
| (new) DOCX contains a `[trash]/0000.dat` part | uninspected `EMBEDDED_OBJECT`, blocks via G3 until the writer drops it | New finding |

**Sample smoke** (`make smoke`, cold cache; 12 logical CPUs, 4 OCR workers; batch wall
70.1 s; stages after extraction are still stubs):

| File | State | Rule | Reason | Segments native/OCR | Regions | Uninspected |
|---|---|---|---|---|---|---|
| Risk policy PDF | BLOCKED | G3 | V2, V3, V5 not run | 10 / 1897 | face 1, unreadable 10 (pp. 9, 12, 14, 15, 18, 19, 20) | none |
| TPRM DOCX | BLOCKED | G3 | `UNINSPECTED_PARTS=1` + not-run checks | 1402 / 829 | unreadable 16 | `EMBEDDED_OBJECT` 1 (`[trash]`) |
| Org pack PPTX | BLOCKED | G3 | V2, V3, V5 not run | 424 / 1 | none | none |

**Cross-checks run**

- *Planted-PII round trip:* 63/63 items found at the expected locator (kind, part, page,
  slide, table, row, col, metadata key); `once` items (merged cells, text box) exactly once;
  vMerge continuation and gridSpan-covered cells produce no segment.
- *Differential:* pages (PyMuPDF/pdfplumber), paragraphs/tables/inline images
  (lxml walk/python-docx), slides (walk/python-pptx), on fixtures and samples.
- *Fault injection:* OCR missing, OCR binary path wrong, OCR timeout, corrupt image part,
  XXE in a document part, plain DOCX thumbnail without OCR: each `BLOCKED G3`.
- *Determinism:* regenerated manifest equals the committed one; regenerated PNG is
  pixel-identical.
- *Test-quality findings:* the generator produced colliding item IDs (fixed, test added);
  the manifest's fuzzy matcher let short OCR fragments "contain" a value (fixed; the round
  trip still finds 63/63); the "illegible" fixture region was legible to Tesseract (made
  illegible; a test now proves OCR cannot read it); a stale OCR cache entry hid the
  single-character fix (cache key now versioned).

## Deviations from spec

- ADR-26: extraction covers attribute authors, deleted text, field codes, relationship
  targets, PDF annotations/links/outline/forms and a generic part sweep; OCR cache encrypted
  and versioned; `Region` added to the CDM.
- ADR-27: YuNet added next to the Haar cascades; connected non-text regions implemented for
  scanned pages; single-character words ignored in block statistics; whole-image region
  for wordless pictures with content.

## Known gaps / risks carried forward

- Five unreadable candidates on the PDF (pp. 12, 14, 15, 19, 20) are of unknown truth until
  gold labels exist; each will cost review effort.
- `printerSettings*.bin` (python-pptx template) and the DOCX `[trash]` part stay uninspected
  until the Phase 6 writer removes them.
- EMF/WMF rasterisation works on Windows only; on Linux (Docker) such parts will be
  uninspected, i.e. blocked. To be checked in Phase 11.
- SVG text, charts, footnotes/endnotes and `custom.xml` paths are implemented but not in the
  fixtures yet.
- Regions are extracted but not yet masked or turned into findings (Phases 5-6). Until then
  the gate cannot pass because V2/V3/V5 have not run (ADR-24).
- Real-sample diagnosis was done on numbers only (boxes, counts, confidences); no sample
  page was viewed, in line with the README rule on AI assistants and sample content.

## Next phase entry criteria

- `make check` green at `v0.3.0`. Phase 4 adds deterministic recognizers (L1) and
  label-anchored capture (L2) and asserts their types against the same manifest.
