"""Pipeline orchestrator: validate -> extract -> detect -> redact -> verify -> gate.

``Pipeline.process_batch`` creates a batch and runs two phases (ADR-29):

1. ``submit`` per file: store the upload in its own job directory and validate it
   (``RECEIVED -> PROCESSING``, or ``RECEIVED -> FAILED`` with the validator's code);
2. ``run_batch``: extract every valid file, detect over the whole batch (one person
   registry, so the same person gets the same token in every file, TR-DT-15.5), then per
   job ``finish``: tokens, redaction, verification, gate.

Every stage runs inside ``JobContext.stage`` (timed, progress reported). Fail-closed rules
(Architecture 6, ADR-09):

* invalid input: ``FAILED`` (rule ``ingest``);
* an exception in any stage of a job: the gate decides with ``processing_error`` set, i.e.
  G0 ``FAILED``; never a partial result. A crash in batch detection fails every job of the
  batch that reached it;
* if the gate decision itself raises, the job is forced to ``FAILED``;
* the only route to ``VALIDATED_SAFE`` is ``gate.machine.decide``.

``finish`` also saves the encrypted job state (segment texts, findings with values) that a
review re-run needs (TR-RV-03); ``rerun`` replays redaction and verification on it.
Stages are injected through ``Stages`` so tests can replace any of them.
"""

from __future__ import annotations

import shutil
import time
import uuid
import zipfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pymupdf
from PIL import Image

from cleargate.core.config import Policy, Settings, check_gate_key, check_vault_key, policy_hash
from cleargate.core.db import MetaStore
from cleargate.core.errors import ClearGateError, ErrorCode
from cleargate.core.logging import get_logger
from cleargate.core.models import (
    Document,
    EntityType,
    FileFormat,
    Finding,
    Locator,
    RedactionAction,
    VerificationReport,
)
from cleargate.core.states import JobState
from cleargate.gate.machine import decide, fail, transition
from cleargate.gate.rules import GateInput, Verdict
from cleargate.ingest.storage import existing_job_dir, job_dir, sanitize_display_name, store_upload
from cleargate.ingest.validator import ValidatedFile, file_ext, validate

log = get_logger(__name__)
Progress = Callable[[str, str, int, int], None]  # job_id, stage, done, total
REDACTING = ("auto_redact", "review")
REGION_TYPES = (EntityType.PHOTO, EntityType.UNREADABLE_IMAGE_REGION)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class JobContext:
    job_id: str
    batch_id: str
    job_dir: Path
    policy: Policy
    policy_hash: str
    settings: Settings
    store: MetaStore
    progress: Progress | None = None
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    reviewed: set[str] = field(default_factory=set)  # finding ids a reviewer resolved
    known_residual: set[str] = field(default_factory=set)  # V3 hits a reviewer accepted
    vault: Any = None  # redact.vault.Vault: tokens for V5, encrypted job state
    # Raster boxes a reviewer confirmed on residual hits: burned on every later run.
    forced_boxes: dict[tuple[str, Any], list[Any]] = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self.report(name, 0, 1)
        start = time.perf_counter()
        try:
            yield
        finally:
            self.timings[name] = round(time.perf_counter() - start, 4)
            log.info(
                "stage finished",
                extra={"job_id": self.job_id, "stage": name, "seconds": self.timings[name]},
            )
        self.report(name, 1, 1)

    def report(self, stage: str, done: int, total: int) -> None:
        if self.progress:
            self.progress(self.job_id, stage, done, total)


# ----------------------------------------------------------------------- stage protocols


class Extractor(Protocol):
    name: str
    version: str

    def supports(self, fmt: FileFormat) -> bool: ...
    def extract(self, path: Path, fmt: FileFormat, ctx: JobContext) -> Document: ...


class Detector(Protocol):
    name: str
    version: str

    def detect_batch(self, docs: list[Document], ctxs: list[JobContext]) -> list[list[Finding]]: ...


@dataclass
class WriteResult:
    output_path: Path
    sanitized_path: Path
    actions: list[RedactionAction] = field(default_factory=list)
    masked_parts: list[Locator] = field(default_factory=list)  # uninspected parts removed


class Writer(Protocol):
    name: str
    version: str

    def apply(
        self, src: Path, doc: Document, findings: list[Finding], out_dir: Path, ctx: JobContext
    ) -> WriteResult: ...


class Verifier(Protocol):
    name: str
    version: str

    def verify(
        self,
        src: Path,
        result: WriteResult,
        doc: Document,
        findings: list[Finding],
        ctx: JobContext,
    ) -> VerificationReport: ...


@dataclass
class Stages:
    extractors: Sequence[Extractor]
    detector: Detector
    writer: Writer
    verifier: Verifier

    def extractor_for(self, fmt: FileFormat) -> Extractor:
        for ex in self.extractors:
            if ex.supports(fmt):
                return ex
        raise ClearGateError(ErrorCode.EXTRACTION_FAILED, part=f"no_extractor:{fmt.value}")

    def versions(self) -> dict[str, str]:
        parts: list[Extractor | Detector | Writer | Verifier] = [
            *self.extractors,
            self.detector,
            self.writer,
            self.verifier,
        ]
        return {p.name: p.version for p in parts}


# ----------------------------------------------------------------------- stub stages


class RegisterOnlyExtractor:
    """Phase 2 stub: registers every part, inspects none (all ``STUB_NOT_INSPECTED``)."""

    name = "register-only"
    version = "0.2.0"

    def supports(self, fmt: FileFormat) -> bool:
        return True

    def extract(self, path: Path, fmt: FileFormat, ctx: JobContext) -> Document:
        doc = Document(
            doc_id=ctx.job_id,
            filename=path.name,
            sha256="",
            fmt=fmt,
            size_bytes=path.stat().st_size,
        )
        for loc in list_parts(path, fmt):
            doc.coverage.register(loc, inspected=False, code="STUB_NOT_INSPECTED")
        return doc


def list_parts(path: Path, fmt: FileFormat) -> list[Locator]:
    if fmt is FileFormat.PDF:
        with pymupdf.open(path) as pdf:
            return [Locator(part="page", page=i + 1) for i in range(pdf.page_count)]
    if fmt in (FileFormat.DOCX, FileFormat.PPTX):
        with zipfile.ZipFile(path) as zf:
            return [Locator(part=n) for n in zf.namelist() if not n.endswith("/")]
    return [Locator(part="image")]


class NoopDetector:
    name = "noop-detector"
    version = "0.2.0"

    def detect_batch(self, docs: list[Document], ctxs: list[JobContext]) -> list[list[Finding]]:
        return [[] for _ in docs]


class EngineDetector:
    """The layered detection engine (TRD 6), one per policy, shared across batches."""

    name = "detection-engine"
    version = "0.5.0"

    def __init__(self) -> None:
        self._engines: dict[str, Any] = {}

    def engine(self, policy: Policy) -> Any:
        from cleargate.detect.engine import DetectionEngine

        key = policy_hash(policy)
        if key not in self._engines:
            self._engines[key] = DetectionEngine(policy)
        return self._engines[key]

    def detect_batch(self, docs: list[Document], ctxs: list[JobContext]) -> list[list[Finding]]:
        if not docs:
            return []
        vk = ctxs[0].settings.vault_key
        key = vk.get_secret_value().encode() if vk else b""
        result: list[list[Finding]] = self.engine(ctxs[0].policy).detect_batch(docs, key=key)
        return result


class IdentityWriter:
    """Phase 2 stub: copies the input unchanged and renders segment text in order."""

    name = "identity-writer"
    version = "0.2.0"

    def apply(
        self, src: Path, doc: Document, findings: list[Finding], out_dir: Path, ctx: JobContext
    ) -> WriteResult:
        out = out_dir / f"redacted{src.suffix}"
        shutil.copyfile(src, out)
        sanitized = out_dir / "sanitized.txt"
        text = "\n".join(s.text for s in sorted(doc.segments, key=lambda s: s.order_index))
        sanitized.write_text(text, encoding="utf-8")
        return WriteResult(output_path=out, sanitized_path=sanitized)


class CoverageOnlyVerifier:
    """Phase 2 stub: V1 (output reopens) and V4 (coverage, unit counts) only."""

    name = "coverage-only-verifier"
    version = "0.2.0"

    def verify(
        self,
        src: Path,
        result: WriteResult,
        doc: Document,
        findings: list[Finding],
        ctx: JobContext,
    ) -> VerificationReport:
        reopen_ok = reopens(result.output_path, doc.fmt)
        units_equal = reopen_ok and len(list_parts(src, doc.fmt)) == len(
            list_parts(result.output_path, doc.fmt)
        )
        masked = set(result.masked_parts)
        return VerificationReport(
            job_id=ctx.job_id,
            checks_run=frozenset({"V1", "V4"}),
            reopen_ok=reopen_ok,
            uninspected_unmasked=sum(1 for loc in doc.coverage.uninspected if loc not in masked),
            unit_counts_equal=units_equal,
            verifiers={self.name: self.version},
        )


def reopens(path: Path, fmt: FileFormat) -> bool:
    try:
        if fmt is FileFormat.PDF:
            with pymupdf.open(path) as pdf:
                return pdf.page_count > 0
        if fmt in (FileFormat.DOCX, FileFormat.PPTX):
            with zipfile.ZipFile(path) as zf:
                return zf.testzip() is None
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:  # any failure to reopen is a V1 failure
        return False


def default_stages() -> Stages:
    from cleargate.extract.docx import DocxExtractor
    from cleargate.extract.image import ImageExtractor
    from cleargate.extract.pdf import PdfExtractor
    from cleargate.extract.pptx import PptxExtractor
    from cleargate.redact.writers import FormatWriter
    from cleargate.verify import IndependentVerifier

    return Stages(
        extractors=[PdfExtractor(), DocxExtractor(), PptxExtractor(), ImageExtractor()],
        detector=EngineDetector(),
        writer=FormatWriter(),
        verifier=IndependentVerifier(),
    )


def default_extractor(fmt: FileFormat) -> Extractor:
    """The standard extractor for a format (also used by V3/V6 on outputs)."""
    from cleargate.extract.docx import DocxExtractor
    from cleargate.extract.image import ImageExtractor
    from cleargate.extract.pdf import PdfExtractor
    from cleargate.extract.pptx import PptxExtractor

    for ex in (PdfExtractor(), DocxExtractor(), PptxExtractor(), ImageExtractor()):
        if ex.supports(fmt):
            return ex
    raise ClearGateError(ErrorCode.EXTRACTION_FAILED, part=f"no_extractor:{fmt.value}")


# ----------------------------------------------------------------------- job state


def dump_state(doc: Document, findings: list[Finding], ctx: JobContext) -> dict[str, Any]:
    """Everything a review re-run needs, raw values included (stored encrypted only)."""
    return {
        "doc": doc.model_dump(mode="json"),
        "texts": [s.text for s in doc.segments],
        "findings": [f.model_dump(mode="json") for f in findings],
        "values": [f.value for f in findings],
        "reviewed": sorted(ctx.reviewed),
        "known_residual": sorted(ctx.known_residual),
        "forced_boxes": [[list(k), [list(b) for b in v]] for k, v in ctx.forced_boxes.items()],
    }


def load_doc(state: dict[str, Any]) -> tuple[Document, list[Finding]]:
    doc_json = state["doc"]
    for seg, text in zip(doc_json["segments"], state["texts"], strict=True):
        seg["text"] = text
    doc = Document.model_validate(doc_json)
    findings = [
        Finding.model_validate({**f, "value": v})
        for f, v in zip(state["findings"], state["values"], strict=True)
    ]
    return doc, findings


def is_region(f: Finding) -> bool:
    return f.entity_type in REGION_TYPES


# ----------------------------------------------------------------------- pipeline


@dataclass
class JobResult:
    job_id: str
    filename: str
    state: JobState
    rule: str
    reason: str
    timings: dict[str, float] = field(default_factory=dict)
    finding_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class BatchResult:
    batch_id: str
    jobs: list[JobResult]


@dataclass
class Prepared:
    ctx: JobContext
    name: str
    vf: ValidatedFile | None


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        policy: Policy,
        store: MetaStore,
        stages: Stages | None = None,
        progress: Progress | None = None,
    ) -> None:
        check_gate_key(settings.gate_key)  # refuse to run without keys (TR-RD-02, TR-GT-03)
        check_vault_key(settings.vault_key)
        from cleargate.redact.tokens import TokenService
        from cleargate.redact.vault import Vault

        self.settings = settings
        self.policy = policy
        self.policy_hash = policy_hash(policy)
        self.store = store
        self.stages = stages or default_stages()
        self.progress = progress
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.vault = Vault(settings.data_dir / "vault.db", settings.vault_key)
        self.tokens = TokenService(self.vault, policy.redaction.token_style)

    def close(self) -> None:
        self.vault.close()

    # -------------------------------------------------------------- batches

    def process_batch(
        self, paths: Sequence[Path], names: Sequence[str | None] | None = None
    ) -> BatchResult:
        batch_id, prepared = self.submit_batch(paths, names)
        self.run_batch(prepared)
        return BatchResult(batch_id, [self._result(p.ctx, p.name) for p in prepared])

    def submit_batch(
        self, paths: Sequence[Path], names: Sequence[str | None] | None = None
    ) -> tuple[str, list[Prepared]]:
        if len(paths) > self.policy.limits.max_files_per_batch:
            raise ClearGateError(ErrorCode.INTERNAL, stage="too_many_files")
        batch_id = new_id("batch")
        self.store.create_batch(batch_id, self.policy.policy_name, self.policy_hash)
        names = list(names) if names is not None else [None] * len(paths)
        return batch_id, [self.submit(batch_id, p, n) for p, n in zip(paths, names, strict=True)]

    def process_file(self, batch_id: str, src: Path, display_name: str | None = None) -> JobResult:
        prepared = self.submit(batch_id, src, display_name)
        self.run_batch([prepared])
        return self._result(prepared.ctx, prepared.name)

    def context(self, job_id: str, batch_id: str, *, create: bool = True) -> JobContext:
        """Context of a new job (creates its directory) or of an existing one."""
        jdir = (job_dir if create else existing_job_dir)(self.settings.data_dir, job_id)
        return JobContext(
            job_id=job_id,
            batch_id=batch_id,
            job_dir=jdir,
            policy=self.policy,
            policy_hash=self.policy_hash,
            settings=self.settings,
            store=self.store,
            progress=self.progress,
            vault=self.vault,
        )

    def submit(self, batch_id: str, src: Path, display_name: str | None = None) -> Prepared:
        """Store and validate one upload (synchronous part of ``POST /batches``)."""
        job_id = new_id("job")
        name = sanitize_display_name(display_name or src.name)
        self.store.create_job(job_id, batch_id, name, self.policy_hash)
        ctx = self.context(job_id, batch_id)
        try:
            stored = store_upload(src, ctx.job_dir, file_ext(name))
            with ctx.stage("validate"):
                validated = validate(stored, self.policy.limits, display_name=name)
        except ClearGateError as exc:
            fail(self.store, job_id, exc.code, rule="ingest")
            return Prepared(ctx, name, None)
        except OSError:
            fail(self.store, job_id, ErrorCode.MALFORMED, rule="ingest")
            return Prepared(ctx, name, None)
        with self.store.transaction():
            self.store.conn.execute(
                "UPDATE jobs SET fmt = ?, sha256 = ?, size_bytes = ? WHERE job_id = ?",
                (validated.fmt.value, validated.sha256, validated.size_bytes, job_id),
            )
        transition(self.store, job_id, JobState.PROCESSING, rule="ingest", reason="validated")
        return Prepared(ctx, name, validated)

    def run_batch(self, prepared: Sequence[Prepared]) -> None:
        live = [p for p in prepared if p.vf is not None]
        docs: dict[str, Document] = {}
        errors: dict[str, ErrorCode] = {}
        for p in live:
            assert p.vf is not None
            try:
                with p.ctx.stage("extract"):
                    extractor = self.stages.extractor_for(p.vf.fmt)
                    docs[p.ctx.job_id] = extractor.extract(p.vf.path, p.vf.fmt, p.ctx)
            except ClearGateError as exc:
                errors[p.ctx.job_id] = exc.code
                log.warning("extract failed", exc_info=True, extra={"job_id": p.ctx.job_id})
            except Exception:  # fail closed on anything unexpected
                errors[p.ctx.job_id] = ErrorCode.INTERNAL
                log.warning("extract crashed", exc_info=True, extra={"job_id": p.ctx.job_id})
        ready = [p for p in live if p.ctx.job_id in docs]
        found: dict[str, list[Finding]] = {}
        if ready:
            start = time.perf_counter()
            for p in ready:
                p.ctx.report("detect", 0, 1)
            try:
                lists = self.stages.detector.detect_batch(
                    [docs[p.ctx.job_id] for p in ready], [p.ctx for p in ready]
                )
                found = {p.ctx.job_id: f for p, f in zip(ready, lists, strict=True)}
            except ClearGateError as exc:
                errors.update({p.ctx.job_id: exc.code for p in ready})
                log.warning("detect failed", exc_info=True)
            except Exception:
                errors.update({p.ctx.job_id: ErrorCode.INTERNAL for p in ready})
                log.warning("detect crashed", exc_info=True)
            elapsed = round(time.perf_counter() - start, 4)
            for p in ready:
                p.ctx.timings["detect"] = elapsed
                p.ctx.report("detect", 1, 1)
        for p in live:
            assert p.vf is not None
            jid = p.ctx.job_id
            if jid in errors:
                self._decide(p.ctx, GateInput(job_id=jid, processing_error=errors[jid]))
            else:
                self.finish(p.ctx, p.vf, docs[jid], found[jid])

    # -------------------------------------------------------------- per job

    def finish(
        self, ctx: JobContext, vf: ValidatedFile, doc: Document, findings: list[Finding]
    ) -> Verdict | None:
        out_dir = ctx.job_dir / "out"
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir()
        try:
            gate_input = self._finish_stages(ctx, vf, doc, findings, out_dir)
        except ClearGateError as exc:
            gate_input = GateInput(job_id=ctx.job_id, processing_error=exc.code)
            log.warning("stage failed", exc_info=True, extra={"job_id": ctx.job_id})
        except Exception:  # fail closed on anything unexpected
            gate_input = GateInput(job_id=ctx.job_id, processing_error=ErrorCode.INTERNAL)
            log.warning("stage crashed", exc_info=True, extra={"job_id": ctx.job_id})
        return self._decide(ctx, gate_input)

    def _finish_stages(
        self,
        ctx: JobContext,
        vf: ValidatedFile,
        doc: Document,
        findings: list[Finding],
        out_dir: Path,
    ) -> GateInput:
        with ctx.stage("redact"):
            findings = self.tokens.assign(ctx.batch_id, findings)
            self.vault.save_state(ctx.job_dir, dump_state(doc, findings, ctx))
            result = self.stages.writer.apply(vf.path, doc, findings, out_dir, ctx)
            repair = getattr(self.stages.writer, "repair", None)
            if ctx.forced_boxes and repair is not None:
                repair(result.output_path, doc.fmt, ctx.forced_boxes, ctx)
                result.actions.extend(
                    RedactionAction(
                        finding_ids=[],
                        locator=Locator(part=str(k[0])),
                        method="pixel_mask",
                        token="review-confirmed",  # noqa: S106 (a marker, not a secret)
                        applied=True,
                    )
                    for k in ctx.forced_boxes
                )
        with ctx.stage("verify"):
            report = self.stages.verifier.verify(vf.path, result, doc, findings, ctx)
            boxes = getattr(self.stages.verifier, "last_repair", {}).pop(ctx.job_id, None)
            if (report.leak_hits or report.residual_deterministic) and boxes and repair is not None:
                # One repair pass (ADR-30): burn the located hits, then verify from scratch.
                burned = repair(result.output_path, doc.fmt, boxes, ctx)
                result.actions.extend(
                    RedactionAction(
                        finding_ids=[],
                        locator=Locator(
                            part=str(kind),
                            page=n if isinstance(n, int) else None,
                            image_ref=n if isinstance(n, str) else None,
                        ),
                        method="pixel_mask",
                        token="verify-repair",  # noqa: S106 (a marker, not a secret)
                        applied=True,
                    )
                    for (kind, n), bxs in boxes.items()
                    if bxs
                )
                ctx.warnings.append(f"verify_repair_boxes={burned}")
                report = self.stages.verifier.verify(vf.path, result, doc, findings, ctx)
                getattr(self.stages.verifier, "last_repair", {}).pop(ctx.job_id, None)
        residual = getattr(self.stages.verifier, "last_residual", {}).pop(ctx.job_id, [])
        residual_boxes = getattr(self.stages.verifier, "last_residual_boxes", {}).pop(
            ctx.job_id, {}
        )
        state = dump_state(doc, findings, ctx)
        state["residual"] = [f.model_dump(mode="json") for f in residual]
        state["residual_values"] = [f.value for f in residual]
        state["residual_boxes"] = residual_boxes
        self.vault.save_state(ctx.job_dir, state)
        self.store.replace_findings(ctx.job_id, findings)
        self.store.save_run(ctx.job_id, report, result.actions, ctx.timings, self.stages.versions())
        open_items = sum(
            1 for f in findings if f.decision == "review" and f.finding_id not in ctx.reviewed
        )
        regions = sum(
            1
            for f in findings
            if is_region(f) and f.decision in REDACTING and f.finding_id not in ctx.reviewed
        )
        return GateInput(
            job_id=ctx.job_id,
            verification=report,
            coverage=doc.coverage,
            masked_parts=frozenset(result.masked_parts),
            actions=tuple(result.actions),
            open_review_items=open_items,
            masked_regions=regions,
            unreadable_policy=self.policy.ocr.unreadable_policy,
            srs_min=self.policy.verification.srs_min,
        )

    def _decide(self, ctx: JobContext, gate_input: GateInput) -> Verdict | None:
        sanitized = ctx.job_dir / "out" / "sanitized.txt"
        try:
            with ctx.stage("gate"):
                assert self.settings.gate_key is not None
                return decide(
                    self.store,
                    gate_input,
                    gate_key=self.settings.gate_key,
                    sanitized_path=sanitized,
                )
        except Exception:
            log.error("gate decision failed", exc_info=True, extra={"job_id": ctx.job_id})
            if self.store.job_state(ctx.job_id) is JobState.PROCESSING:
                fail(self.store, ctx.job_id, ErrorCode.INTERNAL)
            return None

    # -------------------------------------------------------------- review re-run (TR-RV-03)

    def rerun(
        self, job_id: str, findings: list[Finding], doc: Document, ctx: JobContext
    ) -> Verdict | None:
        """Re-redact and re-verify with reviewer overrides; detection is not re-run."""
        row = self.store.get_job(job_id)
        assert row is not None
        stored = next(ctx.job_dir.glob("original.*"))
        try:
            vf = validate(stored, self.policy.limits, display_name=row["filename"])
        except ClearGateError as exc:
            return self._decide(ctx, GateInput(job_id=job_id, processing_error=exc.code))
        return self.finish(ctx, vf, doc, findings)

    def _result(self, ctx: JobContext, name: str) -> JobResult:
        job = self.store.get_job(ctx.job_id)
        assert job is not None
        counts: dict[str, int] = {}
        for row in self.store.findings(ctx.job_id):
            if row["decision"] in REDACTING:
                counts[row["entity_type"]] = counts.get(row["entity_type"], 0) + 1
        return JobResult(
            job_id=ctx.job_id,
            filename=name,
            state=JobState(job["state"]),
            rule=job["rule"] or "",
            reason=job["reason"] or "",
            timings=dict(ctx.timings),
            finding_counts=counts,
        )
