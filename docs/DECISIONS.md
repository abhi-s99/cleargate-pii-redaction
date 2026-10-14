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

### ADR-20: `core/db.py` and the single-use transition ticket
- **Context:** TRD 3 has no module for `meta.db`. TR-GT-02 asks for a trigger that raises
  "unless a `state_history` row with the matching `(job_id, to_state)` was inserted in the
  same transaction", but SQLite exposes no transaction id, so "same transaction" cannot be
  tested directly.
- **Decision:** Add `cleargate/core/db.py` (`MetaStore`, schema, migrations). The gate writes
  a row into `transition_tickets` that names the job, both states and the new history row.
  The `AFTER UPDATE OF state` trigger requires that ticket, requires it to point at the
  newest history row for the job with matching states, and deletes it. Because the ticket
  is consumed by the update and the gate writes history, ticket and update in one
  `BEGIN IMMEDIATE` transaction, a history row from an earlier transaction can never
  authorise a later update. Extra guards in the same schema: `allowed_transitions` (a frozen
  copy of TR-GT-01 checked by the trigger), jobs only insertable in `RECEIVED`,
  `VALIDATED_SAFE` needs a `safe_handles` row, immutable `job_id`/`policy_hash`/handles,
  append-only history (deletable only after its job is gone, for TR-SEC-06).
- **Alternatives:** a `consumed` flag on history rows (needs updates to an append-only
  table); a per-connection temp table (connection-scoped, not transaction-scoped).
- **Consequences:** Raw SQL with full write access can still forge every row; SQLite is not
  the security boundary. The SafeHandle HMAC is, and a test shows a fully forged SAFE row
  is refused by `verify_against_store` (`mac_mismatch`).

### ADR-21: How the gate rules read inputs the TRD leaves open
- **Context:** TRD 8.2 names the rules but not every input combination.
- **Decision:**
  - No verification report at all is a **G0** failure (`VERIFICATION_MISSING`): unverified
    is not safe.
  - If minting the SafeHandle fails after G7 (sanitized file missing, bad key), the job ends
    **G0** `FAILED` with `HANDLE_MINT_FAILED`.
  - Masked unreadable/photo regions: an open review item (**G6**) under `mask_and_review`,
    an uncovered part (**G3**) under `block`, neither under `mask_only` (Architecture 6).
  - An uninspected part passes G3 only if its locator is listed in `masked_parts`.
  - SRS not measured is a **G6** review item (`V6_SRS_NOT_MEASURED`), not a pass. SRS equal
    to `srs_min` passes (the TRD says "below 0.80" triggers review).
  - Every rule reports all of its reasons; the first rule with any reason decides.
- **Consequences:** Each interpretation has a table-driven test in `test_gate_rules.py`.

### ADR-22: Only `decide()` can enter VALIDATED_SAFE
- **Context:** ADR-09 describes a single `gate.transition(job, to_state, reason)`. A first
  implementation accepted a caller-supplied `SafeHandle` for the SAFE edge. The Phase 1
  hypothesis state machine showed that a caller could pass a handle signed with the wrong
  key, because `transition` has no gate key to check it with.
- **Decision:** One internal function `_apply` performs every state change. The public
  `transition` refuses `VALIDATED_SAFE` unconditionally. `decide` evaluates G0..G7 and, on
  G7, mints the handle itself with the gate key and calls `_apply`. Rule ids and reasons
  must be identifier-like strings (no spaces), so history cannot hold content.
- **Consequences:** No code path outside `decide` can produce a SAFE job. A mutation test
  that removes the public refusal is caught by the `_apply` handle requirement (defence in
  depth), so SAFE stays unreachable either way.

### ADR-24: A verification check that did not run counts as failed
- **Context:** Until Phase 7 the verifier is a stub that runs only V1 (reopen) and V4
  (coverage). Once Phase 3 makes extraction real, every part is inspected; a stub that
  reports `leak_hits=0` because no leak check ran would let a document full of PII reach
  `VALIDATED_SAFE`.
- **Decision:** `VerificationReport.checks_run` lists the checks that executed; it defaults
  to empty. A missing V1 is G0 (`V1_NOT_RUN`); a missing V2..V5 is G3 (`Vn_NOT_RUN`, an
  uninspected verification dimension, so the job is BLOCKED); a missing V6 is G6.
- **Alternatives:** make missing checks G0 (would make every stub run FAILED instead of the
  brief's expected BLOCKED-by-G3, and hide the real coverage reason); trust defaults (fails
  open).
- **Consequences:** Partial verifiers are safe to ship. Table and property tests cover each
  missing check.

### ADR-23: CDM and module additions for coverage codes, storage and CLI
- **Context:** TR-EX-40 wants an error code for every uninspected part, but TRD 4 defines
  `Coverage.uninspected` as a plain `list[Locator]`. TRD 3 has no module for upload storage
  or for the CLI the brief asks for in Phase 2.
- **Decision:** Keep `Coverage.uninspected` (the gate's input) unchanged and add
  `Coverage.issues: list[PartIssue(locator, code)]`, filled by `Coverage.register(...)`, one
  entry per uninspected part. Add `cleargate/ingest/storage.py` (job dirs, uploads) and
  `cleargate/cli.py` (Typer, `cleargate` console script).
- **Consequences:** Reports can say *why* a part was not inspected; the gate logic is
  untouched.

### ADR-25: Owner-only job directories on Windows; display filenames are kept
- **Context:** TR-SEC-04 asks for `0700` job directories. On Windows `chmod` only toggles the
  read-only flag. Separately, the uploaded display name is stored in `jobs.filename` and
  could contain a person's name (Phase 1 open question).
- **Decision:** On Windows, `secure_dir` removes inherited ACEs and grants full control to
  the current user only (`icacls /inheritance:r /grant:r`); files created inside inherit
  that single ACE (checked by a test). On POSIX it sets `0700`. The display name is kept
  (sanitised: basename only, control characters removed, at most 120 characters) because
  FR-13 reports must name the file; it is never used as a path (uploads are stored as
  `original.<ext>`), and it is listed as a known limitation.
- **Alternatives:** hashing the display name (loses the FR-13 file name).
- **Consequences:** `RLIMIT_AS` (TR-SEC-07) remains POSIX-only; the Phase 11 Docker image
  provides it. A filename that is itself PII is a documented residual risk.

### ADR-26: Extraction coverage beyond the TRD part list; encrypted OCR cache; regions in the CDM
- **Context:** Implementing TRD 5 showed places where personal data lives that the TRD part
  lists do not name: person names in XML *attributes* (`w:ins/@w:author`, comment authors and
  initials, `w15:person`, PowerPoint `cmAuthor/@name`), tracked deletions (`w:delText`) and
  field codes (`w:instrText`, e.g. `mailto:`) that stay in the file, external relationship
  targets in `.rels` parts, PDF annotations with author titles, link URIs, outline titles,
  form fields and embedded files, and a `[trash]` remnant part in the sample DOCX. Separately,
  the TR-EX-08 OCR cache would hold document text on disk in clear, and TRD 4 has no place
  for face and unreadable regions.
- **Decision:** Extract all of the above as segments. Run a generic sweep over every package
  part a structured walker did not handle: XML parts are text-swept, images are analysed,
  fonts count as inspected, anything else is uninspected (`EMBEDDED_OBJECT`), so nothing in
  a package goes unaccounted for. Encrypt OCR cache entries at rest with the vault key
  (Fernet); without a key, cache in memory only. The cache key adds the Tesseract config and
  a parser version to TR-EX-08's `sha256(raster) + dpi + tesseract version`, because entries
  store derived block statistics (a stale entry hid a fix during development). Add
  `Region(kind, locator, area_ratio, mean_conf, word_count)` and `Document.regions`, plus
  `Document.extractors` (name -> version).
- **Consequences:** More coverage blocks: `printerSettings*.bin` in PPTX packages and the DOCX
  `[trash]` part are uninspected until the Phase 6 writer removes them. Without a vault key,
  OCR is never cached on disk.

### ADR-27: Face and unreadable-region detection on the real samples
- **Context:** On the real PDF, the TR-EX-06 Haar cascades found no face on p.9 (Fig. 3) at
  any scale or sensitivity setting: the face is about 13 x 17 px at 150 DPI. The TR-EX-05 block
  rule did not flag Fig. 3 either, because Tesseract recognised no words in it at all. The
  TRD also names "connected non-text regions", which the first implementation omitted. The
  block rule flagged the clean RACI table on p.32, because single-letter cells score low
  (Architecture D2).
- **Decision:** Face detection is the union of OpenCV YuNet (`FaceDetectorYN`, bundled
  232 KB MIT-licensed model from OpenCV Zoo, run offline) and the TR-EX-06 Haar cascades
  (frontal, profile, mirrored profile), merged. Implement the connected non-text region rule
  for scanned PDF pages: blank recognised word boxes, join remaining ink, and flag components
  of at least `min_area_ratio` of the page whose words (2+ characters) are absent, below
  `max_mean_conf`, or at least 40 % below `word_conf_floor`. Embedded images (screenshots)
  keep the block rule only, because their coloured UI panels would flood the region rule. Block
  statistics ignore single-character words when the block has longer ones. No threshold was
  changed.
- **Alternatives:** keep Haar only (Fig. 3 face missed; criterion fails); lower Haar
  `minNeighbors` (false faces on text, still no hit on p.9); raise the 70 confidence threshold
  (forbidden: never weaken a threshold).
- **Also:** an embedded picture with visible ink, no recognised words and no face gets a
  whole-image unreadable region (mask and review), so a screenshot OCR cannot read at all
  is never treated as empty. On the sample DOCX this affects one EMF diagram.
- **Consequences:** On the real PDF, YuNet finds exactly one face (p.9, inside the Fig. 3
  region) and no false faces on the other 34 pages. Unreadable regions: p.9 (Fig. 3), p.18
  (Fig. 8, two regions) and five more small candidates (pp. 12, 14, 15, 19, 20) whose truth is
  unknown until gold labels exist; p.32 is no longer flagged. Region rules for embedded images
  are weaker than for pages (block rule plus the whole-image rule above).

### ADR-28: Detection details the TRD leaves open, and where it was tightened
- **Context:** Building TRD 6 on the synthetic fixtures and running it (counts only) on the
  real samples exposed gaps: Presidio's constant 0.85 score cannot separate weak from strong
  NER guesses before calibration exists (Phase 10); a value detected once was left in clear
  wherever detection missed it (V2 then blocked every sample); OCR reads names as
  `First M. Last` and splits values over lines; the model tags incident IDs as PERSON and
  tags only part of some names in `/`-separated cells.
- **Decision:**
  1. *Pre-calibration scores* for non-deterministic PERSON candidates, by shape: two or more
     capitalised tokens not all common words 0.60, all common words 0.45 (NER) or 0.35
     (label only), one token 0.45 or 0.25 if common, lowercase words or acronyms 0.20-0.30.
     With `review_threshold` 0.40 this separates `SINGLE_SIGNAL` (review) from `LOW`
     (discarded, counted). Phase 10 calibrates; these values are documented, not tuned.
  2. *Trigger-anchored grammars are L2*: `card/account ending NNNN`, `last four digits ...
     (NNNN)`, SSN last four and `home address`/`home at` + street grammar emit L2 evidence
     (Architecture ADR-04 lists `home address` as an L2 label), so they are DETERMINISTIC.
  3. *Person metadata fields are labels*: `dc:creator`, `cp:lastModifiedBy`, PDF `author`,
     annotation authors, author attributes and EXIF `Artist` are PERSON by field semantics
     (L2, DETERMINISTIC).
  4. *Registry*: an exact full-name match (first name, up to two middle initials, surname)
     of a registered person is CORROBORATED on its own: the person was already confirmed by
     two signals. Abbreviated variants (`F. Last`, `Dr Last`) and fuzzy OCR matches stay
     single signals. Fuzzy matching only considers windows that start with a capital.
     `person_key` is an HMAC of the canonical name (no name in `meta.db`).
  5. *More L4 grammar*: `First M. Last` (any line) and *list siblings*: in a delimiter list
     where NER tagged at least one item as a person, a name-shaped item NER missed or
     tagged only in part gets L4 evidence. Row labels apply in key/value tables.
  6. *Value propagation (L5)*: after tiering, every redacted value (4+ characters, numbers
     6+ digits) and every redacted email's local part becomes a linked finding wherever it
     occurs in the batch: case-sensitive for one-word values, case-insensitive otherwise,
     digits-only for long numbers in any formatting, and across two consecutive OCR lines
     of the same raster. Copies inherit type, tier, decision and person. This makes the
     writer, the sanitized text and V2 agree.
  7. *Covered weak signals are dropped*: a `SINGLE_SIGNAL`/`LOW` candidate inside a
     DETERMINISTIC `HOME_ADDRESS`, or on an OCR line inside a masked region, adds nothing.
  8. *Filters*: NER PERSON spans containing digits are dropped (incident IDs); trailing
     possessives are trimmed. The "50k common English words" list is the 50 000 most
     frequent lowercase entries of `en_core_web_lg`'s vector table (frequency-ordered).
  9. `Finding.locator` added so region findings and reports carry a location (FR-04).
- **Alternatives:** keep NER-only names at one score (every NER hit to review, about 200
  review items on the PDF); leave repeated values to V2 (all three samples `BLOCKED`).
- **Consequences:** On the samples, PDF review items fell from 205 to 91 before grouping,
  and the sanitized text no longer contains values redacted elsewhere. Propagation can
  over-redact a value that also has a harmless use; review items are grouped by value so
  one reviewer decision covers all copies (Phase 8). Scores remain uncalibrated until
  Phase 10.

### ADR-29: Redaction writers, batch pipeline and encrypted job state
- **Context:** TRD 7 describes each writer, but leaves open how a finding's offsets reach the
  exact XML nodes, what happens to package parts the extractors could not read, how a
  review re-run gets the raw text back without storing it in clear, and how tokens can be
  consistent across a batch when jobs run one after another.
- **Decision:**
  1. *Shared text maps* (`extract/textmap.py`): segment text is built from the same node
     pieces (runs, fields, attribute values, stripped generic text nodes) the writer edits,
     so offsets always map; a span crossing runs puts its token in the first run and
     removes the covered text from the rest. A segment whose map does not reproduce its
     text is never guessed: the action is unapplied (G4).
  2. *OOXML extras*: every author-like attribute in every part becomes `[REDACTED]` (not
     only `docProps`); a final value sweep replaces any remaining exact occurrence of a
     redacted value in any paragraph, text node or attribute (`mc:Fallback` copies, chart
     caches); short numbers are never swept. Unreferenced unreadable parts (`[trash]`
     remnants, an XML part that failed to parse) and printer settings are removed and
     reported as masked; the thumbnail is removed with its relationship and content-type
     override; package infrastructure is never removed.
  3. *Images*: redacted rasters keep their format, size and part name; EMF is rebuilt as a
     minimal EMF holding the redacted bitmap with the original frame (Windows renders it
     back); WMF cannot be rebuilt and stays unapplied. Region masks get 1.5 % padding.
     `Segment.ocr_word_boxes` (geometry only) lets the writer burn exactly the span's words.
  4. *PDF*: pages are routed with the extractor's rule; raster pages are re-rendered at the
     OCR DPI, burned, and rebuilt as a single image; the invisible text layer (TR-RD-20
     MAY) is not added. Annotations carrying findings are deleted and other annotation
     authors cleared. PyMuPDF's constant is `PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED`.
  5. *Batch pipeline*: `submit` (store + validate) then `run_batch`: extract all, detect over
     the batch (one registry), then tokens, writer, verifier and gate per job. Tokens are
     assigned in reading order, so numbering follows first occurrence.
  6. *Encrypted job state*: segment texts and finding values a review re-run needs are
     stored Fernet-encrypted (vault key) as `state.enc` in the job directory, deleted with
     the job. This is part of the vault in the sense of TR-SEC-02; nothing raw reaches
     `meta.db`. A `runs` table keeps the content-free verification report, action
     summary, timings and stage versions.
- **Alternatives:** re-run extraction and detection for review (TRD TR-RV-03 says detection
  is not re-run); pickle the state (unsafe to load); keep WMF/EMF as is (an unmasked
  screenshot would block the sample DOCX for good).
- **Consequences:** Outputs keep page/slide/paragraph counts. A WMF picture with findings
  blocks its document (G4); none is in the samples. Over-redaction is possible where a
  redacted value also has a harmless use.

### ADR-30: Verification interpretations and the repair pass
- **Context:** Running V1..V6 on the real outputs showed three things the TRD does not
  settle. OCR of a redacted raster is not OCR of the original: black boxes change page
  segmentation, so text the source OCR misread can be read correctly in the output (a real
  leak) and masked areas read as low-confidence noise. V3 "new" findings needed a
  definition. Short numeric needles hit unrelated numbers.
- **Decision:**
  1. *V2 needles*: values and normal forms of every redacted finding; registry variants
     only for registered (CORROBORATED or better) persons; one-word values matched with
     their case; numbers under 6 digits only together with the word before them in the
     source (`ending 4417`); digit runs compared with separators removed.
  2. *V3 "new"*: a residual finding is new when no source finding has the same type and
     value HMAC, so values the source pass already decided on are not re-litigated.
     Non-deterministic new hits become review items; a reviewer can accept them (stored as
     known) or confirm them (their output boxes are burned on every later run).
  3. *Repair pass*: when V2 hits or new deterministic V3 hits are located in an output
     raster's OCR, their word boxes are burned once and verification runs again from
     scratch; the gate sees only the second report. Hits in text layers (XML, PDF text,
     sanitized text) are never repaired and keep the gate at G1/G2.
  4. *V4*: `OCR_UNREADABLE`/`OCR_NO_TEXT` on an output raster the writer burned masks into
     is an effect of the masks (that raster was still OCR'd and searched by V2); OCR
     unavailable or timeouts always count.
  5. *V6*: SRS counts body structure only (annotation texts, link URIs, form values and
     outline titles are not units); CRS is computed per rendered segment (LCS of non-PII
     tokens against the sanitized segment).
  6. Repair boxes assume `verify_ocr_dpi` equals `ocr.dpi` (both 300); Phase 11 measures
     200 DPI and must scale boxes if the values differ.
- **Alternatives:** treat every OCR difference as blocking (all scanned outputs blocked by
  noise); skip OCR of outputs (misses pixel leaks entirely).
- **Consequences:** On the samples the repair pass burned a few boxes on the PDF and one on
  the DOCX; all three samples verify with 0 leak hits and reach `REVIEW_REQUIRED`.

### ADR-31: API service layer, value-grouped review, loopback-only API tests
- **Context:** TRD 10 lists the endpoints; it does not say how background work, review
  grouping, null fields or the socket-blocked test rule interact with a real HTTP stack.
- **Decision:**
  1. One background worker thread runs batches and review re-runs in order (OCR keeps its
     own process pool). Every request opens its own `meta.db` connection. Progress per job
     is kept in memory and reported by `GET /jobs/{id}`.
  2. Review items are grouped by `(type, value HMAC)`: one decision covers every linked copy
     of a value (ADR-28 value propagation). Masked regions and residual V3 hits are review
     items too (`kind`: finding, region, residual). Thumbnails are rendered from the
     redacted output, so they show the proposed masks applied (TR-RV-01). An added region's
     box is given in thumbnail pixels and scaled back to the raster.
  3. `GET /jobs/{id}/findings` (masked previews only) is open to submitters, as the UI
     expects; `include_text=true` needs the reviewer role. Rejection justifications are
     screened: any finding value in them is replaced by `[withheld]` before logging.
  4. Responses omit `null` fields (the UI's schemas reject `null` where a field is optional).
  5. A review decision moves the job `REVIEW_REQUIRED -> PROCESSING` with rule `review`; a
     document rejection moves it to `BLOCKED` with reason `REVIEWER_REJECTED`.
  6. In-process API tests run with sockets limited to loopback (`allow_hosts`): asyncio's
     event loop needs a loopback socket pair on Windows. A test proves outbound connections
     stay blocked. The browser smoke test (opt-in `-m e2e`) binds a localhost server.
- **Consequences:** The API is single-node and single-worker (PRD cut line: no Celery). A
  large batch queues behind the previous one.

### ADR-32: React + TypeScript web UI instead of Streamlit (user decision)
- **Context:** ADR-12 chose Streamlit for one-language simplicity. The user supplied a
  finished React 18 + TypeScript + Vite UI (`cleargate-ui/`, written against the TRD 10
  contract with a mock server) and asked for it to be integrated instead.
- **Decision:** Replace the Streamlit UI with the supplied React UI. ADR-12's principle is
  kept: the UI is a thin client of the API with no gate logic; every rule is enforced
  server-side (403/409/422). The production build (`VITE_API_MODE=live`) is served by
  `cleargate serve` on the same origin; the Vite dev server proxies `/api/v1`. Integration
  changes to the UI: the redacted download asks for the uploaded file's extension (it
  always asked for `.docx`), the Connect page names the `.env` tokens, two em dashes were
  removed (project style rule), and a "Confirm all remaining" button records confirm
  decisions for undecided items (a convenience; the server still re-verifies). The UI's
  own `docs/ADR-14-frontend.md` is this decision; its number predates ours.
- **Alternatives:** keep Streamlit (the user asked otherwise); serve the UI separately with
  CORS (two origins, more configuration for the manual test).
- **Consequences:** Node 18+ is needed to build the UI (`make ui`). The brief's Playwright
  exit criterion is met with Python Playwright driving the Edge installed with Windows
  (no browser download); on other systems the e2e test is skipped.

### ADR-33: Evaluation scoring rules and one calibrated threshold
- **Context:** TRD 9 defines the metrics and TRD 6.4 asks for per-tier thresholds fitted
  on gold. The policy has a single `detection.review_threshold`, the only score-routed
  boundary (DETERMINISTIC and CORROBORATED do not depend on a score; SINGLE_SIGNAL vs LOW
  does). The real-sample gold set has to come from the user's annotators; only the
  synthetic manifest exists today.
- **Decision:**
  1. Calibration fits that one threshold (recall maximised subject to precision >= 0.50,
     5-fold over segments, held-out results reported). When no threshold meets the target
     the lowest observed score is chosen: fail closed redacts more, never less.
  2. The threshold is written into the policy only on request (`--write-threshold`) and
     only from the annotated real-sample gold; a run on synthetic data refuses to write.
  3. A prediction that matches no gold span but carries a gold value of the same file and
     type elsewhere is a propagated copy (ADR-28): neither TP nor FP, counted separately.
  4. The leak metric is exact (normalised text, or the digit run of a numeric value with
     at least 6 digits) over the re-extracted output and the sanitized text; garbled OCR
     residues stay the job of V2/V3.
  5. `make eval` scores the synthetic fixtures (`eval/report.md`, committed, counts and
     metrics only). `python -m eval.run_eval --samples` scores the real files against
     `eval/gold/*.jsonl` into `out/eval-samples.md` (git-ignored). `python -m
     eval.draft_gold` writes value-free draft gold files for the annotators.
- **Alternatives:** per-tier thresholds (no score exists for the deterministic tiers);
  fitting on synthetic data (it would tune to planted values, the opposite of TRD 6.4).
- **Consequences:** `review_threshold` stays 0.40 until real gold exists, so the real-sample
  review load is not yet calibrated. Synthetic numbers are a regression signal, not an
  accuracy estimate; the report says so.

### ADR-34: Worker memory limit and the Docker image
- **Context:** TR-SEC-07 asks for a worker memory limit (`RLIMIT_AS`); ADR-16 and ADR-25
  deferred it to the Linux image because Windows has no `resource` module. PRD 8 asks for
  `docker compose up` on a laptop.
- **Decision:**
  1. `cleargate.core.limits.limit_memory(mb)` sets `RLIMIT_AS` and is the initializer of
     the PDF OCR process pool; Tesseract children inherit it. `CLEARGATE_WORKER_MEM_MB`
     (default 6144, 0 = off). `RLIMIT_AS` caps virtual size: a fresh worker reserves
     about 3.7 GB after one page (OpenCV and ONNX thread arenas) while only about 0.5 GB is
     resident; in the image 3072 MiB broke OCR, 4096 MiB worked, and an 8 GiB allocation was
     refused under every limit tried. The pool uses the `spawn` start method on every platform: a
     forked worker inherits the service's address space (measured 4.4 GB with spaCy
     loaded) and would start above the limit. Where the limit is enforceable (POSIX), OCR always runs in
     worker processes, never in the service process. A worker killed by the limit breaks
     the pool, and the job ends `FAILED` (fail closed). On Windows it is a documented
     no-op.
  2. The image is two-stage: Node builds the UI in live mode; `python:3.13-slim` with
     Tesseract (Debian package) and the pinned spaCy model wheel runs `cleargate serve` as
     a non-root user. The source is installed editable under `/app` because `REPO_ROOT`
     locates `config/` and `cleargate-ui/dist` relative to the package.
  3. Compose publishes on loopback only, mounts `/data` as a volume, reads keys from
     `.env`, sets a container memory limit, a read-only root file system, `cap_drop: ALL`
     and `no-new-privileges`. `.dockerignore` keeps `Data/`, `samples/`, `eval/gold/`,
     `out/`, `.env` and databases out of the build context.
- **Alternatives:** Windows Job Objects for the limit (more code for a dev platform);
  a non-editable wheel install (would need `REPO_ROOT` to become configurable).
- **Consequences:** DOCX/PPTX image OCR runs in the service process and is bounded only by
  the container limit. The image uses Debian's Tesseract (5.3), not 5.4 as on the
  development machine, so OCR output can differ slightly.

### ADR-35: The server reports the role of a token (`GET /whoami`)
- **Context:** The supplied UI stored the role the user *selected* on the Connect page and
  gated the review page on it in the browser. A reviewer token entered under "Submitter",
  or a page reload without the tab-only token, made the UI show "This token is not a
  reviewer token" without asking the server (seen in manual testing). TRD 10 has no
  endpoint that reports a token's role.
- **Decision:** Add `GET /api/v1/whoami` (any valid token; returns `{"role": ...}`, 401
  otherwise). The Connect page verifies the token with it before storing anything and
  stores the server's role; a rejected token is reported on the Connect page. The review
  page says "Not connected" when no token is held. Server-side enforcement is unchanged:
  reviewer endpoints still return 403 to a submitter token.
- **Alternatives:** keep the client-side choice (the observed confusion); infer the role
  from a 403 on the review endpoint (works only after the user is already on that page).
- **Consequences:** One endpoint beyond TRD 10. The role buttons on the Connect page are a
  hint only.
