# Progress (hand-off file)

Resume by reading `CLAUDE.md`, then this file, then the latest phase report.

| Field | Value |
|---|---|
| Current phase | Phase 3 (extraction): **complete**; Phases 2 and 3 waiting for user review |
| Branch | `main` (no phase branches, ADR-18) |
| Last green commit | tagged `v0.3.0` (see `git log --oneline -1 v0.3.0`) |
| Latest report | [phases/PHASE-03-extract.md](phases/PHASE-03-extract.md) |
| Samples | present in `Data/` (git-ignored, ADR-15) |

## In progress

Nothing. The user reviews Phases 2 and 3 (commands in both reports) before Phase 4.

## Next three steps (Phase 4: deterministic detection)

1. L1 recognizers with validators (TR-DT-10): email, phone (phonenumbers), SSN (900 area
   allowed), PAN holder type, PESEL checksum + masked form, Luhn card, context-required
   passport, configurable employee IDs. Force `tldextract` offline (TR-SEC-01).
2. L2 label-anchored capture with column-header propagation (TR-DT-11) and OCR-confusion
   tolerance (TR-DT-12); partial financial and SSN last-4 rules.
3. Tests: 5+ positives, 5+ negatives and OCR-damaged cases per recognizer; false-positive
   suite on the manifest decoys; types asserted against the planted manifest; sample smoke
   counts by type, and all 16 PPTX mobiles caught by the label-anchored phone rule.

## Open questions

- None blocking. PRD section 13 defaults apply.
- Five PDF unreadable-region candidates (pp. 12, 14, 15, 19, 20) need gold labels to judge.
- EMF/WMF on Linux (Phase 11 Docker check).
