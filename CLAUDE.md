# CLAUDE.md: working rules for ClearGate

ClearGate is a fail-closed privacy gate between business documents and an AI model
(Optiv PS-2 case study, Cadence Financial Group). Specs live in `docs/`:
`TRD.md` (primary spec, TR-xx IDs), `Architecture.md` (ADR-01..13, the why),
`PRD.md` (scope, FR-xx, cut line), `DECISIONS.md` (ADR-14 onwards, deviations).
Precedence: Optiv brief > TRD > Architecture > PRD > README. Never quietly deviate:
add an ADR to `docs/DECISIONS.md`, mention it in the phase report, make the smallest change.

## Resume protocol

Read this file, then `docs/PROGRESS.md`, then the latest `docs/phases/PHASE-NN-*.md`.
Keep a task list per phase. Update `docs/PROGRESS.md` before every commit that ends a
work chunk. Pause at the end of every phase and wait for "continue". Also pause and ask
when: samples are missing; a dependency or system package will not install; an ADR or
gate rule must change; a PRD section 13 question truly blocks (else use its default).
If a step fails three times, stop, write down what was tried, and ask.

## Project style rules (user instruction, enforced by `scripts/check_style.py`)

- **No emoji anywhere in the project.** Status words instead: PASS, PARTIAL, XFAIL, TODO,
  Yes/No. The TRD's raw-content marker is written `[RAW]`.
- **No em dashes anywhere.** Use a colon, comma, parentheses or a plain hyphen.
- When writing such characters in code (tests of the checker), build them with `chr()`;
  editor tools may turn `\uXXXX` escapes into literal characters.

## Non-negotiables

1. **Fail closed.** Nothing becomes `VALIDATED_SAFE` unless every gate rule in TRD 8.2
   passes. Unread page, unapplied redaction, verification crash or missing model must end
   non-safe, and each path has a test.
2. **No raw PII outside memory and the encrypted vault**: not in `meta.db`, logs, reports,
   exceptions, snapshots or commit messages (TR-SEC-02/03). Raw model fields use
   `raw_field()` (excluded from dumps and repr).
3. **No network at runtime.** Tests run with sockets blocked (`--disable-socket`). LLM client
   disabled; default handoff target is the local `MockAgent`.
4. **No overlays.** Redaction is burned into pixels or removed from content/XML (ADR-07).
5. **Never weaken a test, threshold or gate rule to pass.** Real limitation: keep the test,
   mark `xfail(strict=True, reason=...)`, report it.
6. **Never claim something works without running it.** Every PASS in a report has the
   command and its real output next to it.
7. **Stay in scope** (PRD cut line). No microservices, Celery, cloud OCR, model training,
   logo detection, "security insight generation".

## Confidentiality

- Real samples live in `Data/` or `samples/` (both git-ignored; tests also honour
  `CLEARGATE_SAMPLES_DIR`). Gold labels in `eval/gold/`, generated reports in `out/`:
  git-ignored. Never commit sample files or any value from them.
- Committed tests use synthetic fixtures with invented values. Real-sample tests are
  `@pytest.mark.samples` and skip when the files are absent.
- Committed reports give counts, types, pages and metrics, never values.
- Never write the real organisation visible in the DOCX screenshots into anything.
- The GitHub remote is private (checked: unauthenticated API returns 404). Never push to a
  public repository.

## Git workflow (user instruction overrides the brief's branch rules)

- Work directly on `main`: commit and push to `origin main`. **No phase branches.**
  Tag the last commit of each phase `v0.NN.0` and push tags.
- Small atomic commits; the suite passes at every commit (verify with
  `git stash push --keep-index --include-untracked` before committing a partial stage).
- Conventional Commits, first line <= 50 chars, imperative, lowercase, no period:
  `<type>(<scope>): <subject>`. Types: feat fix test refactor perf docs chore build ci.
  Scopes: core gate ingest extract ocr detect redact vault verify api ui report eval cli
  config deps docs phase. Optional body (max 3 short lines) cites requirement IDs.
- No `Co-Authored-By` trailer or any other AI attribution in commit messages (user
  instruction, 2026-10-14; older commits keep theirs, history is not rewritten).

## Verification protocol (every phase)

1. `make lint`: ruff check, ruff format --check, mypy (strict on core, gate, verify).
2. Unit tests for new code: positive, negative, edge; recognizers also OCR-damaged cases.
3. `make test` (`pytest -m "not samples and not slow"`) green across all phases. Never
   delete or skip an older test.
4. Cross-checks for existing stages: planted-PII round trip against the synthetic manifest
   (from Phase 3), differential checks between two independent paths, fault injection for
   every Architecture section 6 failure path, hypothesis property tests.
5. `make smoke` on the real samples (from Phase 3): table to `out/smoke.md`, leak grep
   against `eval/gold/` once gold exists.
6. Update `docs/VERIFICATION.md` (every touched TR-/FR- ID). `make check` runs lint, tests,
   `scripts/check_matrix.py` and `scripts/check_style.py`.
7. Write `docs/phases/PHASE-NN-<name>.md`; update README status table, `CHANGELOG.md`,
   `docs/PROGRESS.md`.
8. Commit the report, tag, push.

## Phase report template (`docs/phases/PHASE-NN-<name>.md`)

```
# Phase NN: <name>
Tag: v0.NN.0 · Date: <date>
## What was built            (requirements covered: TR-.., FR-..)
## Files added / changed     (path: purpose)
## How to verify (copy-paste) (exact commands, expected output)
## Actual results            (static checks, pytest summary line, cross-checks,
                              sample smoke table without values, metrics with n and intervals)
## Deviations from spec      (none | ADR-xx: one line)
## Known gaps / risks carried forward
## Next phase entry criteria
```

## Environment notes

- Windows 11, Python 3.13.15 venv in `.venv` (`.venv/Scripts/python.exe`), GNU make from
  winget (`ezwinports.make`), Tesseract 5.4.0 at `C:\Program Files\Tesseract-OCR`
  (override with `CLEARGATE_TESSERACT_CMD`). Local keys in `.env` (`make keys`).
- `python -I` is used for one-off scripts that touch sample files; print counts only.
