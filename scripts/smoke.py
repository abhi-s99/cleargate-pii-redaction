"""Sample smoke run: python scripts/smoke.py [--data-dir out/smoke-data]

Runs the full pipeline on the three real sample files and writes tables
table (file, state, rule, reason, units, segments by method, regions, uninspected
parts, time) to out/smoke.md. Counts, types, pages and codes only: no document values.

The leak grep against eval/gold/ runs once gold labels exist (Phase 10); until then
the report says so.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cleargate.core.config import load_env_file, load_policy, load_settings  # noqa: E402
from cleargate.core.db import MetaStore  # noqa: E402
from cleargate.core.models import Document  # noqa: E402
from cleargate.pipeline import JobContext, Pipeline, default_stages  # noqa: E402
from tests.conftest import SAMPLE_FILES, find_samples_dir  # noqa: E402

STAGES = ("validate", "extract", "detect", "redact", "verify", "gate")


def stage_seconds(timings: dict[str, float]) -> float:
    return sum(timings.get(s, 0.0) for s in STAGES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "out" / "smoke-data")
    args = parser.parse_args(argv)
    samples = find_samples_dir()
    if samples is None:
        print("smoke: sample files not present (samples/ or Data/); nothing to run")
        return 0
    load_env_file(ROOT / ".env")
    settings = load_settings().model_copy(update={"data_dir": args.data_dir})
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    policy = load_policy(settings.policy_path)
    store = MetaStore.open(settings.data_dir / "meta.db")
    stages = default_stages()
    docs: dict[str, Document] = {}
    for ex in stages.extractors:
        original = ex.extract

        def recording(path: Path, fmt: object, ctx: JobContext, _orig=original) -> Document:
            doc = _orig(path, fmt, ctx)
            docs[ctx.job_id] = doc
            return doc

        ex.extract = recording  # type: ignore[method-assign]
    pipeline = Pipeline(settings, policy, store, stages=stages)
    start = time.perf_counter()
    batch = pipeline.process_batch([samples / name for name in SAMPLE_FILES])
    wall = time.perf_counter() - start
    rows = [
        "| File | State | Rule | Reason | Units | Segments (native/ocr) | Regions | "
        "Uninspected | Time (s) |",
        "|---|---|---|---|---|---|---|---|---:|",
    ]
    for job in batch.jobs:
        doc = docs.get(job.job_id)
        units = json.dumps(doc.units, sort_keys=True) if doc else "-"
        native = sum(1 for s in doc.segments if s.method == "native") if doc else 0
        ocr = sum(1 for s in doc.segments if s.method == "ocr") if doc else 0
        regions: dict[str, int] = {}
        for r in doc.regions if doc else []:
            regions[r.kind] = regions.get(r.kind, 0) + 1
        codes: dict[str, int] = {}
        for i in doc.coverage.issues if doc else []:
            codes[i.code] = codes.get(i.code, 0) + 1
        rows.append(
            f"| {job.filename} | {job.state.value} | {job.rule} | {job.reason} | {units} | "
            f"{native}/{ocr} | {json.dumps(regions, sort_keys=True)} | "
            f"{json.dumps(codes, sort_keys=True)} | {stage_seconds(job.timings):.1f} |"
        )
    region_pages = {
        job.filename: sorted(
            {(r.kind, r.locator.page) for r in docs[job.job_id].regions if r.locator.page}
        )
        for job in batch.jobs
        if job.job_id in docs
    }
    ocr_timing = {
        j.filename: {k: v for k, v in j.timings.items() if k.startswith("ocr_")}
        for j in batch.jobs
        if "ocr_pages" in j.timings
    }
    detail = [
        "| File | Redacted by type | Tiers (redacted) | Review items | Actions applied/total | "
        "V2 leaks | V3 det/other | V4 uninspected | SRS | CRS |",
        "|---|---|---|---:|---|---:|---|---:|---:|---:|",
    ]
    for job in batch.jobs:
        rows_f = store.findings(job.job_id)
        red = [r for r in rows_f if r["decision"] in ("auto_redact", "review")]
        by_type: dict[str, int] = {}
        tiers: dict[str, int] = {}
        for r in red:
            by_type[r["entity_type"]] = by_type.get(r["entity_type"], 0) + 1
            tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        review = sum(1 for r in rows_f if r["decision"] == "review")
        run = store.run(job.job_id)
        if run is None:
            detail.append(f"| {job.filename} | - | - | - | - | - | - | - | - | - |")
            continue
        rep = json.loads(run["report_json"])
        acts = json.loads(run["actions_json"])
        applied = sum(1 for a in acts if a["applied"])
        detail.append(
            f"| {job.filename} | {json.dumps(by_type, sort_keys=True)} | "
            f"{json.dumps(tiers, sort_keys=True)} | {review} | {applied}/{len(acts)} | "
            f"{rep['leak_hits']} | {rep['residual_deterministic']}/{rep['residual_other']} | "
            f"{rep['uninspected_unmasked']} | {rep['srs']} | {rep['crs']} |"
        )
    stamp = datetime.now(tz=UTC).isoformat(timespec="seconds")
    gold = ROOT / "eval" / "gold"
    leak = (
        "leak grep: eval/gold/ present, see Phase 10 tooling"
        if gold.is_dir()
        else "leak grep: not run (no eval/gold/ labels yet, Phase 10)"
    )
    text = "\n".join(
        [
            "# Sample smoke",
            "",
            f"Generated {stamp}. CPU count {os.cpu_count()}, OCR workers {settings.ocr_workers}, "
            f"batch wall time {wall:.1f} s. Counts only, no document values.",
            "",
            *rows,
            "",
            *detail,
            "",
            "Region pages (kind, page): " + json.dumps(region_pages),
            "",
            "OCR timing (seconds): " + json.dumps(ocr_timing),
            "",
            leak,
            "",
        ]
    )
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "smoke.md").write_text(text, encoding="utf-8")
    store.close()
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
