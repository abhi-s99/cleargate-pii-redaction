# Phase 04: Deterministic detection
Tag: v0.4.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built

The deterministic detection layers and the merge that combines them.

- **L1 recognizers with validators** (`detect/recognizers/deterministic.py`, `phone.py`):
  email (RFC-lite, alphabetic TLD, no network), phone (`phonenumbers.PhoneNumberMatcher`,
  8 regions, leniency VALID), SSN (Presidio invalidation rules, 9xx areas allowed,
  undelimited needs context), PAN (holder type; non-`P` holders discarded as
  `business_pan`), PESEL (checksum plus encoded birth date; masked `NNNNNNxxxxx` after
  `PESEL`), payment card (Luhn plus IIN sanity), passport (context-required), employee IDs
  from the policy.
- **L2 label-anchored capture** (`label_anchored.py`): `SSN`, `PAN`, `PESEL`, `Passport`,
  `DOB`/`Date of birth`/`born`, `TIN`/`NI`, `Mobile`/`Phone`/`Tel`, `M` before `+`; inline,
  as a column header (every cell of the column) or as a row label (key/value tables). A
  per-type value grammar captures the value whatever its format; the L1 validator only
  sets `format_invalid`. On OCR segments up to two confusion substitutions
  (`0/O 1/I/l 5/S 7/T 8/B 2/Z`) are tried to reach a valid value (TR-DT-12).
- **L4 subset** (`context.py`): partial financial (`card ending NNNN`, `last four digits ...
  (NNNN)`, masked account numbers), SSN last four, home address with trigger. These are
  trigger-anchored captures and carry L2 evidence (ADR-28).
- **Merge and tiers** (`detect/merge.py`, TRD 6.3): identical hits combined, same-type
  overlaps unioned, compatible types kept (PERSON inside HOME_ADDRESS), conflicting types
  resolved by priority with the loser's evidence kept on the winner; passes repeat to a
  fixed point. Tiers and decisions per TRD 6.3 points 4 and 5.

Requirements: TR-DT-10, TR-DT-11, TR-DT-12 (PASS); TR-DT-14 subset (PASS with Phase 5);
FR-05 (with Phase 5).

## Files added / changed

- `cleargate/detect/base.py`: `Candidate`, `DocContext` (column headers, row labels),
  value normalisation, HMAC, masked previews.
- `cleargate/detect/recognizers/{deterministic,phone,label_anchored,context}.py`.
- `cleargate/detect/presplit.py`, `cleargate/detect/lexicon.py` (used by the context rules).
- `cleargate/detect/merge.py`.
- `tests/unit/detect_support.py`, `tests/unit/test_recognizers.py`,
  `tests/unit/test_merge.py`; `.gitignore` (UI `node_modules/`).

## How to verify (copy-paste)

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_recognizers.py tests\unit\test_merge.py -q
make check
```

Expected: `160 passed`; `make check` green.

## Actual results

**Tests:** `pytest tests/unit/test_recognizers.py tests/unit/test_merge.py -q`:
`160 passed in 1.21s`. Each recognizer has at least 5 positives and 5 negatives, and
OCR-damaged cases are tested both ways: L1 refuses `9OO-l2-3456` and `PAN BCDPF567BK`, and
L2 repairs them on OCR segments only.

**False-positive suite (exit criterion):** risk, incident and policy IDs (`RSK-`, `INC-`,
`GRP-POL-`), invoice numbers, version strings, page numbers, dates without a DOB label,
`ending soon`, corporate addresses without a home trigger and company PANs are not flagged
(`test_ssn_negatives`, `test_phone_negatives`, `test_employee_id_negatives`,
`test_partial_financial_negatives`, `test_corporate_addresses_are_kept`,
`test_business_pan_is_discarded_with_reason`).

**Merge properties (hypothesis, 100 examples each):** idempotent, order-independent, never
drops a HIGH-risk deterministic span, no conflicting overlaps in the output.

**Sample counts, rule layers only** (L1, L2, L4, metadata, registry; no NER; counts only):

| File | Redacted by type | Decisions |
|---|---|---|
| Risk policy PDF | DATE_OF_BIRTH 1, EMAIL_ADDRESS 157, EMPLOYEE_ID 191, FINANCIAL_PARTIAL 2, HOME_ADDRESS 2, IN_PAN 5, PASSPORT 2, PHONE_NUMBER 128, PL_PESEL 1, US_SSN 4, PERSON 271 (context rules, metadata, registry) | auto 506, review 269, discarded 15 |
| Org pack PPTX | EMAIL_ADDRESS 34, PHONE_NUMBER 34, PERSON 56 | auto 70, review 54 |

**All 16 PPTX mobiles caught by the label-anchored phone rule (exit criterion):** 16 phone
findings carry `header:PHONE_NUMBER` evidence (the `Mobile` column), all `format_invalid`
(the library rejects `+1 (555) 01xx`); 18 more come from inline phone labels. Measured
with `DetectionEngine(policy, use_ner=False)` on the real PPTX.

## Deviations from spec

- ADR-28 (points 1 and 2): pre-calibration scores; trigger-anchored grammars carry L2
  evidence. Row labels apply to key/value tables (point 5).

## Known gaps / risks carried forward

- The phone recognizer accepts only numbers the library validates; badly formatted numbers
  depend on a label (column header or inline).
- Passport needs the word `passport` nearby; a bare passport number is not detected.
- Business PAN discards rely on the holder character; an OCR-damaged holder character is
  repaired only next to a `PAN` label.

## Next phase entry criteria

- `make check` green at `v0.4.0`. Phase 5 adds NER, the person registry, the allowlist and
  propagation on top of these layers.
