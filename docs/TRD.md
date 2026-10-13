# ClearGate: Technical Requirements Document (TRD)

| Field | Value |
|---|---|
| Product | ClearGate, privacy gate for AI document analysis |
| Case study | Optiv PS-2: Text Analysis and PII Detection (Cadence Financial Group) |
| Version | 0.1 (design baseline, pre-implementation) |
| Date | 13 Oct 2026 |
| Related | [PRD](PRD.md) (what and why) · [Architecture](Architecture.md) (decisions ADR-01…13) · [README](../README.md) |

Requirement keywords: **MUST** (needed for the PS-2 demo), **SHOULD** (planned for v1 if time allows), **MAY** (stretch). Every requirement has an ID (`TR-xx`) so tests can cite it.

---

## 1. System context

```
 Cadence employee ──upload──> ClearGate API ──(SafeHandle only)──> Document-analysis AI agent
                                  │                                   (mock by default)
 Privacy reviewer <──review UI────┘
 Optiv evaluator  <──reports · eval harness
```

- **Trust boundary:** everything inside ClearGate may see raw content. Nothing outside it may, except the reviewer (authenticated, in session).
- **Network:** no outbound calls at runtime by default (TR-SEC-01). spaCy models and Tesseract language data are installed at build time.

## 2. Supported inputs (v1)

| ID | Format | Detection by | Status |
|---|---|---|---|
| TR-IN-01 | PDF (native and scanned) | magic `%PDF-` + PyMuPDF open | MUST |
| TR-IN-02 | DOCX | ZIP + `[Content_Types].xml` declares `wordprocessingml.document.main` | MUST |
| TR-IN-03 | PPTX | ZIP + `presentationml.presentation.main` | MUST |
| TR-IN-04 | PNG, JPEG, TIFF | magic bytes + Pillow verify | SHOULD |
| TR-IN-05 | XLSX | ZIP + `spreadsheetml.sheet.main` | MAY (not in PS-2 sample set) |
| TR-IN-06 | `.doc`, `.ppt`, `.docm`, `.pptm`, encrypted PDF/OOXML | - | MUST **reject** with a clear message |

Validation limits (configurable): file ≤ 50 MB; PDF ≤ 300 pages; OOXML total uncompressed ≤ 250 MB and compression ratio ≤ 100 (zip-bomb guard); ≤ 20 files per batch; image ≤ 80 MP. The extension must agree with the detected type.

---

## 3. Module layout and interfaces

```
cleargate/
  core/        models.py (Pydantic schemas) · states.py · config.py · errors.py · logging.py
  ingest/      validator.py
  extract/     base.py · pdf.py · docx.py · pptx.py · image.py · ocr.py · metadata.py
  detect/      engine.py · recognizers/{deterministic,label_anchored,context,phone}.py
               ner.py · presplit.py · registry.py · propagate.py · allowlist.py · merge.py
  redact/      tokens.py · vault.py · text_renderer.py · writers/{pdf,docx,pptx,image}.py
  verify/      reextract.py · leak.py · residual.py · coverage.py · structure.py
  gate/        machine.py · rules.py · handle.py · handoff.py
  report/      builder.py · templates/
  api/         main.py · routes/*.py · auth.py
  ui/          app.py (Streamlit)
  pipeline.py  orchestrator
eval/          gold/*.jsonl · fixtures/ · run_eval.py · metrics.py
tests/         unit/ · integration/ · security/
config/        policy.default.yaml
```

Stage interfaces (Python `Protocol`s). Each stage is pure with respect to its inputs, so stages can be tested in isolation:

```python
class Extractor(Protocol):
    def supports(self, fmt: FileFormat) -> bool: ...
    def extract(
        self, path: Path, ctx: JobContext
    ) -> ExtractionResult: ...  # Document + Segment[] + coverage


class Recognizer(Protocol):
    name: str
    layer: Literal["L1", "L2", "L3", "L4", "L5"]

    def analyze(self, seg: Segment, doc_ctx: DocContext) -> list[RawFinding]: ...


class Writer(Protocol):
    def apply(
        self, src: Path, doc: Document, actions: list[RedactionAction], out: Path
    ) -> WriteResult: ...


class Verifier(Protocol):
    def verify(
        self, out_path: Path, doc: Document, findings: list[Finding], ctx: JobContext
    ) -> VerificationReport: ...
```

---

## 4. Data model (Canonical Document Model + findings)

All models are Pydantic v2. Fields marked [RAW] hold raw content. They live **only** in memory during a job and in the encrypted vault, never in `meta.db`, logs or reports.

```python
class Locator(BaseModel):
    part: str  # "page" | "word/document.xml" | "ppt/slides/slide3.xml" | "docProps/core.xml" | "word/media/image10.png"
    page: int | None = None  # 1-based (PDF)
    slide: int | None = None  # 1-based (PPTX)
    shape_id: int | None = None
    paragraph_index: int | None = None
    run_range: tuple[int, int] | None = None
    table: int | None = None
    row: int | None = None
    col: int | None = None
    bbox: tuple[float, float, float, float] | None = (
        None  # page pts (native PDF) or px of the source raster (OCR)
    )
    image_ref: str | None = None  # media part or "page-raster"
    xpath: str | None = None  # OOXML element path for writers


class Segment(BaseModel):
    segment_id: str  # f"{doc_id}:{order_index}"
    kind: Literal[
        "heading",
        "paragraph",
        "list_item",
        "table_cell",
        "shape_text",
        "notes",
        "header",
        "footer",
        "textbox",
        "alt_text",
        "metadata",
        "ocr_line",
        "caption",
    ]
    text: str  # [RAW]
    order_index: int  # global reading order
    heading_level: int | None
    locator: Locator
    method: Literal["native", "ocr"]
    ocr_word_conf: list[float] | None  # aligned to whitespace tokens
    parent_id: str | None  # e.g. image segment → owning paragraph


class Document(BaseModel):
    doc_id: str
    filename: str
    sha256: str
    fmt: FileFormat
    size_bytes: int
    units: dict[
        str, int
    ]  # {"pages":35} / {"slides":9} / {"paragraphs":402,"tables":16,"images":35}
    segments: list[Segment]
    coverage: Coverage


class Coverage(BaseModel):
    parts_total: int
    parts_inspected: int
    parts_masked: int
    uninspected: list[Locator]  # MUST be empty, or masked, for SAFE


class Evidence(BaseModel):
    detector: str
    layer: str
    rule_id: str
    raw_score: float | None
    context_terms: list[str] = []


class Finding(BaseModel):
    finding_id: str
    segment_id: str
    start: int
    end: int
    entity_type: EntityType
    risk: Literal["HIGH", "MEDIUM", "LOW"]
    tier: Literal["DETERMINISTIC", "CORROBORATED", "SINGLE_SIGNAL", "LOW"]
    evidence: list[Evidence]
    format_invalid: bool = False  # label-anchored capture of malformed value
    value: str  # [RAW] (dropped before persistence)
    value_hmac: str  # HMAC-SHA256(vault_key, normalise(value))
    preview: (
        str  # masked, e.g. "Jo****ft", "***-**-4321" → never more than 2+2 chars or last 4 digits
    )
    person_key: str | None  # registry identity for PERSON-linked findings
    decision: Literal["auto_redact", "review", "suppressed", "discarded"]
    token: str | None  # "[PERSON_7]"


class RedactionAction(BaseModel):
    finding_ids: list[str]
    locator: Locator
    method: Literal["token_replace", "pixel_mask", "region_mask", "metadata_clear", "remove_part"]
    token: str | None
    applied: bool = False
    error_code: str | None = None
```

### 4.1 Entity types and default risk

| EntityType | Risk | Primary detectors | Token |
|---|---|---|---|
| `PERSON` | MEDIUM | L3 NER, L4 context, L5 registry | `[PERSON_n]` |
| `EMAIL_ADDRESS` | MEDIUM | L1 regex + TLD check | `[EMAIL_n]` |
| `PHONE_NUMBER` | MEDIUM | L1 phonenumbers, L2 label-anchored | `[PHONE_n]` |
| `EMPLOYEE_ID` (EMP/DIR/vendor-staff) | MEDIUM | L1 configurable patterns | `[EMPLOYEE_ID_n]` |
| `US_SSN` (incl. last-4 with context) | HIGH | L1 (Presidio-style invalidation), L2, L4 | `[SSN]` |
| `IN_PAN` | HIGH | L1 `[A-Z]{5}\d{4}[A-Z]` + holder-type char, OCR-tolerant in context | `[NATIONAL_ID]` |
| `PL_PESEL` (incl. masked `\d{6}x{5}`) | HIGH | L1 checksum, L2 | `[NATIONAL_ID]` |
| `PASSPORT` | HIGH | L2 / context-required L1 | `[PASSPORT]` |
| `TAX_ID` | HIGH | L2 (`TIN`, `tax identifier`) | `[TAX_ID]` |
| `DATE_OF_BIRTH` | HIGH | L2/L4 (`DOB`, `date of birth`, `born`) + date parser | `[DOB]` |
| `HOME_ADDRESS` | HIGH | L4 (`home address`, `home at`, `to your home at`) + US street/ZIP grammar | `[HOME_ADDRESS]` |
| `FINANCIAL_PARTIAL` (card/account ending) | HIGH | L4 (`ending \d{4}`, `last four digits`) | `[ACCOUNT_REF]` |
| `PAYMENT_CARD` | HIGH | L1 Luhn | `[CARD]` |
| `PHOTO` | HIGH | face detector on rasters | region mask |
| `UNREADABLE_IMAGE_REGION` | HIGH (pseudo) | OCR region confidence | region mask |

High-risk identifiers get **untyped-number** tokens (no `_n`) by default, because linking two SSNs across documents gives the AI nothing useful.

---

## 5. Extraction requirements

### 5.1 PDF (`extract/pdf.py`)
- **TR-EX-01** For each page, compute `native_chars` (PyMuPDF `get_text("rawdict")`) and `image_coverage` (union of image bboxes / page area).
- **TR-EX-02** Route a page to OCR if `native_chars < 25` **or** `image_coverage > 0.60`. Native text on such pages is kept too and merged (OCR lines that overlap native spans are dropped).
- **TR-EX-03** On native-text pages, every embedded image ≥ 120×120 px is OCR'd as a child segment with `image_ref`.
- **TR-EX-04** OCR: render at 300 DPI, `image_to_data` (`--oem 1 --psm 3`). Build `ocr_line` segments from `(block,par,line)` groups, with word boxes and confidences. Keep the block-level mean confidence for region analysis.
- **TR-EX-05** Unreadable-region detection: a Tesseract block or connected non-text region with area ≥ 2 % of the page and mean word conf < 70, **or** ≥ 40 % of its words below 60, becomes a `UNREADABLE_IMAGE_REGION` candidate.
- **TR-EX-06** Face detection (Haar frontal + profile) on every page raster and embedded image. Hits become `PHOTO` regions.
- **TR-EX-07** Metadata: Info dict (`Author`, `Creator`, `Producer`, `Title`, `Subject`, `Keywords`) and XMP become `metadata` segments.
- **TR-EX-08** OCR results are cached by `sha256(raster bytes)+dpi+tess_version`.

### 5.2 DOCX (`extract/docx.py`)
- **TR-EX-10** Walk `w:body` children **in order**: `w:p`, `w:tbl` (row/col, merged cells resolved via `gridSpan`/`vMerge`, so a merged cell is extracted once), `w:sdt` (content controls including TOC), `w:txbxContent` (inside `mc:AlternateContent`, de-duplicating the `Fallback` copy).
- **TR-EX-11** Also extract: headers/footers (all sections, first/even variants), footnotes, endnotes, comments, `wp:docPr/@descr` and `@title` (alt text), `docProps/core.xml` (`dc:creator`, `cp:lastModifiedBy`, `dc:title`, …), `docProps/app.xml` (`Company`, `Manager`), `docProps/custom.xml`.
- **TR-EX-12** Every `a:blip` image referenced from the body/headers is OCR'd (2× upscale if shorter side < 1000 px) as a child segment. EMF/WMF/SVG: SVG text nodes are extracted natively. EMF/WMF are rasterised with Pillow where possible, otherwise marked `uninspected` (→ gate rule G3).
- **TR-EX-13** Each paragraph segment keeps `heading_level` (from `Heading n` styles / outline level) and list membership.

### 5.3 PPTX (`extract/pptx.py`)
- **TR-EX-20** Iterate slides → shapes recursively (groups), in z-order. Text frames go paragraph by paragraph. Tables go cell by cell (`table`,`row`,`col`). Charts: series/category names. Notes slides.
- **TR-EX-21** Picture shapes: OCR + face detection. A picture whose `sha256` repeats on ≥ 50 % of slides (logo) is processed once and the result reused.
- **TR-EX-22** `docProps` as in TR-EX-11.

### 5.4 Images (`extract/image.py`)
- **TR-EX-30** EXIF/XMP metadata is extracted and always stripped on output. The whole image goes through the OCR + face path.

### 5.5 Coverage accounting
- **TR-EX-40** Each extractor registers every part it found (page, slide, image, XML part) in `Coverage`. A part is `inspected` only if text extraction succeeded and, for OCR parts, it is not entirely an unreadable region. Parts that fail are listed in `uninspected` with an error code.

---

## 6. Detection requirements

### 6.1 Pre-processing (`detect/presplit.py`)
- **TR-DT-01** Before NER, split segment text into **sub-spans** on ` / `, `;`, `|`, `·`, tabs, and line breaks inside table cells. Run NER per sub-span and map offsets back. (Driver: Architecture D8. A 4-name cell was returned as 1 span.)
- **TR-DT-02** Normalise OCR text for matching only (NFKC, dash unification, `ﬁ`→`fi`, smart quotes, collapse whitespace). Offsets are mapped back to the original string.

### 6.2 Layers
- **TR-DT-10 (L1)** Deterministic recognizers. Each has: regex, validator, `context_terms`, `risk`, unit tests (positives, negatives, OCR-damaged negatives). Validators:
  - SSN: Presidio rules (mismatched delimiters, all-same digit, zero groups, 000/666, sample numbers). **No** rejection of 9xx areas (the sample uses 900-series values; ITINs are personal data too).
  - PAN: `^[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]$`. Holder type `P` → PII. Other holder types → `discarded` with reason `business_pan`.
  - PESEL: weights `1,3,7,9,1,3,7,9,1,3` checksum. Masked form `\d{6}[xX*]{5}` is accepted when preceded by `PESEL` within 3 tokens.
  - Phone: `phonenumbers.PhoneNumberMatcher` (regions US, GB, IN, PL, FR, DE, SG, SE; leniency VALID).
  - Email: RFC-lite regex + TLD length ≥ 2. `.example` TLD accepted.
  - Employee IDs: config list, default `EMP-\d{5}`, `DIR-\d{4}`, `MER-[A-Z]{2}-\d{4}`, `EMP\.\d{5}` (OCR variant).
  - Card: 13–19 digits, Luhn, IIN prefix sanity.
- **TR-DT-11 (L2)** Label-anchored capture. Label lexicon → capture the next value token group (up to the first `,`, `)`, `;` or 4 tokens). Captured spans are DETERMINISTIC with `format_invalid` set when the L1 validator fails. Labels include `SSN`, `PAN`, `PESEL`, `Passport`, `DOB`, `Date of birth`, `TIN`, `NI`, `Mobile`, `M` (only when followed by `+`), and table column headers with the same semantics (header text matched against the lexicon applies to every cell in the column).
- **TR-DT-12 (L2)** OCR-confusion tolerance, applied only to OCR segments and only within 3 tokens of a high-risk label: confusion map `{0↔O,1↔I↔l,5↔S,7↔T,8↔B,2↔Z}`, with up to 2 substitutions to reach a validator-passing value. If none passes, the label-anchored capture still applies.
- **TR-DT-13 (L3)** NER: Presidio `AnalyzerEngine` with `SpacyNlpEngine(en_core_web_lg)`, entities `PERSON`, `LOCATION`. LOCATION is used only as an address-grammar feature and never redacted by itself.
- **TR-DT-14 (L4)** Context rules:
  - column/field label → PERSON corroboration (`Name`, `Users`, `Member`, `Created by`, `Owner`, `Chair`, `Led by`, `Attested by`, `Challenged by`, `Author`, `Reviewer`, `Contact`, `Incident manager`, `Investigating officer`);
  - honorific: `\b(Mr|Ms|Mrs|Miss|Dr|Prof)\.?\s+[A-Z][\w'’-]+(\s+[A-Z][\w'’-]+)?`;
  - initials: `\b([A-Z]\.\s?){1,2}[A-Z][a-z]+(-[A-Z][a-z]+)?\b` (e.g., `R. J. Thornfield`), accepted when the surname is in the registry **or** the segment is a table header / role line;
  - partial financial: `(card|account)\s+ending\s+(\d{4})`, `last four digits[^()]{0,40}\((\d{4})\)`;
  - home address: trigger phrase + US street grammar `\d{1,6}\s+[A-Z][\w\s]+(Street|St|Avenue|Ave|Lane|Ln|Court|Ct|Crescent|Road|Rd|Drive|Dr)\b[^.]{0,60}\b[A-Z]{2}\s\d{5}`.
- **TR-DT-15 (L5)** Registry & propagation:
  1. Seed with PERSON findings of tier ≥ CORROBORATED and with reviewer-added spans.
  2. Canonical key: casefold, strip honorifics/middle initials, Unicode-normalise. Generate variants: `First Last`, `F. Last`, `F. M. Last`, `Last, F.`, `Hon. Last`, email local parts `f.last`, `flast`, `first.last` (hyphens removed: `ashbycroft`).
  3. Sweep all segments: exact case-insensitive variant match in native segments; `rapidfuzz.fuzz.ratio ≥ 90` on OCR segments (window = variant token length ± 1).
  4. Surname-only: only if the surname is unique in the registry, ≥ 5 characters, and not in the 50k common-English-word list. Tier SINGLE_SIGNAL.
  5. The batch registry is shared across documents in a batch, so the same person gets the same token everywhere.
- **TR-DT-16** Face detections and unreadable regions are emitted as region findings (no text span).

### 6.3 Merge, allowlist, tiering (`detect/merge.py`)
1. Group raw findings by segment and sort by `(start, -length)`.
2. **Overlap resolution:** if spans overlap, the union span is kept when the types are compatible (e.g., PERSON ⊂ HOME_ADDRESS line → keep both, the outer one wins for redaction). If the types conflict, priority is `HIGH-risk deterministic > MEDIUM deterministic > CORROBORATED > SINGLE_SIGNAL`. All evidence is retained on the surviving finding (traceability).
3. **Allowlist:** drop a finding only if *all* of its evidence is L3 NER **and** its normalised span equals an allowlist term **and** its `person_key` is not in the registry. Store `decision="suppressed"` with reason `allowlist:<term>`.
4. **Tiering:** DETERMINISTIC if any L1-valid or L2 evidence; CORROBORATED if ≥ 2 independent detectors (NER + context, NER + registry, context + registry); else SINGLE_SIGNAL; then LOW if calibrated score < `review_threshold`.
5. **Decision:** DETERMINISTIC/CORROBORATED → `auto_redact`. SINGLE_SIGNAL → `auto_redact` + `review` flag when risk ≥ MEDIUM. LOW → `discarded` (counted).
6. Property tests (hypothesis): merge is idempotent, order-independent, and never drops a HIGH-risk deterministic span.

### 6.4 Calibration
- **TR-DT-30** `eval/calibrate.py` fits per-tier thresholds on the gold set to maximise recall subject to precision ≥ target. The thresholds are written into the policy file and the policy hash changes. Thresholds are never hand-tuned on the test fold. With 3 documents this is a k-fold over segments, and the README reports it as weak evidence.

---

## 7. Redaction requirements

- **TR-RD-01 Tokens** come from `redact/tokens.py`: `lookup_or_create(batch_id, entity_type, value_hmac, person_key)`. The counter is per `(batch, type)`. PERSON uses `person_key` so that `P. Halvorsen`, `Priya Halvorsen` and the email owner share the same person token (the email keeps its own `[EMAIL_n]`).
- **TR-RD-02 Vault**: `vault.db` table `(batch_id, token, entity_type, value_hmac, value_ct BLOB, created_at)`. `value_ct` = Fernet(key) ciphertext. The key comes from `CLEARGATE_VAULT_KEY` (32-byte urlsafe base64) and the service refuses to start without it. Batch vault rows are deleted with the batch.
- **TR-RD-10 DOCX/PPTX writer**: map `(segment, start, end)` → runs. If a span crosses runs, write the token into the first run and remove the covered text from the rest, keeping the formatting of the first run. Replace images that have findings with redacted rasters at the same pixel size (same `rId`). Clear `docProps` person fields (`creator`, `lastModifiedBy` → `"[REDACTED]"`), and replace alt text that contains PII with the sanitized text. Remove `docProps/thumbnail.jpeg` (it may render page 1).
- **TR-RD-11** OOXML integrity: the output must open with python-docx/python-pptx **and** pass a zip/XML well-formedness check. The `[Content_Types].xml` part set must be unchanged except for the removed thumbnail.
- **TR-RD-20 Scanned PDF writer**: for each page take the cached 300 DPI raster, fill black rectangles over word boxes (+3 px padding, horizontally adjacent boxes of the same finding merged) and over region masks, then add a new PDF page with the same mediabox and the raster as the only content (JPEG q=85 or PNG for low-colour pages). **MAY** add an invisible text layer containing **sanitized** text so the output stays searchable. Info/XMP cleared, `Producer` = `ClearGate`.
- **TR-RD-21 Native PDF writer**: `page.add_redact_annot(rect, fill=(0,0,0))` per finding quad, `page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_IF_TOUCHED)`, then `doc.set_metadata({})`, `doc.del_xml_metadata()`, and save with `garbage=4, deflate=True, clean=True` so orphaned objects are dropped.
- **TR-RD-30 Sanitized text renderer**: walk segments in `order_index`, substituting tokens. Emit structural markers (`[Page n]`, `[Slide n]`, `#`/`##` from `heading_level`, tables as pipe rows, `[Image: n words OCR'd, k redactions]`, `[Image region redacted: unreadable]`). This is the only artifact that may reach the AI.
- **TR-RD-40** Any action whose `applied=False` blocks the gate (rule G4).

---

## 8. Verification and gate

### 8.1 Verification (`verify/`)
| ID | Check | Method | Outcome on fail |
|---|---|---|---|
| V1 | Output reopens | Open with the format library **and** a second path (PDF: pdfplumber; OOXML: zip + lxml parse of every XML part) | `FAILED` |
| V2 | Known-value leak | Build a needle set from all redacted findings: value + normalisations (casefold, whitespace-collapsed, digits-only for numeric types, email local part, registry name variants). Search the **re-extracted** output text: all XML parts' text nodes (OOXML), PyMuPDF text **and** OCR of output rasters (PDF), and the sanitized text file. Aho-Corasick over normalised haystacks. | `BLOCKED` |
| V3 | Residual scan | Run `detect.engine` on the re-extracted output with the `verify` profile: allowlist off, propagation on, `review_threshold × 0.5`, ignoring ClearGate tokens. | New DETERMINISTIC → `BLOCKED`; other → `REVIEW_REQUIRED` |
| V4 | Coverage | `Coverage.uninspected` minus masked parts must be empty. Page/slide/image counts are equal to the source. | `BLOCKED` |
| V5 | Overlap/consistency | No two tokens overlap. Each token in the output maps to a vault entry of the same type. Each person token is used consistently. | `BLOCKED` (bug guard) |
| V6 | Structure | SRS and CRS (§9) | SRS < 0.80 → `REVIEW_REQUIRED` |

### 8.2 Gate rules (`gate/rules.py`), evaluated in order, first match wins
| Rule | Condition | Resulting state |
|---|---|---|
| G0 | Any unhandled exception in PROCESSING, V1 failed, or vault unavailable | `FAILED` |
| G1 | V2 found ≥ 1 needle | `BLOCKED` |
| G2 | V3 found ≥ 1 new DETERMINISTIC finding | `BLOCKED` |
| G3 | V4 failed (an uninspected, unmasked part exists) | `BLOCKED` |
| G4 | ≥ 1 redaction action not applied | `BLOCKED` |
| G5 | V5 failed | `BLOCKED` |
| G6 | Any open review item (SINGLE_SIGNAL ≥ MEDIUM, masked unreadable/photo region when `unreadable_policy=mask_and_review`, V3 non-deterministic hits, SRS < 0.80) | `REVIEW_REQUIRED` |
| G7 | None of the above | `VALIDATED_SAFE` |

- **TR-GT-01** Allowed transitions (anything else raises `IllegalTransition`):
  `RECEIVED→PROCESSING`, `RECEIVED→FAILED`, `PROCESSING→{FAILED,BLOCKED,REVIEW_REQUIRED,VALIDATED_SAFE}`, `REVIEW_REQUIRED→PROCESSING`, `REVIEW_REQUIRED→BLOCKED`.
- **TR-GT-02** `jobs.state` has a `CHECK` constraint on these five values plus `RECEIVED`. An `AFTER UPDATE` trigger raises unless a `state_history` row with the matching `(job_id, to_state)` was inserted in the same transaction.
- **TR-GT-03 SafeHandle** = `{job_id, sanitized_sha256, policy_hash, verification_sha256, issued_at}` + `HMAC-SHA256(gate_key, canonical_json)`. It is issued only on transition into `VALIDATED_SAFE`.
- **TR-GT-04 Handoff** verifies the HMAC, re-hashes the sanitized text on disk, checks that the job is still `VALIDATED_SAFE` with the same `policy_hash`, and only then calls the AI client with the sanitized text. The AI client interface takes a `SafeHandle`, never a path or raw string.
- **TR-GT-05** The AI client defaults to `MockAgent` (local extractive summary + entity-token counts). `llm.enabled=true` requires `llm.provider`, `llm.endpoint` and an explicit `llm.approved_by` value in config. The outbound payload is sanitized text only.

### 8.3 Review (`api/routes/review.py`)
- **TR-RV-01** A review item contains: finding/region id, masked preview, the full segment text with highlight (served only to the `reviewer` role and fetched from the vault on demand), type, risk, tier, evidence list, locator, proposed token, and a page/slide thumbnail **with the proposed masks applied**.
- **TR-RV-02** Actions: `confirm`, `reject{justification}`, `retype{entity_type}`, `add{segment_id,start,end,entity_type}` / `add_region{page,bbox}`, `reject_document{reason}`. `reject` is forbidden on HIGH-risk DETERMINISTIC findings.
- **TR-RV-03** Submitting decisions runs `REVIEW_REQUIRED→PROCESSING`, re-runs §7 (redaction) and §8.1 (verification) with the overrides, and the gate decides again. Detection is **not** re-run, except propagation seeded by `add` actions.
- **TR-RV-04** Each decision is logged in `review_log` with reviewer id, timestamp, finding id, action and justification. No raw values are stored there.

---

## 9. Metrics (definitions used by reports and evaluation)

- **Leak rate** = gold PII instances whose value (or normalised variant) appears in the sanitized output ÷ gold PII instances. **Target 0.**
- **Precision / recall / F1**, per entity type and overall, computed on (a) strict span match and (b) overlap ≥ 50 % with the same type. Region findings are matched by IoU ≥ 0.5.
- **False positives on business entities** = suppressed-or-should-be-suppressed allowlist terms that were redacted.
- **Extraction completeness** = inspected parts ÷ total parts, plus for OCR pages the character error rate (CER) on a hand-transcribed sample of ≥ 5 pages.
- **Structure Retention Score (SRS)** = Σ matched units ÷ Σ source units, over units = pages/slides + headings (with level) + paragraphs + list items + tables + table cells + images. A unit is *matched* if it exists at the same position in the output CDM (re-extracted). PS-2 asks for ≥ 0.80.
- **Context Retention Score (CRS)** = |LCS(non-PII tokens of source, tokens of sanitized text)| ÷ |non-PII tokens of source|. It measures how much surrounding text (the brief's "preceding and succeeding context") survives. Target ≥ 0.80. Gold PII tokens are excluded from the denominator.
- **Review load** = review items ÷ findings.
- **Timing** = wall time per page/slide per stage, p50/p95, recorded with CPU count.
- **Error rate** = jobs ending in `FAILED` ÷ jobs.

Gold annotation format (`eval/gold/<file>.jsonl`, one finding per line, **kept out of any public repo**):
```json
{"doc":"Cadence_TPRM_Training.docx","locator":{"part":"word/document.xml","table":2,"row":1,"col":3},"text_sha256":"…","start":0,"end":16,"type":"PERSON","note":"cell list item 1"}
```
Annotation protocol: annotator A labels from scratch. Annotator B reviews A's labels **and** the system's output, and records disagreements. Report the inter-annotator agreement and the number of gold items added after seeing system output (anchoring bias).

---

## 10. API (FastAPI, `/api/v1`)

| Method & path | Role | Purpose | Notes |
|---|---|---|---|
| `POST /batches` | submitter | Multipart `files[]`, optional `policy` name → `{batch_id, jobs:[{job_id, filename, state}]}` | Validation is synchronous. Processing runs in the background |
| `GET /jobs/{id}` | submitter | State, progress `{stage, done, total}`, counts by type, timings, warnings | No raw values |
| `GET /jobs/{id}/findings` | reviewer | List with masked previews, locators, tiers, evidence | `?include_text=true` needs the reviewer role |
| `GET /jobs/{id}/review` | reviewer | Open review items + thumbnails | |
| `POST /jobs/{id}/review` | reviewer | Decisions (TR-RV-02) | 409 unless state is `REVIEW_REQUIRED` |
| `GET /jobs/{id}/report?format=json\|md` | submitter | Processing report | Safe in every state |
| `GET /jobs/{id}/artifacts/sanitized.txt` | submitter | Sanitized text | **403 unless `VALIDATED_SAFE`** |
| `GET /jobs/{id}/artifacts/redacted.{ext}` | submitter | Redacted file | **403 unless `VALIDATED_SAFE`** |
| `POST /jobs/{id}/handoff` | submitter | Run the AI client on the SafeHandle | 409 unless `VALIDATED_SAFE` |
| `GET /health` | - | Liveness, model loaded, Tesseract version, vault key present | |

Errors use one schema: `{"error":{"code":"OCR_TIMEOUT","message":"Page 18 could not be OCR'd within 120 s","job_id":"…"}}`. Messages never quote document content.

---

## 11. Configuration (`config/policy.default.yaml`)

```yaml
policy_name: cadence-default
entities:
  enabled: [PERSON, EMAIL_ADDRESS, PHONE_NUMBER, EMPLOYEE_ID, US_SSN, IN_PAN, PL_PESEL,
            PASSPORT, TAX_ID, DATE_OF_BIRTH, HOME_ADDRESS, FINANCIAL_PARTIAL, PAYMENT_CARD, PHOTO]
  employee_id_patterns: ['EMP-\d{5}', 'DIR-\d{4}', 'MER-[A-Z]{2}-\d{4}']
keep:
  organisations: true
  role_titles: true            # quasi-identifier risk, see README limitations
  corporate_addresses: true
  non_dob_dates: true
allowlist:
  organisations: [Cadence, Cadence Financial Group, Optiv, Halloran & Pike LLP, Northwind Analytics, Meridian Staffing, Veritrace Screening Services]
  products: [OneTrust, Ironclad, Torii]
  auto_learn_orgs: true        # corporate suffix / vendor context
detection:
  ner_model: en_core_web_lg
  review_threshold: 0.40       # calibrated; see TR-DT-30
  surname_only_propagation: true
  fuzzy_ocr_ratio: 90
ocr:
  dpi: 300
  min_native_chars: 25
  word_conf_floor: 60
  unreadable_region: {min_area_ratio: 0.02, max_mean_conf: 70}
  unreadable_policy: mask_and_review     # mask_and_review | mask_only | block
  timeout_s_per_page: 120
redaction:
  token_style: typed_numbered            # typed_numbered | typed | fixed
  pdf_padding_px: 3
verification:
  srs_min: 0.80
  verify_ocr_dpi: 300                     # candidate optimisation: 200 (to be measured)
retention:
  job_ttl_hours: 24
llm:
  enabled: false
```

The policy file is canonicalised and hashed (`policy_hash`). Every job and report records it.

---

## 12. Security requirements

| ID | Requirement |
|---|---|
| TR-SEC-01 | No outbound network calls at runtime unless `llm.enabled=true`. A CI test runs the pipeline with outbound sockets blocked (`pytest-socket`). |
| TR-SEC-02 | Raw values exist only in process memory and in `vault.db` (encrypted). `meta.db`, logs and reports contain types, counts, locators, HMACs and masked previews only. |
| TR-SEC-03 | `PiiSafeFilter` on all loggers: rejects records whose message contains any needle from active jobs (defence in depth) and strips exception `args`. Test: run the samples, then grep logs for the gold values. Zero hits required. |
| TR-SEC-04 | Job directories are `0700`, owned by the service user. Uploads are written with `O_EXCL`. Filenames are sanitised (no path traversal) and stored as `original.<ext>`. |
| TR-SEC-05 | Artifact and handoff endpoints enforce state server-side (403/409). Reviewer-only endpoints need the reviewer token. |
| TR-SEC-06 | TTL sweeper deletes job directories and vault rows. A `DELETE /batches/{id}` endpoint (SHOULD) does the same on demand. |
| TR-SEC-07 | Parsing hardening: `defusedxml`-style parser settings (no external entities, no DTD), zip-bomb limits (§2), PDF page and object limits, OCR timeout per page, worker memory limit (`RLIMIT_AS`). |
| TR-SEC-08 | Outputs never include original image XObjects or OOXML thumbnails. |
| TR-SEC-09 | Documented prototype limits: static tokens, single tenant, SQLite unencrypted metadata (holds no raw PII), no encryption at rest for the original upload beyond OS permissions. |

---

## 13. Performance and capacity

Baseline measured on the profiling container (2 vCPU): Tesseract OCR of the 35-page scanned PDF at 300 DPI took **491 s wall** with 2 processes (~14 s/page wall).

| ID | Target (v1, 2 vCPU reference) |
|---|---|
| TR-PF-01 | DOCX/PPTX without images: ≤ 15 s end-to-end |
| TR-PF-02 | DOCX with ~30 screenshots: ≤ 3 min (OCR-bound) |
| TR-PF-03 | Scanned PDF: ≤ 20 s/page wall including detection + redaction. Verification OCR is reported separately; the 200 vs 300 DPI trade-off is to be measured |
| TR-PF-04 | UI shows per-page progress at least every 5 s |
| TR-PF-05 | spaCy model loaded once per worker process (warm pool) |

Throughput scales roughly linearly with worker processes for OCR. Not yet measured. To be confirmed in the evaluation report.

---

## 14. Test plan

| Level | Scope | Examples |
|---|---|---|
| Unit | Each recognizer | Valid/invalid SSN, PAN holder types, PESEL checksum, masked PESEL, OCR-damaged PAN in label context, `+1 (555) 01NN` with `M` label, honorific + hyphenated surname, `/`-split names |
| Unit | Merge & allowlist | Allowlist suppresses an NER-only `Torii` but never an email; overlap priority; idempotence (hypothesis) |
| Unit | Gate | Every illegal transition raises. DB trigger blocks direct `UPDATE`. SafeHandle tamper → handoff refused |
| Unit | Writers | Span crossing 3 runs keeps first-run formatting. Image swap keeps the `rId`. `docProps` scrubbed |
| Integration | Each PS-2 sample end-to-end | No gold value in any output part. Page/slide counts equal. Report generated. State is one of `VALIDATED_SAFE`/`REVIEW_REQUIRED` (expected `REVIEW_REQUIRED` for the PDF because of Fig. 3) |
| Fault injection | Fail-closed | OCR disabled → scanned PDF `BLOCKED`. Corrupt image part → `BLOCKED` or masked+review. Writer forced to skip a finding → `BLOCKED`. Verification exception → `FAILED`. Encrypted PDF → `FAILED` |
| Security | Leakage | Log grep for gold values. Socket-blocked run. Path-traversal filename. Zip bomb. XML external entity |
| Evaluation | Metrics | `python -m eval.run_eval` produces the metrics in §9 as `eval/report.md` |

CI gate: unit + integration + security suites must pass. Evaluation runs on demand (it is slow because of OCR).

---

## 15. Dependencies (pinned at implementation start; versions checked on PyPI 13 Oct 2026)

| Package | Version | Purpose |
|---|---|---|
| fastapi / uvicorn | 0.14x / 0.53 | API |
| pydantic | 2.13 | Schemas |
| streamlit | latest 1.x at start | UI |
| pymupdf | 1.28.2 | PDF extract/render/redact |
| pdfplumber | 0.11 | Secondary PDF re-extraction in V1 |
| python-docx / python-pptx / lxml | 1.2.0 / 1.0.2 / 5.x | OOXML |
| pytesseract + Tesseract | 0.3.13 + 5.3.4 (`eng`) | OCR |
| presidio-analyzer | 2.2.364 | Recognizer framework |
| spacy + en_core_web_lg | 3.8.16 + 3.8.0 | NER |
| phonenumbers | 9.0.x | Phone validation |
| rapidfuzz | 3.x | Fuzzy propagation |
| opencv-python-headless | 4.x | Face detection |
| pyahocorasick | 2.x | Leak check |
| cryptography | 4x | Fernet/HMAC |
| pillow | 12.x | Rasters |
| pytest, hypothesis, pytest-socket | - | Tests |

System: Tesseract 5 with `eng` traineddata. LibreOffice is optional (legacy-format conversion, stretch).
