# ClearGate: Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Product | ClearGate, privacy gate for AI document analysis |
| Client scenario | Cadence Financial Group (Optiv case study PS-2: Text Analysis and PII Detection) |
| Version | 0.1, design baseline |
| Date | 13 Oct 2026 |
| Delivery window | ~3 weeks from case release, team submission |
| Related | [README](../README.md) · [Architecture](Architecture.md) · [TRD](TRD.md) |

---

## 1. Problem

Cadence employees use a document-analysis AI agent to review business documents. A recent policy forbids personal data from being processed by AI models. The documents arrive as scanned policies, organisational PowerPoints and process documents, with PII in body text, tables, images, screenshots and file metadata.

Removing it by hand is slow and inconsistent, and it fails exactly where it matters: identifiers in narrative prose, names inside screenshots, scans where the text is only pixels. Simple tools fail too, and they fail **open**: a scanned PDF with no text layer comes back as "0 PII found", and the document goes to the model.

> **PS-2 goal (from the Optiv brief):** design and implement a repeatable, scalable system that extracts text from each file format, identifies and classifies the PII, applies transparent tags, summarises what was found with source traceability, and redacts it before LLM processing. Extracted text must keep **≥ 80 % of its original structure** with surrounding context. PII detection should **approach 100 % coverage**, with minimal false positives and **no unidentified instances passed downstream**.

## 2. Product vision

**Nothing reaches the AI model unless ClearGate can show it is safe.** ClearGate gives every document an explicit, evidence-backed verdict: safe, needs review, blocked or failed. It also produces a sanitized version that still makes sense to the AI: who did what stays visible as `[PERSON_7]`, and vendors, dates and figures remain.

## 3. Users and stakeholders

| Persona | Need | Primary surfaces |
|---|---|---|
| **Submitter**, Cadence employee (e.g., risk analyst) | Upload a document, get a usable sanitized version quickly, understand why it is blocked if it is | Upload screen, status, downloads |
| **Privacy reviewer**, Data Privacy Office / internal audit | Resolve uncertain findings fast, with evidence, and leave an audit trail | Review queue, finding detail, report |
| **AI agent operator**, owner of the analysis agent | A guarantee that the agent only receives validated content | Handoff API, SafeHandle |
| **CPO / internal audit** (Cadence) | Exposure summary: what PII, where, how much, which documents were stopped | Processing report, batch summary |
| **Optiv evaluators** | See the blueprint, architecture, extraction logic, measured reliability and a live demo | Docs, evaluation report, demo |

## 4. Goals and non-goals

### Goals (v1)
- **G1** Extract text and structure from the PS-2 formats (PDF incl. scanned, DOCX, PPTX), with OCR wherever text exists only as pixels.
- **G2** Detect and classify PII, including in tables, narrative prose, images/screenshots and metadata, and tell **people apart from vendors, products and organisations**.
- **G3** Redact so that originals **cannot be recovered**, with consistent typed tokens that keep the business context.
- **G4** Verify outputs **independently** and enforce a **fail-closed privacy gate** before any AI handoff.
- **G5** Route uncertain cases to **human review** with evidence.
- **G6** **Measure** reliability on labelled data and report it honestly against the PS-2 targets.

### Non-goals (v1)
- Production identity, multi-tenancy, or enterprise access control (documented as a prototype limit).
- Calling a real external LLM (the handoff is a mock by default; a real client is behind a disabled flag).
- Client-identity anonymisation (logos, company names). Organisation names are not PII under PS-2. Listed as future work (§11).
- Training custom NER models.
- Legacy binary formats (`.doc`, `.ppt`) and Excel. Excel is not in the PS-2 sample set; it is a stretch goal.

## 5. Sample-set findings that shape the product

Profiled on the actual PS-2 files (details in [Architecture §2](Architecture.md#2-what-the-sample-files-taught-us-design-drivers)):

| Artifact | Structure | PII observed (types, not values) | Product implication |
|---|---|---|---|
| Group Risk Management Policy v6.0 (PDF, 35 pp.) | **Fully scanned**: 0 native characters, one image per page | Names, corporate emails, international phones, employee/director/vendor IDs, SSNs, Indian PANs, a partially masked Polish PESEL, passport number, DOBs, home addresses, card/account suffixes, SSN last-four, a face photo, author name in metadata. Several identifiers sit in a photographed form and an illegible screenshot | OCR is mandatory. Uninspectable regions must be masked + reviewed. Narrative PII requires NER + context |
| TPRM Training (DOCX) | 402 paragraphs, 16 tables, 35 images (~30 UI screenshots), text boxes, headers/footers | People named in table cells as `/`-separated lists and only inside screenshots. Many product/vendor names (OneTrust, Ironclad, Torii). Names in document metadata and the version-control table | Image OCR inside DOCX. Proper-noun disambiguation. Metadata scrubbing |
| Organizational Pack (PPTX, 9 slides) | All native text, 3 tables | 16-person directory with corporate emails and mobiles in a **non-standard format** that a standard phone library rejects. Abbreviated names in RACI headers. Same people repeated across slides and across the other two files | Label-anchored phone detection. Name-variant resolution. Batch-consistent tokens |

The PDF's own exercise prompts (p.35) double as acceptance criteria: report which pages needed OCR; enumerate PII by category with page and location; separate body/table/narrative/image-only occurrences; measure the recall gap between image-only and native text; handle unlabelled narrative identifiers; produce a masked derivative that keeps page count, layout and cross-artifact traceability with stable tokens; justify false-positive controls for PAN, PESEL, TIN and card patterns.

## 6. User stories

| ID | As a… | I want to… | So that… | Priority |
|---|---|---|---|---|
| US-01 | Submitter | upload several documents at once | I can prepare an analysis pack in one go | MUST |
| US-02 | Submitter | see each file's state and progress (e.g., "OCR page 12/35") | I know when it will be ready | MUST |
| US-03 | Submitter | get a clear reason when a file is rejected or fails | I can fix or escalate it | MUST |
| US-04 | Submitter | download sanitized text and a redacted file once safe | I can feed the AI agent or share the file | MUST |
| US-05 | Submitter | see counts of PII by type and where they were found | I trust what was removed | MUST |
| US-06 | Reviewer | see uncertain findings with the text, location, detectors and proposed token | I can decide quickly and correctly | MUST |
| US-07 | Reviewer | confirm, reject (with reason), retype, or add a missed span/region | the output is right and my decisions are recorded | MUST |
| US-08 | Reviewer | have the system re-verify after my decisions | my approval can't accidentally let a leak through | MUST |
| US-09 | AI operator | receive only content that carries a valid SafeHandle | unsafe content cannot reach the model | MUST |
| US-10 | CPO/audit | get a processing report per document and batch | I can evidence control effectiveness | MUST |
| US-11 | Evaluator | see measured precision/recall/leak rate per PII type | I can judge reliability against PS-2 | MUST |
| US-12 | Submitter | see the same person get the same token across all files in a batch | the AI can still follow who did what | SHOULD |
| US-13 | Privacy admin | adjust which types are redacted and the allowlist of vendors/products | the policy fits Cadence | SHOULD |
| US-14 | Submitter | upload standalone images (PNG/JPG/TIFF) | screenshots get the same treatment | SHOULD |
| US-15 | Submitter | process XLSX | spreadsheets are covered | MAY |

## 7. Functional requirements

| ID | Requirement | Acceptance criteria | Pri. |
|---|---|---|---|
| FR-01 Ingestion | Accept PDF, DOCX, PPTX (+ images SHOULD). Validate type by content, size, page/zip limits, encryption | Mismatched extension, encrypted, macro-enabled, oversized or zip-bomb files are rejected with a specific message. Valid PS-2 samples are accepted | MUST |
| FR-02 Batch workflow | Multiple files per batch. Background processing with per-stage progress | 3 PS-2 samples processed in one batch. UI shows progress without blocking | MUST |
| FR-03 Structure-aware extraction | Native extraction per format with OCR fallback for scanned pages and embedded images. Metadata, headers/footers, text boxes, alt text, notes included | Report lists which pages/images used OCR (exercise prompt 1). Coverage = 100 % inspected or masked | MUST |
| FR-04 Source traceability | Every finding records its location: page+bbox / slide+shape / table row+col / XML part / image | Report shows location for each finding. A reviewer can jump to it | MUST |
| FR-05 Layered detection | Validators, label-anchored capture, NER, context rules, entity resolution/propagation | All PII types in §5 are detectable. Unit tests per recognizer pass | MUST |
| FR-06 People vs business entities | Distinguish personal names from organisations, vendors and products | Allowlisted product/vendor names are not redacted. People in the same sentence or cell are | MUST |
| FR-07 Confidence-aware decisions | Evidence tiers. Uncertain MEDIUM/HIGH findings go to review. Thresholds configurable and calibrated | Changing the thresholds in config changes routing (tested). No HIGH-risk deterministic finding can be dismissed | MUST |
| FR-08 Redaction modes | Typed tokens (`[EMAIL_n]`), consistent person pseudonyms per batch, policy-selectable types | Example: `Rahul Sharma from Finance can be contacted at rahul@example.com.` → `[PERSON_1] from Finance can be contacted at [EMAIL_1].` | MUST |
| FR-09 Secure redacted files | Burn into pixels (scans/images) or remove from content (native PDF/OOXML). Scrub metadata. No overlays | Text extraction and OCR of outputs find no original value. Page/slide counts unchanged | MUST |
| FR-10 Independent verification | Leak check, residual scan, coverage, integrity, structure | Fault-injection tests (TRD §14) all end in a non-SAFE state | MUST |
| FR-11 Privacy gate | Enforced states `PROCESSING`, `REVIEW_REQUIRED`, `BLOCKED`, `VALIDATED_SAFE`, `FAILED`. Downloads and handoff only when SAFE | Illegal transitions raise. API returns 403/409 otherwise. Handoff rejects a tampered handle | MUST |
| FR-12 Human review | Review queue with evidence and actions. Re-verify after decisions | A review → re-verify → SAFE path is demonstrated on the PDF | MUST |
| FR-13 Reporting | Per document: file name and type, state, entity counts by type, locations, redaction actions, verification results, unresolved items, duration, extraction warnings. Batch summary | Report contains no raw PII (automated grep test) | MUST |
| FR-14 AI handoff | Mock agent receives sanitized text via SafeHandle. A real LLM client exists but is disabled by default | Demo shows the agent summarising sanitized text. Raw text has no code path to the client | MUST |
| FR-15 Evaluation harness | Gold annotations + metrics + report vs PS-2 targets | `eval/report.md` regenerated from code. Limitations stated | MUST |
| FR-16 Audit trail | State history, review decisions, policy hash per job | Every state change has a reason and timestamp | MUST |
| FR-17 Policy configuration | YAML policy: enabled types, keep-lists, allowlist, thresholds, OCR settings | Policy hash shown in every report | SHOULD |
| FR-18 Images | Standalone image support | Same pipeline, EXIF stripped | SHOULD |
| FR-19 XLSX | Cell-level extraction/redaction | - | MAY |

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Privacy | Local processing by default. No outbound calls. No raw PII in logs, metadata DB, reports or error messages. Encrypted pseudonym vault, never exported |
| Safety | Fail-closed: any error, uninspected part or unapplied redaction prevents `VALIDATED_SAFE` |
| Performance | DOCX/PPTX without images ≤ 15 s. Scanned PDF ≤ 20 s/page on 2 vCPU (OCR measured at ~14 s/page). Progress updates ≤ 5 s apart |
| Data lifecycle | Job data deleted after 24 h (configurable) or on request |
| Usability | A reviewer resolves a typical item in < 30 s (target, to be observed in the demo dry-run) |
| Portability | `docker compose up` on a laptop. No GPU, no paid services |
| Explainability | Every finding shows detectors, rule ids and context terms that produced it |

## 9. Success metrics

Targets are **hypotheses to be measured**, not claims. With only three real documents, results are reported with counts and 95 % intervals and are not generalised.

| Metric | Target | PS-2 link |
|---|---|---|
| Leak rate (gold PII present in sanitized output) | **0** on the sample set, enforced by the gate | "no unidentified instances passed downstream" |
| Recall, deterministic identifier types | ≥ 0.98 | "approach 100 % coverage" |
| Recall, PERSON (native text / OCR text / image-only) | ≥ 0.95 / ≥ 0.90 / reported separately | Exercise prompt 3 (image-only recall gap) |
| Precision overall | ≥ 0.90 | "minimal false positives" |
| False positives on allowlisted vendors/products | 0 | Proper-noun challenge |
| Structure Retention Score (SRS) | ≥ 0.80 (aim ≥ 0.95 for DOCX/PPTX) | "≥ 80 % of original structure" |
| Context Retention Score (CRS) | ≥ 0.80 | "preceding and succeeding context preserved" |
| Fault-injection tests ending non-SAFE | 100 % | Gate correctness |
| Review load | Reported (expect the PDF to need review because of illegible regions) | Practicality |

Definitions: [TRD §9](TRD.md#9-metrics-definitions-used-by-reports-and-evaluation).

## 10. Scope and release plan (3 weeks)

| Week | Deliverable (thin end-to-end slice first, then depth) | Exit check |
|---|---|---|
| **1** | Repo, CDM, validator, PPTX + DOCX native extractors, PDF OCR path, deterministic + label-anchored recognizers, text tokenizer, gate state machine with rules G0–G7 stubbed, CLI | PPTX sample goes end-to-end to `VALIDATED_SAFE`. Scanned PDF with OCR disabled ends `BLOCKED` |
| **2** | NER + presplit + context rules + registry/propagation + allowlist + merge; DOCX/PPTX/PDF writers; image OCR in DOCX; verification V1–V6; vault; FastAPI | All three samples processed. Integration tests pass. Leak check green |
| **3** | Streamlit upload/status/review/report; review loop; mock AI handoff; gold annotations; evaluation harness + report; architecture diagrams finalised; demo script; stakeholder deck | Live demo dry-run on the real files. `eval/report.md` with measured numbers |

**Cut line if behind schedule:** drop FR-17 UI editing (YAML only), FR-18, native-PDF writer (samples have no native PDF), and the invisible text layer in scanned-PDF output. Never cut FR-09, FR-10, FR-11 or FR-15.

**Submission deliverables (from the brief):** stakeholder deck (.pptx, 10–15 min) covering the solution blueprint (functional diagram), system architecture, extraction logic, reliable outcomes, and a live walkthrough. Plus this documentation set, `REFERENCE_GAP_ANALYSIS.md`, tests and the evaluation report. Per the brief and case-file notices: **no public repository and no published presentation**. Case files stay confidential.

## 11. Future enhancements

1. **Client-identity policy pack**: detect and mask logos and client/tenant names in screenshots (one sample screenshot shows the original organisation beneath an overlaid label).
2. **Learning from review**: reviewer rejections and additions feed per-client allowlists and threshold recalibration.
3. **Layout-aware OCR model** (e.g., a document-layout detector) to find figure and table regions in scans more reliably than Tesseract blocks.
4. Quasi-identifier generalisation (role titles → role families) for high-sensitivity uses.
5. XLSX and legacy formats via an isolated converter.
6. Enterprise controls: SSO, per-tenant keys, KMS-backed vault, encrypted object storage.

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OCR can't read some image text (observed) | High | Missed PII | Region masking + review; never treat as clean |
| NER misses unusual or OCR-damaged names | Medium | Leak | Context rules, propagation, fuzzy OCR matching, review, residual scan |
| Over-redaction destroys context | Medium | AI output poor; CRS < 0.8 | Taxonomy limited to personal data, allowlist, CRS metric |
| Small evaluation set overstates reliability | High | False confidence | Intervals, synthetic edge cases, explicit limitations |
| OCR time makes the demo slow | High | Demo friction | Pre-warmed cache, show progress, demo PPTX/DOCX live and PDF from cache plus one live page |
| Gold annotation biased by system output | Medium | Inflated recall | Annotate before viewing output; second-annotator pass; count post-hoc additions |
| Scope creep into Smart-Redact features (logo detection, security insight generation) | Medium | Missed core | PRD non-goals; cut line |

## 13. Open questions for the stakeholder (Cadence / Optiv)

1. Are **person-attributable corporate emails** and role mailboxes (e.g., a board-chair mailbox) PII under Cadence policy? *(Assumed yes.)*
2. Should **role titles** be kept for AI context, or generalised? *(Assumed keep; quasi-identifier risk noted.)*
3. Are **external contacts** (vendor staff, assessors, customers, relatives) in scope? *(Assumed yes: the PDF's definition of personal data covers any identifiable natural person.)*
4. Is the corporate **headquarters address** business information? *(Assumed yes, kept.)*
5. Is masking an illegible screenshot acceptable context loss, or should such documents be blocked outright? *(Default: mask + review.)*
6. Should pseudonym tokens be stable **across batches** (e.g., per quarter) or only within a batch? *(Default: within batch.)*
