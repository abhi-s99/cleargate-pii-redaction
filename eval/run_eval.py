"""Evaluation entry point: ``python -m eval.run_eval`` (FR-15, TRD sections 6.4, 9 and 14).

Default: the synthetic fixtures scored against the planted-PII manifest, report written to
``eval/report.md`` (invented values only; the report holds counts and metrics, never
values). ``--samples``: the real case files scored against the annotators' labels in
``eval/gold/*.jsonl``; the report goes to ``out/eval-samples.md`` (git-ignored) and the
run refuses to start without gold. ``--write-threshold`` writes the calibrated review
threshold into the policy file (opt-in, changes the policy hash).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from cleargate.core.config import REPO_ROOT, load_env_file, load_policy, policy_hash
from eval.calibrate import DEFAULT_K, DEFAULT_TARGET, Calibration, calibrate, write_threshold
from eval.gold import from_jsonl, from_manifest
from eval.harness import STAGES, EvalRun, JobEval
from eval.metrics import Prf, fmt, fmt_ci, percentile

SYNTHETIC = REPO_ROOT / "tests" / "fixtures" / "synthetic"
SYNTHETIC_FILES = (
    "planted.docx",
    "planted.pptx",
    "planted_native.pdf",
    "planted_scanned.pdf",
    "planted.png",
)
GOLD_DIR = REPO_ROOT / "eval" / "gold"
POLICY = REPO_ROOT / "config" / "policy.default.yaml"


def totals(jobs: Sequence[JobEval], mode: str) -> dict[str, Prf]:
    out: dict[str, Prf] = {}
    for je in jobs:
        for t, prf in getattr(je, mode).items():
            out.setdefault(t, Prf()).add(prf)
    return out


def prf_table(table: dict[str, Prf]) -> list[str]:
    rows = [
        "| Type | Gold | Found | Recall [95% CI] | Pred TP | Pred FP | Precision [95% CI] | F1 |",
        "|---|---:|---:|---|---:|---:|---|---:|",
    ]
    overall = Prf()
    for t in sorted(table):
        p = table[t]
        overall.add(p)
        rows.append(
            f"| {t} | {p.gold} | {p.found} | {fmt_ci(p.found, p.gold)} | {p.tp} | {p.fp} | "
            f"{fmt_ci(p.tp, p.tp + p.fp)} | {fmt(p.f1)} |"
        )
    o = overall
    rows.append(
        f"| **all** | {o.gold} | {o.found} | {fmt_ci(o.found, o.gold)} | {o.tp} | {o.fp} | "
        f"{fmt_ci(o.tp, o.tp + o.fp)} | {fmt(o.f1)} |"
    )
    return rows


def render(run: EvalRun, cal: Calibration, policy_name: str, phash: str) -> str:
    jobs = run.jobs
    gold_n = sum(sum(j.gold_by_type.values()) for j in jobs)
    leaked = sum(sum(j.leaks.values()) for j in jobs)
    failed = sum(1 for j in jobs if j.state == "FAILED")
    findings = sum(j.findings for j in jobs)
    review = sum(j.review for j in jobs)
    regions_found = sum(j.regions_found for j in jobs)
    regions_gold = sum(j.regions_gold for j in jobs)
    keeps_red = sum(j.keeps_redacted for j in jobs)
    keeps_n = sum(j.keeps_total for j in jobs)
    stamp = datetime.now(tz=UTC).isoformat(timespec="seconds")
    lines = [
        "# Evaluation report",
        "",
        f"Generated {stamp} by `python -m eval.run_eval`. Gold: {run.source}. "
        f"Policy `{policy_name}` hash `{phash[:16]}`, review threshold "
        f"{run.policy_threshold:.2f}. CPU count {os.cpu_count()}. Batch wall time "
        f"{run.wall_s:.1f} s. Counts and metrics only, no document values.",
        "",
        "Intervals are 95 % Wilson score intervals; n is shown with every rate. With this "
        "few documents every number is weak evidence (TRD 6.4).",
        "",
        "## Headline (PS-2 targets)",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| Leak rate (gold values in any output) | {fmt_ci(leaked, gold_n)} | 0 |",
        f"| Recall, overlap match | {fmt_ci(*_found(totals(jobs, 'overlap')))} | high |",
        f"| Region recall (faces, unreadable) | {fmt_ci(regions_found, regions_gold)} | 1.0 |",
        f"| Business terms redacted (FP on keep-list) | {fmt_ci(keeps_red, keeps_n)} | 0 |",
        f"| Review load (review items / findings) | {fmt_ci(review, findings)} | low |",
        f"| Error rate (FAILED / jobs) | {fmt_ci(failed, len(jobs))} | 0 |",
        f"| SRS min over jobs | {fmt(_min(j.srs for j in jobs))} | >= 0.80 |",
        f"| CRS min over jobs | {fmt(_min(j.crs for j in jobs))} | >= 0.80 |",
        "",
        "## Per job",
        "",
        "| File | State | Rule | Units | Gold | Not extracted | Leaked | Findings | Review | "
        "Regions found/gold | Keep-list redacted | SRS | CRS |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|",
    ]
    for j in jobs:
        lines.append(
            f"| {j.file} | {j.state} | {j.rule} | {j.units} | {sum(j.gold_by_type.values())} | "
            f"{j.gold_unextracted} | {sum(j.leaks.values())} | {j.findings} | {j.review} | "
            f"{j.regions_found}/{j.regions_gold} | {j.keeps_redacted}/{j.keeps_total} | "
            f"{fmt(j.srs)} | {fmt(j.crs)} |"
        )
    lines += [
        "",
        "## Detection, overlap match (character IoU >= 0.5, same type)",
        "",
        *prf_table(totals(jobs, "overlap")),
        "",
        f"Propagated copies (same value as a gold item at another location, neither TP nor "
        f"FP): {sum(j.copies for j in jobs)}. Gold items without a text channel "
        f"(image-only), not span-scored: {run.excluded}.",
        "",
        "## Detection, strict match (same offsets or same normalised text)",
        "",
        *prf_table(totals(jobs, "strict")),
        "",
        "## Leaks by type",
        "",
        "| Type | Gold | Leaked |",
        "|---|---:|---:|",
    ]
    gold_types: dict[str, int] = {}
    leak_types: dict[str, int] = {}
    for j in jobs:
        for t, n in j.gold_by_type.items():
            gold_types[t] = gold_types.get(t, 0) + n
        for t, n in j.leaks.items():
            leak_types[t] = leak_types.get(t, 0) + n
    lines += [f"| {t} | {gold_types[t]} | {leak_types.get(t, 0)} |" for t in sorted(gold_types)]
    lines += [
        "",
        "## Calibration of the review threshold (TR-DT-30)",
        "",
        f"Threshold-routed findings n={cal.n} (positives {cal.positives}), precision target "
        f"{cal.target:.2f}, {len(cal.folds)}-fold cross-validation over segments.",
        "",
        "| Fold | Fitted threshold | Held-out TP | Held-out FP | Held-out positives |",
        "|---:|---:|---:|---:|---:|",
        *[
            f"| {i + 1} | {f.threshold:.3f} | {f.tp} | {f.fp} | {f.positives} |"
            for i, f in enumerate(cal.folds)
        ],
        "",
        f"Cross-validated recall {fmt(cal.cv_recall)}, precision {fmt(cal.cv_precision)}. "
        f"Threshold fitted on all items: {cal.threshold:.3f} (policy: "
        f"{run.policy_threshold:.2f}). The policy is changed only with `--write-threshold`, "
        "and never from synthetic data alone.",
        "",
        "## Timing per unit (PDF page, slide, image frame; a DOCX counts as one unit), seconds",
        "",
        "| Stage | p50 | p95 | n jobs |",
        "|---|---:|---:|---:|",
    ]
    for s in STAGES:
        per = [j.stage_s[s] / j.units for j in jobs if s in j.stage_s and j.units]
        lines.append(
            f"| {s} | {fmt(percentile(per, 50), 2)} | {fmt(percentile(per, 95), 2)} | {len(per)} |"
        )
    lines += [
        "",
        "## Method and limitations",
        "",
        "- Predictions are findings that redact text (auto-redacted or sent to review); "
        "review items count as redacted because they are masked until a reviewer decides.",
        "- Leak search is exact (normalised text, or the digit sequence of numeric values "
        "with at least 6 digits) over the re-extracted output (including OCR of output "
        "rasters) and the sanitized text. OCR-garbled residues are covered by V2/V3 in the "
        "pipeline, not here.",
        "- Region gold without a bounding box matches by page, slide or part.",
        "- Synthetic gold measures the pipeline against invented, planted values; it is a "
        "regression signal, not an estimate of real-document accuracy. Real-sample numbers "
        "need the annotated gold set (`--samples`).",
        "",
    ]
    return "\n".join(lines)


def _found(table: dict[str, Prf]) -> tuple[int, int]:
    return sum(p.found for p in table.values()), sum(p.gold for p in table.values())


def _min(values: object) -> float | None:
    vals = [v for v in values if v is not None]  # type: ignore[attr-defined]
    return min(vals) if vals else None


def _shown(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def main(argv: list[str] | None = None) -> int:
    from eval.harness import evaluate
    from tests.conftest import SAMPLE_FILES, find_samples_dir

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", action="store_true", help="real samples + eval/gold/")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--precision-target", type=float, default=DEFAULT_TARGET)
    parser.add_argument("--folds", type=int, default=DEFAULT_K)
    parser.add_argument("--write-threshold", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(REPO_ROOT / ".env")
    policy = load_policy()
    if args.samples:
        samples = find_samples_dir()
        if samples is None or not any(GOLD_DIR.glob("*.jsonl")):
            print("eval: --samples needs the sample files and eval/gold/*.jsonl labels")
            return 2
        files = [samples / n for n in SAMPLE_FILES]
        run = evaluate(files, lambda docs: from_jsonl(docs, GOLD_DIR), policy)
        out = args.out or REPO_ROOT / "out" / "eval-samples.md"
    else:
        files = [SYNTHETIC / n for n in SYNTHETIC_FILES]
        run = evaluate(files, lambda docs: from_manifest(docs, SYNTHETIC), policy)
        out = args.out or REPO_ROOT / "eval" / "report.md"
    cal = calibrate([s for j in run.jobs for s in j.scored], args.precision_target, args.folds)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render(run, cal, policy.policy_name, policy_hash(policy)), encoding="utf-8", newline="\n"
    )
    leaked = sum(sum(j.leaks.values()) for j in run.jobs)
    print(f"eval: {len(run.jobs)} jobs, leaks {leaked}, report {_shown(out)}")
    if args.write_threshold:
        if not args.samples:
            print("eval: refusing to write a threshold fitted on synthetic data only")
            return 2
        write_threshold(POLICY, cal.threshold)
        print(f"eval: review_threshold set to {cal.threshold:.2f} in {POLICY.name}")
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    raise SystemExit(main())
