# Progress (hand-off file)

Resume by reading `CLAUDE.md`, then this file, then the latest phase report.

| Field | Value |
|---|---|
| Current phase | Phase 11 (hardening, Docker, demo): **complete**; all build phases done |
| Branch | `main` (no phase branches, ADR-18) |
| Last green commit | tagged `v0.11.0` (see `git log --oneline -1 v0.11.0`) |
| Latest report | [phases/PHASE-11-hardening.md](phases/PHASE-11-hardening.md) |
| Samples | present in `Data/` (git-ignored, ADR-15) |

## In progress

Nothing. All phases are done; the items below need the user or their team.

## Next three steps

1. User's team: annotate `eval/gold/*.jsonl` (drafts via `make draft-gold`), then
   `make eval-samples` and, if wanted, `--write-threshold` (ADR-33).
2. TR-PF-02: the DOCX sample took 199 s against 180 s; profile the image OCR path.
3. Stakeholder deck and `REFERENCE_GAP_ANALYSIS.md` (brief deliverables).

## Open questions

- None blocking. PRD section 13 defaults apply.
