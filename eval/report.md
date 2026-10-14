# Evaluation report

Generated 2026-10-14T02:22:59+00:00 by `python -m eval.run_eval`. Gold: synthetic manifest (synthetic). Policy `cadence-default` hash `c04ecbc88aea0486`, review threshold 0.40. CPU count 12. Batch wall time 16.6 s. Counts and metrics only, no document values.

Intervals are 95 % Wilson score intervals; n is shown with every rate. With this few documents every number is weak evidence (TRD 6.4).

## Headline (PS-2 targets)

| Metric | Value | Target |
|---|---|---|
| Leak rate (gold values in any output) | 0.000 [0.000, 0.058] (n=62) | 0 |
| Recall, overlap match | 1.000 [0.942, 1.000] (n=62) | high |
| Region recall (faces, unreadable) | 1.000 [0.510, 1.000] (n=4) | 1.0 |
| Business terms redacted (FP on keep-list) | 0.000 [0.000, 0.354] (n=7) | 0 |
| Review load (review items / findings) | 0.058 [0.023, 0.140] (n=69) | low |
| Error rate (FAILED / jobs) | 0.000 [0.000, 0.434] (n=5) | 0 |
| SRS min over jobs | 1.000 | >= 0.80 |
| CRS min over jobs | 1.000 | >= 0.80 |

## Per job

| File | State | Rule | Units | Gold | Not extracted | Leaked | Findings | Review | Regions found/gold | Keep-list redacted | SRS | CRS |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|
| planted.docx | REVIEW_REQUIRED | G6 | 21 | 28 | 0 | 0 | 30 | 2 | 1/1 | 0/4 | 1.000 | 1.000 |
| planted.pptx | REVIEW_REQUIRED | G6 | 10 | 16 | 0 | 0 | 18 | 1 | 1/1 | 0/0 | 1.000 | 1.000 |
| planted_native.pdf | VALIDATED_SAFE | G7 | 3 | 8 | 0 | 0 | 8 | 0 | 0/0 | 0/1 | 1.000 | 1.000 |
| planted_scanned.pdf | REVIEW_REQUIRED | G6 | 4 | 8 | 0 | 0 | 11 | 1 | 2/2 | 0/2 | 1.000 | 1.000 |
| planted.png | VALIDATED_SAFE | G7 | 1 | 2 | 0 | 0 | 2 | 0 | 0/0 | 0/0 | 1.000 | 1.000 |

## Detection, overlap match (character IoU >= 0.5, same type)

| Type | Gold | Found | Recall [95% CI] | Pred TP | Pred FP | Precision [95% CI] | F1 |
|---|---:|---:|---|---:|---:|---|---:|
| DATE_OF_BIRTH | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| EMAIL_ADDRESS | 9 | 9 | 1.000 [0.701, 1.000] (n=9) | 9 | 0 | 1.000 [0.701, 1.000] (n=9) | 1.000 |
| EMPLOYEE_ID | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| FINANCIAL_PARTIAL | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| HOME_ADDRESS | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| IN_PAN | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| PASSPORT | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| PAYMENT_CARD | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| PERSON | 36 | 36 | 1.000 [0.904, 1.000] (n=36) | 36 | 2 | 0.947 [0.827, 0.985] (n=38) | 0.973 |
| PHONE_NUMBER | 4 | 4 | 1.000 [0.510, 1.000] (n=4) | 4 | 0 | 1.000 [0.510, 1.000] (n=4) | 1.000 |
| PL_PESEL | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| US_SSN | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| **all** | 62 | 62 | 1.000 [0.942, 1.000] (n=62) | 62 | 2 | 0.969 [0.893, 0.991] (n=64) | 0.984 |

Propagated copies (same value as a gold item at another location, neither TP nor FP): 0. Gold items without a text channel (image-only), not span-scored: 1.

## Detection, strict match (same offsets or same normalised text)

| Type | Gold | Found | Recall [95% CI] | Pred TP | Pred FP | Precision [95% CI] | F1 |
|---|---:|---:|---|---:|---:|---|---:|
| DATE_OF_BIRTH | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| EMAIL_ADDRESS | 9 | 9 | 1.000 [0.701, 1.000] (n=9) | 9 | 0 | 1.000 [0.701, 1.000] (n=9) | 1.000 |
| EMPLOYEE_ID | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| FINANCIAL_PARTIAL | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| HOME_ADDRESS | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| IN_PAN | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| PASSPORT | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| PAYMENT_CARD | 1 | 1 | 1.000 [0.207, 1.000] (n=1) | 1 | 0 | 1.000 [0.207, 1.000] (n=1) | 1.000 |
| PERSON | 36 | 34 | 0.944 [0.819, 0.985] (n=36) | 34 | 4 | 0.895 [0.759, 0.958] (n=38) | 0.919 |
| PHONE_NUMBER | 4 | 4 | 1.000 [0.510, 1.000] (n=4) | 4 | 0 | 1.000 [0.510, 1.000] (n=4) | 1.000 |
| PL_PESEL | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| US_SSN | 2 | 2 | 1.000 [0.342, 1.000] (n=2) | 2 | 0 | 1.000 [0.342, 1.000] (n=2) | 1.000 |
| **all** | 62 | 60 | 0.968 [0.890, 0.991] (n=62) | 60 | 4 | 0.938 [0.850, 0.975] (n=64) | 0.952 |

## Leaks by type

| Type | Gold | Leaked |
|---|---:|---:|
| DATE_OF_BIRTH | 2 | 0 |
| EMAIL_ADDRESS | 9 | 0 |
| EMPLOYEE_ID | 1 | 0 |
| FINANCIAL_PARTIAL | 1 | 0 |
| HOME_ADDRESS | 1 | 0 |
| IN_PAN | 2 | 0 |
| PASSPORT | 1 | 0 |
| PAYMENT_CARD | 1 | 0 |
| PERSON | 36 | 0 |
| PHONE_NUMBER | 4 | 0 |
| PL_PESEL | 2 | 0 |
| US_SSN | 2 | 0 |

## Calibration of the review threshold (TR-DT-30)

Threshold-routed findings n=7 (positives 4), precision target 0.50, 5-fold cross-validation over segments.

| Fold | Fitted threshold | Held-out TP | Held-out FP | Held-out positives |
|---:|---:|---:|---:|---:|
| 1 | 0.600 | 1 | 0 | 1 |
| 2 | 0.600 | 0 | 0 | 0 |
| 3 | 0.600 | 1 | 0 | 1 |
| 4 | 0.600 | 1 | 0 | 1 |
| 5 | 0.600 | 1 | 0 | 1 |

Cross-validated recall 1.000, precision 1.000. Threshold fitted on all items: 0.600 (policy: 0.40). The policy is changed only with `--write-threshold`, and never from synthetic data alone.

## Timing per unit (page, slide or image), seconds

| Stage | p50 | p95 | n jobs |
|---|---:|---:|---:|
| validate | 0.00 | 0.01 | 5 |
| extract | 0.09 | 0.83 | 5 |
| detect | 0.73 | 2.92 | 5 |
| redact | 0.01 | 0.06 | 5 |
| verify | 0.28 | 0.89 | 5 |
| gate | - | - | 0 |

## Method and limitations

- Predictions are findings that redact text (auto-redacted or sent to review); review items count as redacted because they are masked until a reviewer decides.
- Leak search is exact (normalised text, or the digit sequence of numeric values with at least 6 digits) over the re-extracted output (including OCR of output rasters) and the sanitized text. OCR-garbled residues are covered by V2/V3 in the pipeline, not here.
- Region gold without a bounding box matches by page, slide or part.
- Synthetic gold measures the pipeline against invented, planted values; it is a regression signal, not an estimate of real-document accuracy. Real-sample numbers need the annotated gold set (`--samples`).
