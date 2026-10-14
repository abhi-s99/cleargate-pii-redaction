# Counter-question prep: ClearGate implementation

Likely questions from the Optiv panel after the walkthrough, with the answer, the evidence
to point at, and the honest caveat where one exists. Numbers come from `eval/report.md`
(synthetic gold), `out/smoke.md` (real samples, counts only) and the phase reports. Never
quote a sample value when answering; counts, types and pages only.

How to use it: lead with the one-line answer, then the evidence. When a question lands on
a real gap (marked **Weak spot**), say so first; the panel will respect a stated limit
more than a defended one.

---

## 1. Architecture and scope

**Q1. Why a modular monolith and not microservices? How does it scale?**
The bottleneck is CPU-bound OCR, not request fan-out (ADR-01). One FastAPI process plus an
OCR process pool keeps the operational surface small for a 3-week build. Stages talk only
through the Canonical Document Model, so any stage could move behind a queue without
touching the others. Scaling today means more OCR workers or more hosts.
*Caveat:* one background worker thread runs batches in order (ADR-31); a large batch queues
behind the previous one. SQLite is single-node.

**Q2. Why not just use Presidio, or a cloud DLP service (Comprehend, Google DLP, Purview)?**
Cloud DLP sends the document off-host, which is the thing the client policy forbids
(local-only, no network at runtime, tested with sockets blocked). Presidio *is* used, as
one layer (L3). On its own it fails here: it gives every NER hit a constant 0.85 score,
its phone recognizer rejected every mobile number in the PPTX, and it has no OCR, no
writer, no verification and no gate (Architecture D9, D13).

**Q3. Why not use an LLM to find the PII?**
Sending the raw document to an LLM to find the personal data is itself the policy
violation. A local LLM would avoid that but is non-deterministic, slow on CPU and hard to
verify. ClearGate's answer to "is this safe" is a gate on checkable evidence, not a
model's opinion. A local model could be added later as one more detection layer; it would
not replace verification.

**Q4. What exactly is "fail closed" here? Show me.**
Only `decide()` can enter `VALIDATED_SAFE`, and only when rules G0 to G7 all pass (TRD 8.2,
ADR-22). Every failure path ends non-safe and has a test: OCR disabled on a scanned PDF ends
`BLOCKED` (G3); an unapplied redaction ends `BLOCKED` (G4); a verification crash ends
`FAILED`; a verification check that did not run counts as failed (ADR-24); a SafeHandle
mint failure ends `FAILED`. Downloads return 403 and handoff 409 before SAFE.
Demo point: show `test_extract_failclosed.py::test_ocr_disabled_scanned_pdf_ends_blocked_g3`.

**Q5. Your design said Streamlit; the build has React. Why the change?**
User decision (ADR-32): a finished React UI written against the TRD API contract was
supplied. ADR-12's principle stands: the UI holds no gate logic, every rule is enforced
server-side, and the UI cannot bypass it. The server reports a token's role (`/whoami`,
ADR-35) instead of trusting the browser's choice.

---

## 2. Detection

**Q6. Documents mix people, vendors and products. How do you tell them apart?**
A vendor/product allowlist can suppress **only NER-only (L3) findings whose span equals an
allowlisted term**. It never suppresses validated identifiers (L1), label-anchored values
(L2) or a name already in the person registry. So a product named in the same sentence as
two people stays, and the people are redacted.
Evidence: `test_detect_context.py::test_products_kept_while_people_in_same_sentence_are_redacted`;
0 of 7 keep-list terms redacted in `eval/report.md`.

**Q7. What if a person's surname is also an allowlisted vendor name?**
If NER is the only signal, it is kept (that is the allowlist's job). If anything else
fires (honorific, initial-plus-surname, field label, registry match) the finding is not
NER-only and is redacted. *Caveat:* a bare surname that equals a product name and has no
other signal would be kept. The allowlist is small and client-curated for that reason.

**Q8. OCR damages identifiers (a dropped digit, `T` for `7`). How do you catch those?**
L2 label-anchored capture: after a high-risk label (`SSN`, `PAN`, `Passport`, `DOB`, ...)
the value is captured whatever its format and tagged `format_invalid`. On top: fuzzy
registry matching for OCR'd names, value propagation across consecutive OCR lines, and
low-confidence region masking for what cannot be read at all (Architecture D4, ADR-28).

**Q9. How do you handle unlabelled PII in narrative prose?**
NER on pre-split segments, then context grammars: honorifics, `First M. Last`,
`card/account ending NNNN`, `last four digits ... (NNNN)`, home-address grammar. Then
document- and batch-wide propagation: once a person or value is confirmed, every other
mention is redacted too (L5).

**Q10. Why evidence tiers instead of a confidence score and a threshold?**
Because the scores are not probabilities: Presidio's NER score is a constant, so a
threshold on it is meaningless (D13). Tiers say *why* we believe something:
DETERMINISTIC (validator passed or label-anchored) and CORROBORATED (two independent
signals) auto-redact; SINGLE_SIGNAL redacts *and* goes to review; LOW is discarded but
counted.

**Q11. The PERSON scores (0.60, 0.45, ...) look hand-picked. Aren't they arbitrary?**
**Weak spot.** Yes, they are documented pre-calibration values (ADR-28), chosen by name
shape, not tuned. The calibration harness exists (5-fold, recall maximised under a
precision floor) and refuses to write a threshold fitted on synthetic data (ADR-33). It
needs the real-sample gold set. Note the direction of the risk: a single-signal name is
still *redacted* while it waits for review, so an uncalibrated threshold costs review time,
not leaks.

**Q12. Names that only appear inside screenshots?**
Every embedded image is OCR'd (upscaled 2x when small) and goes through the same detector
stack. Faces are found by OpenCV YuNet plus Haar cascades (ADR-27). Text that cannot be
read is not treated as empty: the region is masked and sent to review.

**Q13. Over-redaction: how do you keep context for the AI?**
The taxonomy is personal data only: organisations, products, cities, non-DOB dates,
amounts and risk/policy IDs are kept (ADR-05). Structure and context retention are
measured: SRS and CRS are 1.0 on all three samples (`out/smoke.md`). *Caveat:* value
propagation can over-redact a value that also has a harmless use (ADR-28).

**Q14. Role titles can identify someone ("the Group CRO"). Do you handle that?**
**Weak spot.** No. Quasi-identifiers are kept by default to preserve context; the
`keep.role_titles` switch is read but generalisation is not implemented (README
Limitations, PRD 11 future work).

**Q15. Non-English documents or non-Latin names?**
Untested. English spaCy model only. Stated in README Limitations.

---

## 3. Redaction

**Q16. How do you prove a redaction cannot be reversed?**
No overlays (ADR-07). Scanned pages are re-rendered, masks burned into pixels and the page
rebuilt from the redacted raster: the original image objects are gone
(`test_scanned_output_has_no_original_image_objects`). Native PDF uses true content
redaction. DOCX/PPTX text is removed from the XML, plus the places people forget: author
attributes, tracked deletions, comment authors, field codes, thumbnails, `docProps`,
printer settings, a leftover `[trash]` part (ADR-26, ADR-29). Then V2 re-opens the output
and searches for every original value.
Talking point: one sample screenshot shows the original organisation under a pasted-on
label (D12), which is exactly the overlay failure this avoids. Do not name it.

**Q17. Why typed tokens and not realistic fake names?**
Fake names can collide with real people, the AI cannot tell them from real names, and a
residual scanner cannot tell a substitute from a leak. `[PERSON_7]` is unambiguous and
machine-verifiable (ADR-06).

**Q18. Consistent tokens across files: doesn't that help re-identification?**
It is a deliberate trade-off: the AI needs to follow who did what across the batch. Tokens
are per batch only (PRD 13 default), the mapping is HMAC-keyed and Fernet-encrypted in a
vault that is never in reports, downloads or the handoff, and it is deleted with the batch.

**Q19. What if a redaction cannot be applied (odd XML, a span across runs, a WMF image)?**
Spans across runs are handled by the shared text map (token in the first run, covered
text removed from the rest). If a segment's map does not reproduce its text, the writer
does not guess: the action is marked unapplied and the gate blocks (G4). A WMF picture
with findings cannot be rebuilt and blocks its document (ADR-29).

---

## 4. Verification and the gate

**Q20. Isn't verification just the same detector run twice, with the same blind spots?**
Partly, and say so. V2 (known-value leak) and V4 (coverage) are independent of detector
recall: V2 searches the re-extracted output, including OCR of the output rasters, for
every value and variant; V4 checks every page, image and XML part was inspected or masked.
V3 re-runs detection with a different profile (allowlist off, threshold halved), but it
shares the NER model, so a name the model cannot see in either pass is not caught by V3.
That residual risk is why there is review, propagation and a stated limit: no scanner
proves zero PII.

**Q21. The "repair pass" burns extra boxes after verification. Isn't that grading your own homework?**
It is narrow (ADR-30): only hits located in an *output raster's* OCR are burned, once, and
then verification runs again from scratch; the gate sees only the second report. Hits in
any text layer (XML, PDF text, sanitized text) are never repaired and keep the job
`BLOCKED`. It exists because OCR of a redacted page can read text the source OCR misread,
which is a real leak and gets fixed rather than ignored.

**Q22. Could someone edit the database and mark a job SAFE?**
The schema makes it hard (trigger, single-use transition tickets, append-only history,
ADR-20), but SQLite is not the security boundary and we do not claim it is. The boundary
is the SafeHandle: an HMAC over job id, sanitized-text hash, policy hash and verification
hash. Handoff re-hashes the sanitized file and checks the job is still SAFE under the same
policy. A test forges a SAFE row and the handoff refuses it (`mac_mismatch`).

**Q23. Can a reviewer just approve everything?**
A reviewer cannot "click safe". Decisions trigger re-redaction and re-verification and the
gate decides again. HIGH-risk deterministic findings cannot be rejected. "Confirm" means
*redact*, so bulk-confirm only redacts more. Rejecting a finding needs a justification,
which is screened for values before logging, and every decision is in `review_log`.
*Caveat:* a reviewer can wrongly reject a single-signal name; that is an audit question,
not something the tool can prevent.

**Q24. Why does an SRS below 0.80 go to review rather than block?**
Structure loss is a quality failure, not a privacy failure. Blocking is reserved for
privacy evidence: a leak, a new deterministic hit, an uninspected part, an unapplied
redaction, a token inconsistency.

**Q25. None of the three real samples reached SAFE automatically. Is that a failure?**
No, it is the gate working. All three end `REVIEW_REQUIRED` (G6) with 0 V2 leaks and 0
uninspected parts after masking: the PDF because of masked illegible regions, a face and
uncertain names; the PPTX with only 3 review items. A design that auto-passed a scanned
policy with an illegible identity screenshot would be the fail-open case the brief warns
about. The review-to-SAFE path is demonstrated end to end (`test_review_path_reaches_safe`,
and live on the PPTX in the demo).

---

## 5. Evaluation

**Q26. Every metric is 1.000. Why should we believe it?**
**Weak spot.** Do not defend those numbers as accuracy. They are measured on synthetic
documents with planted, invented values (n = 62 items, 5 files): a regression signal that
the pipeline works end to end, not an estimate of real-document accuracy. The report says
so and gives Wilson intervals: the leak-rate upper bound is 0.058, region recall's lower
bound 0.51. Precision is not perfect (0.969, two PERSON false positives).

**Q27. Why is there no accuracy number on the real samples?**
**Weak spot, the biggest one.** The real-sample gold set is not annotated yet (ADR-33).
The harness, the `--samples` mode and value-free draft gold files (`make draft-gold`)
are ready. It was not self-annotated from the system's own output because that inflates
recall (PRD 12 risk: annotate before viewing output, second annotator). What *is*
measured on the real files: 0 known-value leaks (V2), 0 uninspected parts, SRS/CRS 1.0,
counts by type.

**Q28. The real PDF and DOCX produce 91 and 103 review items. Is that practical?**
Items are grouped by value, so one decision covers every copy (ADR-31). The threshold is
uncalibrated, and the expectation is calibration on real gold cuts the queue; that is not
yet shown. The target of under 30 s per item has not been observed. The PPTX, with clean
native text, needs only 3. Direction of error is safe: uncertain names are redacted while
they wait.

**Q29. Three documents: how can you say anything statistically?**
We say little, deliberately. Every rate carries n and a 95 % Wilson interval, and the
report states the numbers do not generalise (ADR-13, TRD 6.4).

---

## 6. Performance and operations

**Q30. How fast is it?**
Real samples, 12 CPUs, 4 OCR workers: scanned PDF 212 s for 35 pages (6.1 s/page against a
20 s/page target), PPTX 32 s, DOCX with 36 screenshots 199 s.
**Weak spot:** the DOCX misses its 180 s target, and the 2 vCPU reference machine was not
measured. Verification re-OCRs the output, roughly doubling scanned-PDF cost. Next step is
profiling the DOCX image OCR path.

**Q31. Can this handle thousands of documents a day?**
Not as built: single worker thread, single node, SQLite. The stage boundaries make a queue
and more hosts a contained change, and Celery was cut on purpose (PRD cut line). OCR
results are cached encrypted by page-pixel hash, so re-runs are cheap.

**Q32. What about hostile files: zip bombs, XXE, huge images?**
Validation sniffs type by content and rejects encrypted, macro-enabled, oversized and
zip-bomb files; XML parsing is hardened against XXE. OCR workers get an `RLIMIT_AS` memory
limit, and a worker killed by it ends the job `FAILED` (ADR-34).
*Caveat:* the limit is POSIX only (Docker image); on Windows it is a no-op, and DOCX/PPTX
image OCR runs in the service process, bounded only by the container limit.

**Q33. Data retention?**
Job directories are owner-only, a TTL sweeper deletes batches after 24 h (configurable),
and the encrypted job state is deleted with the job. Nothing raw is in `meta.db`.

---

## 7. Security

**Q34. Where are the keys and what happens if the vault key leaks?**
In `.env` (Fernet vault key, HMAC gate key, two role tokens), generated by `make keys`,
never committed. A leaked vault key plus the vault file re-identifies that batch's
tokens, which is why the vault is separate, per batch and short-lived. Production needs
a KMS-backed key and per-tenant keys (PRD 11). Prototype, and stated as such.

**Q35. Authentication?**
Static bearer tokens per role, compared in constant time, role reported by the server.
Prototype only: no SSO, single tenant (PRD non-goal).

**Q36. How do you know no raw PII lands in logs, reports or the database?**
Raw fields are `raw_field()` and never serialise (property-tested); a `PiiSafeFilter`
drops log records containing active values and strips exception text; findings are stored
as type, tier, locator and value HMAC only. Tests plant values and grep logs, reports and
the database for them (`test_reports_and_logs_never_carry_planted_values`).
*Caveat:* the uploaded file *name* is kept for reports and could itself be personal data
(ADR-25, documented residual risk).

**Q37. How do you prove there is no network access?**
The test suite runs with sockets blocked; API tests allow loopback only, and a test shows
an outbound connection is still refused. No real LLM client ships: enabling `llm` without
an implementation refuses the handoff.

**Q38. Could a document carry a prompt injection into the AI agent?**
Yes, and that is outside ClearGate's scope: it gates personal data, not instructions in
the content. The sanitized text is still document text. Worth raising as a separate
control for the agent owner.

---

## 8. Process and judgement

**Q39. How do you know the code does what the docs say?**
Every PASS in a phase report sits next to the command and its real output. Fast suite:
835 passed, 1 skipped (POSIX-only memory test, run in the Docker image), 14 deselected
(slow and sample tests). mypy strict on core, gate and verify; hypothesis state-machine
tests on the gate; fault injection for every failure path in Architecture 6;
`scripts/check_matrix.py` ties every requirement to tests (`docs/VERIFICATION.md`).
Before answering, re-run `make check` on the day so you can quote a fresh number.

**Q40. Where did you deviate from your own spec?**
Every deviation is an ADR in `docs/DECISIONS.md` (ADR-14 to ADR-35), for example OpenCV
pinned to 4.x because 5.0 dropped the face cascades (ADR-17), YuNet added because Haar
missed a 13 x 17 px face (ADR-27), React replacing Streamlit (ADR-32). No threshold was
weakened to make a test pass (ADR-27 records the rejected option of raising one).

**Q41. What would you do with three more weeks?**
In order: (1) annotate the real-sample gold set and calibrate the review threshold;
(2) fix the DOCX performance miss; (3) role-title generalisation for quasi-identifiers;
(4) client-identity pack (logos and tenant names in screenshots, D12); (5) production
controls: SSO, KMS-backed vault, queue-based workers.

**Q42. How does this compare to the reference implementation (Smart-Redact)?**
`REFERENCE_GAP_ANALYSIS.md`: of 15 areas, 14 are closed with test evidence, 1 partial
(real-sample accuracy). The headline difference is that the reference, as documented,
fails open on the scanned PDF (no OCR on the PDF path, so 0 findings and "complete").
Caveat to state up front: only its documentation was available, so every statement about
it is "documented, not verified".

---

## Weak spots in one place (rehearse these)

| Gap | One-line answer |
|---|---|
| No real-sample accuracy | Harness ready, gold annotation pending, deliberately not self-annotated (ADR-33) |
| Uncalibrated threshold, long review queues | Errs toward redaction; calibration needs real gold |
| Synthetic metrics are all near 1.0 | Regression signal, not accuracy; intervals stated |
| DOCX 199 s vs 180 s target | Measured and reported, profiling next |
| V3 shares the NER model | Hence V2, coverage, review; no zero-PII claim |
| Quasi-identifiers kept | Context trade-off, generalisation is future work |
| Prototype security | Static tokens, single tenant, `.env` keys |
| English only | Untested beyond English |
