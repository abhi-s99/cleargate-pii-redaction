"""Run the full pipeline on a file set and score it against gold (FR-15, TRD section 9).

``evaluate(files, gold_loader)`` processes the files as one batch in a throw-away data
directory with fresh keys, reloads each job's document and findings from the encrypted
job state, and returns counts only (``JobEval``). Raw values stay in memory.

Scoring rules (documented in the report):

* predictions are findings that redact text (``auto_redact`` or ``review``), regions apart;
* a prediction matching no gold span but whose value equals a gold value of the same file
  and type is a **propagated copy** (the same value elsewhere, ADR-28): neither TP nor FP;
* leak = a gold value (normalised, or its digits for numeric values) found in the
  re-extracted redacted output or the sanitized text;
* calibration items are the threshold-routed findings (``SINGLE_SIGNAL`` / ``LOW``,
  not discarded by a rule, not allowlisted) with their pre-calibration score.
"""

from __future__ import annotations

import json
import re
import secrets
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cryptography.fernet import Fernet
from pydantic import SecretStr

from cleargate.core.config import Policy, Settings, load_policy, load_settings
from cleargate.core.db import MetaStore
from cleargate.core.errors import VaultError
from cleargate.core.models import Document, FileFormat, Finding
from cleargate.ingest.storage import existing_job_dir
from cleargate.pipeline import Pipeline, is_region, load_doc
from cleargate.verify import reextract
from eval.gold import REGION_ENTITY, GoldSet
from eval.metrics import Prf, Scored, Span, norm, overlap_match, strict_match

REDACTING = ("auto_redact", "review")
ROUTED_TIERS = ("SINGLE_SIGNAL", "LOW")
STAGES = ("validate", "extract", "detect", "redact", "verify", "gate")
GoldLoader = Callable[[dict[str, Document]], GoldSet]


@dataclass
class JobEval:
    file: str
    state: str
    rule: str
    units: int
    strict: dict[str, Prf] = field(default_factory=dict)
    overlap: dict[str, Prf] = field(default_factory=dict)
    copies: int = 0
    leaks: dict[str, int] = field(default_factory=dict)  # type -> gold values leaked
    gold_by_type: dict[str, int] = field(default_factory=dict)
    gold_unextracted: int = 0  # gold items whose text was never extracted
    regions_found: int = 0
    regions_gold: int = 0
    keeps_redacted: int = 0
    keeps_total: int = 0
    findings: int = 0
    review: int = 0
    srs: float | None = None
    crs: float | None = None
    stage_s: dict[str, float] = field(default_factory=dict)
    scored: list[Scored] = field(default_factory=list)


@dataclass
class EvalRun:
    source: str
    jobs: list[JobEval]
    excluded: int
    wall_s: float
    policy_threshold: float


def score_of(f: Finding) -> float | None:
    scores = [
        e.raw_score
        for e in f.evidence
        if e.raw_score is not None and not e.rule_id.startswith("merged:")
    ]
    return max(scores) if scores else None


def timing_units(doc: Document) -> int:
    """Pages (PDF), slides (PPTX), frames (image); a DOCX has no pages and counts as 1."""
    u = doc.units
    return int(u.get("pages") or u.get("slides") or u.get("images") or 1)


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _region_match(f: Finding, kind: str, loc: dict[str, Any]) -> bool:
    if f.entity_type.value != REGION_ENTITY.get(kind) or f.locator is None:
        return False
    fl = f.locator
    if "page" in loc and fl.page != loc["page"]:
        return False
    if "slide" in loc and fl.slide != loc["slide"]:
        return False
    if "part_prefix" in loc and not fl.part.startswith(loc["part_prefix"]):
        return False
    if "part" in loc and fl.part != loc["part"]:
        return False
    if "bbox" in loc and fl.bbox is not None:
        a, b = loc["bbox"], fl.bbox
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return union > 0 and inter / union >= 0.5
    return True


def score_job(
    file: str,
    doc: Document,
    findings: list[Finding],
    gold: GoldSet,
    hay: str,
    hay_digits: str,
) -> JobEval:
    je = JobEval(file=file, state="", rule="", units=timing_units(doc))
    items = [g for g in gold.items if g.file == file]
    preds = [
        Span(f.segment_id, f.start, f.end, f.entity_type.value, f.value)
        for f in findings
        if f.decision in REDACTING and not is_region(f)
    ]
    gold_values = {(g.entity_type, norm(g.value)) for g in items if g.value}
    for mode, match, table in (
        ("strict", strict_match, je.strict),
        ("overlap", overlap_match, je.overlap),
    ):
        for g in items:
            prf = table.setdefault(g.entity_type, Prf())
            prf.gold += 1
            prf.found += any(match(s, p) for s in g.spans for p in preds)
        for p in preds:
            prf = table.setdefault(p.entity_type, Prf())
            if any(match(s, p) for g in items for s in g.spans):
                prf.tp += 1
            elif (p.entity_type, norm(p.text)) in gold_values:
                if mode == "overlap":
                    je.copies += 1
            else:
                prf.fp += 1
    for g in items:
        je.gold_by_type[g.entity_type] = je.gold_by_type.get(g.entity_type, 0) + 1
        je.gold_unextracted += not g.spans
        v = norm(g.value)
        d = digits(g.value)
        leaked = bool(v) and (v in hay or (len(d) >= 6 and d == digits(v) and d in hay_digits))
        if leaked:
            je.leaks[g.entity_type] = je.leaks.get(g.entity_type, 0) + 1
    regions = [f for f in findings if is_region(f) and f.decision in REDACTING]
    for r in (r for r in gold.regions if r.file == file):
        je.regions_gold += 1
        je.regions_found += any(_region_match(f, r.kind, r.locator) for f in regions)
    pred_texts = [norm(p.text) for p in preds]
    for k in (k for k in gold.keeps if k.file == file):
        je.keeps_total += 1
        je.keeps_redacted += any(norm(k.value) in t for t in pred_texts)
    live = [f for f in findings if f.decision in REDACTING]
    je.findings = len(live)
    je.review = sum(1 for f in live if f.decision == "review")
    for f in findings:
        if f.tier not in ROUTED_TIERS or f.decision not in ("review", "discarded"):
            continue
        if any(e.rule_id.startswith("discard:") for e in f.evidence) or is_region(f):
            continue
        s = score_of(f)
        if s is None:
            continue
        span = Span(f.segment_id, f.start, f.end, f.entity_type.value, f.value)
        positive = (
            any(overlap_match(g, span) for it in items for g in it.spans)
            or (
                span.entity_type,
                norm(span.text),
            )
            in gold_values
        )
        je.scored.append(Scored(f.segment_id, s, positive))
    return je


def make_settings(root: Path) -> Settings:
    base = load_settings({})
    return Settings(
        data_dir=root,
        vault_key=SecretStr(Fernet.generate_key().decode()),
        gate_key=SecretStr(secrets.token_urlsafe(32)),
        tesseract_cmd=base.tesseract_cmd,
        ocr_workers=base.ocr_workers,
    )


def output_texts(
    settings: Settings, policy: Policy, job_id: str, jdir: Path, fmt: FileFormat
) -> tuple[str, str]:
    texts: list[str] = []
    out = next((jdir / "out").glob("redacted.*"), None)
    if out is not None:
        ctx = SimpleNamespace(settings=settings, policy=policy, job_id=job_id)
        hay, _missed = reextract.haystacks(out, fmt, ctx)
        texts += hay
        reextract.RASTERS.pop(job_id, None)
    sanitized = jdir / "out" / "sanitized.txt"
    if sanitized.is_file():
        texts.append(sanitized.read_text(encoding="utf-8"))
    joined = "\n".join(texts)
    return norm(joined), digits(joined)


def evaluate(
    files: Sequence[Path], gold_loader: GoldLoader, policy: Policy | None = None
) -> EvalRun:
    policy = policy or load_policy()
    with tempfile.TemporaryDirectory(prefix="cleargate-eval-") as tmp:
        settings = make_settings(Path(tmp))
        store = MetaStore.open(settings.data_dir / "meta.db")
        pipeline = Pipeline(settings, policy, store)
        try:
            start = time.perf_counter()
            batch = pipeline.process_batch(list(files))
            wall = time.perf_counter() - start
            loaded: dict[str, tuple[Any, Document, list[Finding]]] = {}
            for job in batch.jobs:
                jdir = existing_job_dir(settings.data_dir, job.job_id)
                try:
                    doc, findings = load_doc(pipeline.vault.load_state(jdir))
                except VaultError:  # a FAILED job has no state: scored as all missed
                    continue
                loaded[job.filename] = (job, doc, findings)
            gold = gold_loader({name: doc for name, (_, doc, _) in loaded.items()})
            jobs: list[JobEval] = []
            for job in batch.jobs:
                if job.filename not in loaded:
                    je = JobEval(job.filename, job.state.value, job.rule, 0)
                    jobs.append(je)
                    continue
                _, doc, findings = loaded[job.filename]
                jdir = existing_job_dir(settings.data_dir, job.job_id)
                hay, hay_digits = output_texts(settings, policy, job.job_id, jdir, doc.fmt)
                je = score_job(job.filename, doc, findings, gold, hay, hay_digits)
                je.state, je.rule = job.state.value, job.rule
                run = store.run(job.job_id)
                if run is not None:
                    rep = json.loads(run["report_json"])
                    je.srs, je.crs = rep.get("srs"), rep.get("crs")
                    timings = json.loads(run["timings_json"])
                    je.stage_s = {s: float(timings[s]) for s in STAGES if s in timings}
                jobs.append(je)
        finally:
            pipeline.close()
            store.close()
    return EvalRun(
        gold.source if loaded else "none",
        jobs,
        gold.excluded if loaded else 0,
        wall,
        policy.detection.review_threshold,
    )
