# Progress (hand-off file)

Resume by reading `CLAUDE.md`, then this file, then the latest phase report.

| Field | Value |
|---|---|
| Current phase | Phase 9 (web UI integrated): **complete**; Phases 6-9 waiting for user review |
| Branch | `main` (no phase branches, ADR-18) |
| Last green commit | tagged `v0.9.0` (see `git log --oneline -1 v0.9.0`) |
| Latest report | [phases/PHASE-09-ui.md](phases/PHASE-09-ui.md) |
| Samples | present in `Data/` (git-ignored, ADR-15) |

## In progress

Nothing. The user tests the UI manually (upload, review, download).

## Next three steps

1. Phase 10: evaluation harness (gold labels by the user's team).
2. Phase 11: hardening, Docker, demo script.
3. Update VERIFICATION.md rows for Phases 6-9 (tests exist; rows still TODO).

## Open questions

- None blocking. PRD section 13 defaults apply.
