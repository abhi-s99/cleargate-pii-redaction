# Progress (hand-off file)

Resume by reading `CLAUDE.md`, then this file, then the latest phase report.

| Field | Value |
|---|---|
| Current phase | Phase 10 (evaluation harness): **complete**; Phase 11 in progress |
| Branch | `main` (no phase branches, ADR-18) |
| Last green commit | tagged `v0.10.0` (see `git log --oneline -1 v0.10.0`) |
| Latest report | [phases/PHASE-10-eval.md](phases/PHASE-10-eval.md) |
| Samples | present in `Data/` (git-ignored, ADR-15) |

## In progress

Phase 11: hardening (RLIMIT_AS), Docker image and compose, demo script, measured performance.

## Next three steps

1. Phase 11: hardening, Docker, demo script, performance numbers (TR-PF-01..04).
2. User's team: annotate `eval/gold/*.jsonl` (drafts via `make draft-gold`), then
   `make eval-samples` and, if wanted, `--write-threshold` (ADR-33).
3. Stakeholder deck (brief deliverable), outside the code base.

## Open questions

- None blocking. PRD section 13 defaults apply.
