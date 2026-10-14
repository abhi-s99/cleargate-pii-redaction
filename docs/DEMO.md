# Demo script (live walkthrough, about 12 minutes)

For the stakeholder session (PRD 10). Runs on one laptop, offline. Show counts and the
redacted files only; never read sample values aloud or paste them anywhere.

## Before the session (once, 10 minutes ahead)

1. Start the service, either way:
   - local: `.venv\Scripts\python.exe -m cleargate.cli serve` (UI built with `make ui`);
   - Docker: `docker compose up -d` (first build about 10 minutes, see README).
2. Open http://127.0.0.1:8000, connect as **Privacy Reviewer** with
   `CLEARGATE_REVIEWER_TOKEN` from `.env`, tick **persist in tab**.
3. **Pre-warm the OCR cache** (PRD risk "OCR time makes the demo slow"): upload the PDF
   once and let it finish (3 to 4 minutes on 12 CPUs). OCR results are cached encrypted,
   keyed by page pixels, so the live run of the same file is fast. Leave this job; it also
   serves as a fallback.
4. Have the three sample files and `eval/report.md` at hand.

## Walkthrough

| Time | Step | What to say / show |
|---|---|---|
| 0:00 | Architecture slide | Fail closed: nothing reaches the AI unless every gate rule passes; detection, writers and an independent verifier are separate. |
| 1:30 | Upload the three files as one batch | Validation (type sniffing, zip-bomb and XXE limits), one batch so tokens stay consistent across files. |
| 2:30 | Batch page | Per-file progress (per OCR page). PPTX finishes first. |
| 3:30 | PPTX job, Overview tab | Entity counts by type, tiers, the deciding rule (G6: open review items). Downloads are disabled: show that the API refuses them (403) before SAFE. |
| 5:00 | Review workspace (PPTX, 3 items) | Evidence per item, masked preview, segment context; confirm. HIGH-risk deterministic items cannot be rejected. Submit and re-verify. |
| 6:30 | PPTX reaches **Validated safe** | Download the redacted PPTX and open it: layout kept, names, emails and phones replaced by typed tokens; the same person has the same token across files. |
| 8:00 | AI Handoff tab | The mock agent receives sanitized text only through a signed SafeHandle; it reports "personal data seen only as tokens". |
| 9:00 | DOCX or PDF job | Larger review queue (uncertain names go to a human by design); masked screenshot regions; show the report (counts, no values). |
| 10:30 | `eval/report.md` | Leak rate 0 with its interval, recall, review load, SRS/CRS; synthetic gold is a regression signal, real-sample gold is pending (ADR-33). |
| 11:30 | Limits | No scanner proves zero PII; OCR ceiling; prototype security (static tokens, single tenant). |

## Fallbacks

- PDF still running: use the pre-warmed job from step 3.
- Browser token lost after reload: reconnect with **persist in tab** ticked.
- Anything fails: the job ends `FAILED` or `BLOCKED`, which is itself the point: show
  the deciding rule and reason on the job page.
