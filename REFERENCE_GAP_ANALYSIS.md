# Reference gap analysis: Smart-Redact vs ClearGate

Brief deliverable (PRD 10). It compares the Smart-Redact reference, as its
**documentation** describes it, with ClearGate as built and tested (tag `v0.11.0`).

**Basis and limits of this comparison.** Only Smart-Redact's documentation was available,
not its source code or a running instance. Every statement about Smart-Redact below is
"documented, not verified": we did not run it and cannot confirm its behaviour. Every
statement about ClearGate cites the test that verifies it (all in `tests/`, run with
`pytest`; see `docs/VERIFICATION.md` for the full requirement-to-test matrix). Architecture
section 3 summarises the design decisions that came out of this analysis.

Status words: **Closed** (ClearGate addresses the gap and a test proves it), **Partial**
(addressed, with a stated limit), **Open** (not addressed).

## 1. Feature-by-feature comparison

| # | Area | Smart-Redact (as documented) | Risk for PS-2 | ClearGate | Evidence | Status |
|---|---|---|---|---|---|---|
| 1 | Scanned PDF input | Text via `pypdfium2` only; no OCR on the PDF path | A scanned PDF yields empty text, 0 findings, and is reported complete: **fails open** | Per-page routing: native text first, OCR (Tesseract, 300 DPI) when a page has too little text or carries images; an unread page is uninspected and blocks the gate | `test_extract_fixtures.py::test_scanned_pdf_has_no_native_text_and_all_pages_ocr`, `test_extract_failclosed.py::test_ocr_disabled_scanned_pdf_ends_blocked_g3` | Closed |
| 2 | PDF output | Rebuilt from plain text with ReportLab | Layout, tables and figures lost; the PS-2 structure target (>= 80 %) cannot be met | Original geometry kept: masks burned into the page raster (scanned) or true content redaction (native); no original image objects left | `test_redact_fixtures.py::test_scanned_output_has_no_original_image_objects`, `::test_outputs_reopen_in_two_parsers_with_unchanged_counts`; SRS = 1.0 on all three samples (`out/smoke.md`) | Closed |
| 3 | Redaction mechanism | `str.replace(entity_text, ...)` over the whole text | Ignores offsets, replaces substrings inside other words, misses variants | Offset-based edits on located segments; OOXML run-level edits that keep formatting; variants handled by the person registry and value propagation | `test_redact_units.py::test_span_crossing_three_runs_keeps_first_run_formatting`, `test_detect_context.py::test_canonical_key_and_variants` | Closed |
| 4 | Verification | Case-insensitive search for the values that were found | Proves only that found values were replaced; blind to missed PII and format variants | Independent re-extraction of the output (separate code path, OCR of output rasters): leak check with normalised and digit forms, residual scan, coverage, consistency, structure (V1 to V6) | `test_verify_faults.py::test_value_left_in_the_output_is_blocked_g1`, `::test_new_identifier_planted_in_output_only_is_blocked_g2`, `::test_verification_crash_fails_closed` | Closed |
| 5 | Entity scope | spaCy `ORG`, `GPE`, `DATE`, `MONEY` treated as PII, fixed confidence 0.8 | Over-redacts vendors, cities and every date; destroys the business context the AI needs | Taxonomy limited to personal data; organisations and products kept (allowlist); dates redacted only as date of birth | `test_detect_fixtures.py::test_decoys_are_not_redacted`, `test_detect_context.py::test_products_kept_while_people_in_same_sentence_are_redacted`; 0 of 7 keep-list terms redacted (`eval/report.md`) | Closed |
| 6 | PPTX handling | PPTX to PDF to PNG to OCR; output is an image-only deck | Native text becomes pictures; OCR errors on clean text; the AI cannot read the output without re-OCR | Native extraction of shapes, groups, tables and notes; in-place run-level redaction; OCR only for pictures | `test_extract_samples.py::test_pptx_structure_matches_profile`, `test_redact_fixtures.py::test_ooxml_parts_rels_and_metadata` | Closed |
| 7 | DOCX handling | Paragraphs, then all tables appended; rebuilt with `Document()` | Reading order, styles, headers and footers, text boxes, images and metadata lost | Ordered body walk over every XML part; the original package edited in place; images swapped by relationship id; metadata scrubbed | `test_extract_fixtures.py::test_segments_are_in_reading_order`, `::test_merged_cells_and_textbox_extracted_once`, `test_redact_fixtures.py::test_ooxml_parts_rels_and_metadata` | Closed |
| 8 | Accuracy claims | "99 %+ precision", "98 %+ accuracy" with no evaluation set | Unverifiable | Evaluation harness: leak rate as the headline metric, per-type precision and recall, 95 % intervals, n with every rate | `test_eval_harness.py::test_planted_docx_and_png_score_without_leaks`; `eval/report.md` | Partial: measured on synthetic gold only; real-sample gold labels are pending (ADR-33) |
| 9 | Status reporting | Image redaction shown as "Completed" in one place and "In Progress / Pending testing" in another | Unclear what works | Every capability has Designed / Implemented / Verified in the README; every requirement has a status and tests in the matrix, checked by `scripts/check_matrix.py` | `docs/VERIFICATION.md`, `README.md` status table | Closed |
| 10 | Safety gate | No processing states, review or AI-gate semantics | Nothing stops unsafe content from reaching the model | Enforced state machine (DB trigger), gate rules G0 to G7, only `decide()` can reach `VALIDATED_SAFE`, handoff needs a signed SafeHandle | `test_gate_machine.py::test_public_transition_can_never_enter_safe`, `test_gate_handle.py::test_tampering_any_field_is_refused`, `test_api.py::test_non_safe_job_refuses_outputs` | Closed |
| 11 | Human review | Not described | Uncertain detections are either silently kept or silently redacted | Review queue grouped by value, with evidence and masked previews; HIGH-risk deterministic items cannot be rejected; decisions trigger re-redaction and re-verification | `test_api.py::test_review_path_reaches_safe`, `::test_reviewer_can_reject_a_document` | Closed |
| 12 | Images in documents | OCR with Tesseract word boxes; nearby regions merged | Faces and illegible screenshots are not treated as personal data | OCR plus face detection and unreadable-region detection; such regions are masked and sent to review | `test_extract_fixtures.py::test_expected_regions_are_found`, `test_detect_fixtures.py::test_illegible_region_item_is_masked_not_read` | Closed |
| 13 | Consistent pseudonyms | Not described | The AI cannot tell that two mentions are the same person | Typed, numbered tokens, consistent across a batch, stored in an encrypted vault | `test_redact_fixtures.py::test_same_person_gets_the_same_token_across_files` | Closed |
| 14 | Leakage through logs and reports | Not described | Raw values copied into logs, reports or the metadata database | Raw values only in memory and the encrypted vault; PII-safe log filter; reports give counts only | `test_api.py::test_reports_and_logs_never_carry_planted_values`, `test_detect_fixtures.py::test_findings_persist_without_values` | Closed |
| 15 | Network | Local processing | None stated | No network at runtime; the test suite runs with sockets blocked; the AI client is a local mock by default | `test_api.py::test_outbound_connection_is_still_blocked` | Closed |

## 2. Ideas kept from the reference

Local-only processing, FastAPI, Tesseract word boxes for image coordinates, Presidio and
spaCy as a base detection layer, merging nearby image regions, and never modifying the
original file (ClearGate works on copies).

## 3. Where ClearGate still falls short

| Gap | Detail | Reference |
|---|---|---|
| Real-sample accuracy is not measured | Needs the annotated gold set for the three samples; synthetic results are a regression signal only | ADR-33, `docs/phases/PHASE-10-eval.md` |
| Review threshold is uncalibrated | Stays at 0.40 until real gold exists; the DOCX and PDF samples produce long review queues | ADR-33 |
| DOCX speed target missed | 199 s against 180 s for the DOCX with 36 screenshots (12 CPUs) | `docs/phases/PHASE-11-hardening.md` |
| Quasi-identifiers kept | Role titles and organisation context stay and can single someone out | README Limitations |
| Prototype security | Static tokens, single tenant, SQLite metadata | README Limitations, TR-SEC-09 |
| English-only NER | Non-Latin names and non-English documents untested | README Limitations |
| No zero-PII proof | Detection, verification, coverage and review reduce risk; they do not prove absence | README Limitations |

## 4. Summary

The documented reference handles clean, text-based documents but **fails open** on the
case's scanned PDF, rebuilds outputs in a way that loses structure, and verifies only what
it already found. ClearGate's design answers each of these with a fail-closed gate,
format-native in-place redaction and independent verification. Of the 15 areas above, 14
are closed with test evidence and 1 is partial (accuracy is measured on synthetic data, not
yet on the real samples).
