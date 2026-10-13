# Phase 05: Context-aware detection
Tag: v0.5.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built

The layers that find people, and the engine that runs all five layers over a batch.

- **Pre-processing** (`detect/presplit.py`): sub-spans split on ` / `, `;`, `|`, `·`, tabs and
  (cells, OCR lines) line breaks; NFKC/dash/quote/whitespace normalisation with an offset
  map back to the original text (TR-DT-01, TR-DT-02).
- **L3 NER** (`detect/ner.py`): Presidio `AnalyzerEngine` with only `SpacyRecognizer`
  (no network-capable recognizer), `en_core_web_lg` loaded once per process and shared
  with the word list, batched with `nlp.pipe`. PERSON spans with digits are dropped;
  ORGANIZATION spans feed allowlist learning.
- **L4 person context** (`context.py`): person field labels inline and as column headers or
  row labels, honorifics (hyphen-aware), initials + surname (header, role line or
  registered surname), `First M. Last`, delimiter-list siblings (ADR-28).
- **L5** (`registry.py`, `propagate.py`): canonical keys, variants, exact full-name and
  abbreviated sweeps, fuzzy OCR sweep (`rapidfuzz` ratio >= 90, capitalised windows),
  unique non-common surnames; batch-wide `person_key` (an HMAC). Value propagation of
  every redacted value across the batch (ADR-28 point 6).
- **Allowlist** (`allowlist.py`): policy terms plus auto-learned organisations (corporate
  suffix or vendor context); suppresses only all-NER findings whose span equals a term and
  whose person is not registered.
- **Engine** (`engine.py`): rule layers, NER, first merge, registry seeding, second context
  pass and sweeps, final merge, allowlist, tiers, decisions, region findings; profiles
  `default` and `verify` (allowlist off, threshold x 0.5, tokens ignored).

Requirements: TR-DT-01, 02, 13, 14, 15, 16, TR-PF-05, FR-05, FR-06 (PASS); FR-07 (PARTIAL:
routing follows the threshold; calibration is Phase 10).

## Files added / changed

- `cleargate/detect/{ner,registry,propagate,allowlist,engine}.py`.
- `cleargate/core/models.py`: `Finding.locator`; `cleargate/core/db.py`: `findings.locator_json`
  (schema 2 with in-place migration).
- `tests/unit/test_detect_context.py`, `tests/integration/test_detect_fixtures.py`;
  extraction fixtures moved to `tests/integration/conftest.py` so both phases share them.

## How to verify (copy-paste)

```powershell
.venv\Scripts\python.exe -m pytest tests\unit\test_detect_context.py tests\integration\test_detect_fixtures.py -q
make check
```

Expected: `106 passed`; `make check` green.

## Actual results

**Tests:** `pytest tests/unit/test_detect_context.py tests/integration/test_detect_fixtures.py -q`:
`106 passed in 7.72s`.

**Exit criteria (synthetic analogues of each spaCy failure in brief section 1):**

| Criterion | Test | Result |
|---|---|---|
| Three names in one cell give three PERSON findings | `test_three_names_in_one_cell_give_three_person_findings` (and without a header) | PASS |
| Two-common-word name under `Created by` is CORROBORATED | `test_two_common_word_name_under_created_by_is_corroborated` | PASS |
| `Ms <Hyphen-Name>`, `Led by <Name>`, `M. Surname` caught | `test_honorific_led_by_and_label_names_are_caught`, `test_initial_surname_header_is_linked_to_registered_person` | PASS |
| Products kept while people in the same sentence are redacted | `test_products_kept_while_people_in_same_sentence_are_redacted` | PASS |
| Allowlist term that is a registered person is redacted | `test_allowlist_term_that_is_a_registered_person_is_redacted` | PASS |
| Merge properties | `tests/unit/test_merge.py` (Phase 4) | PASS |
| Planted manifest: every item detected with its type and redacted; decoys kept | `test_planted_item_detected_with_type_and_redacted` (62 items), `test_decoys_are_not_redacted` (7) | PASS |

**Evidence-tier distribution on the samples** (full engine, counts only, 12 CPUs,
`detect_batch` 25.0 s for the three files):

| File | Redacted by type | Tiers (redacted) | Decisions |
|---|---|---|---|
| Risk policy PDF | PERSON 407, EMPLOYEE_ID 191, EMAIL_ADDRESS 157, PHONE_NUMBER 128, IN_PAN 5, US_SSN 4, FINANCIAL_PARTIAL 2, HOME_ADDRESS 2, PASSPORT 2, DATE_OF_BIRTH 1, PL_PESEL 1, UNREADABLE_IMAGE_REGION 10, PHOTO 1 | DETERMINISTIC 506, CORROBORATED 314, SINGLE_SIGNAL 91 | auto 820, review 91, discarded 33 |
| TPRM DOCX | PERSON 139, UNREADABLE_IMAGE_REGION 16 | DETERMINISTIC 18, CORROBORATED 34, SINGLE_SIGNAL 103 | auto 52, review 103, suppressed 6, discarded 102 |
| Org pack PPTX | PERSON 56, EMAIL_ADDRESS 34, PHONE_NUMBER 34 | DETERMINISTIC 70, CORROBORATED 51, SINGLE_SIGNAL 3 | auto 121, review 3, discarded 2 |

Value propagation added 29 (PDF), 65 (DOCX) and 1 (PPTX) linked findings. The DOCX review
count is dominated by copies of the same single-signal values; Phase 8 groups review items
by value. Six DOCX NER hits were suppressed by the allowlist (product names).

**Tuning done on numbers only** (no sample text viewed): NER-only `First M. Last` names
were the largest review group on the PDF (73); the middle-initial grammar and registry
full-name matching reduced PDF review findings from 205 to 91.

## Deviations from spec

- ADR-28: pre-calibration scores, metadata person fields as labels, registry full-name
  matches as CORROBORATED, extra L4 grammar, value propagation, covered weak signals
  dropped, digit filter, common-word list from the model's vector table, `Finding.locator`.

## Known gaps / risks carried forward

- Review load on the DOCX is high: most items are NER-only single words or names in
  screenshots. Calibration (Phase 10) and value grouping (Phase 8) address it; the
  precision of those single-signal items is unknown until gold labels exist.
- Value propagation is exact (or digit-form); a value OCR misreads elsewhere is caught only
  by the fuzzy registry sweep (people) or by verification (Phase 7).
- Role titles are kept by policy (`keep.role_titles`), a quasi-identifier risk.

## Next phase entry criteria

- `make check` green at `v0.5.0`. Phase 6 tokenises, writes the redacted files and the
  sanitized text.
