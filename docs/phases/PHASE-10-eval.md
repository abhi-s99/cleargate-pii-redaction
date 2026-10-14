# Phase 10: Evaluation harness and calibration
Tag: v0.10.0 · Date: 14 Oct 2026 · Branch: `main` (ADR-18)

## What was built            (requirements covered: FR-15, TR-DT-30, FR-07)
- `eval/metrics.py`: Wilson 95 % intervals, strict and overlap (IoU >= 0.5) span matching,
  precision / recall / F1, threshold fitting, k-fold by segment, percentiles.
- `eval/gold.py`: gold from the synthetic manifest or from `eval/gold/*.jsonl` (TRD 9
  format, resolved by segment SHA-256 and locator), with keep-list terms and regions.
- `eval/harness.py`: runs the full pipeline as one batch in a throw-away data directory,
  reloads each job's encrypted state, scores detection, leaks (re-extracted output and
  sanitized text), regions, keep-list false positives, review load, error rate, SRS/CRS,
  stage timings, and collects the score-routed findings for calibration.
- `eval/calibrate.py`: fits `review_threshold`, held-out folds, opt-in policy write.
- `eval/run_eval.py` (`make eval`): writes `eval/report.md`; `--samples` for real gold.
- `eval/draft_gold.py`: value-free draft gold files for annotators (git-ignored).

## Files added / changed
- `eval/{metrics,gold,harness,calibrate,run_eval,draft_gold}.py`: as above.
- `eval/report.md`: synthetic evaluation report (counts and metrics only).
- `tests/unit/test_eval.py`, `tests/integration/test_eval_harness.py`: new tests.
- `docs/VERIFICATION.md`: Phase 6 to 10 rows filled; `docs/DECISIONS.md`: ADR-33.

## How to verify (copy-paste)
```powershell
.venv\Scripts\python.exe -m eval.run_eval            # expect: eval: 5 jobs, leaks 0, report eval\report.md
.venv\Scripts\python.exe -m pytest tests/unit/test_eval.py tests/integration/test_eval_harness.py -q
.venv\Scripts\python.exe -m pytest -m "not samples and not slow" -q
```

## Actual results
- `python -m eval.run_eval`: `eval: 5 jobs, leaks 0, report eval\report.md` (19 s, OCR
  cache warm).
- Eval tests: `18 passed in 45.50s`. Fast suite: `827 passed, 14 deselected`. mypy:
  `Success: no issues found in 73 source files`. `check_matrix`: 0 problems
  (PASS 68, PARTIAL 23, TODO 6). `check_style`: 0 violations.
- Synthetic metrics (`eval/report.md`, gold = planted manifest, n = 62 text items, 4
  regions, 7 keep-list terms):

| Metric | Value [95% CI] |
|---|---|
| Leak rate | 0.000 [0.000, 0.058] (n=62) |
| Recall, overlap | 1.000 [0.942, 1.000] (n=62) |
| Precision, overlap | 0.969 [0.893, 0.991] (n=64) |
| Recall, strict | 0.968 [0.890, 0.991] (n=62) |
| Region recall | 1.000 [0.510, 1.000] (n=4) |
| Keep-list terms redacted | 0.000 [0.000, 0.354] (n=7) |
| Review load | 0.058 [0.023, 0.140] (n=69) |
| SRS / CRS min | 1.000 / 1.000 |

- Calibration on synthetic data: n = 7 score-routed findings, fitted threshold 0.60,
  held-out recall 1.0; not written to the policy (ADR-33).

## Deviations from spec
- ADR-33: one calibrated threshold (the only score-routed boundary); never fitted on
  synthetic data; propagated copies counted apart.

## Known gaps / risks carried forward
- Real-sample metrics need the annotated gold set (`eval/gold/*.jsonl`); `python -m
  eval.draft_gold` prepares drafts. Until then `review_threshold` stays 0.40 and the
  real-sample review load is uncalibrated. Inter-annotator agreement is not measured.
- CER on hand-transcribed OCR pages (TRD 9) is not implemented (needs transcriptions).

## Next phase entry criteria
- Eval runs green on synthetic data; Phase 11 adds hardening, Docker and the demo script.
