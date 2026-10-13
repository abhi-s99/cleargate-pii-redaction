"""Pipeline orchestrator: validate -> extract -> detect -> redact -> verify -> gate.

``Pipeline.process_batch`` creates a batch, stores each upload in its own job
directory and runs ``run_job``. Every stage runs inside ``JobContext.stage`` (timed,
progress reported). Fail-closed rules (Architecture 6, ADR-09):

* invalid input: ``RECEIVED -> FAILED`` with the validator's code (rule ``ingest``);
* any exception in a stage: the gate decides with ``processing_error`` set, i.e.
  G0 ``FAILED``; never a partial result;
* if the gate decision itself raises, the job is forced to ``FAILED``;
* the only route to ``VALIDATED_SAFE`` is ``gate.machine.decide``.

Stages are injected through ``Stages`` so tests can replace any of them. Until the
real stages land, ``default_stages`` uses stubs: an extractor that registers parts
but inspects none, a no-op detector, an identity writer and a verifier that runs
only V1 (reopen) and V4 (coverage). Any valid file therefore ends ``BLOCKED`` (G3).
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
from typing import Protocol

import pymupdf
from PIL import Image

from cleargate.core.config import Policy, Settings, check_gate_key, check_vault_key, policy_hash
from cleargate.core.db import MetaStore
from cleargate.core.errors import ClearGateError, ErrorCode
from cleargate.core.logging import get_logger
from cleargate.core.models import (
    Document,
    FileFormat,
    Finding,
    Locator,
    RedactionAction,
    VerificationReport,
)
from cleargate.core.states import JobState
from cleargate.gate.machine import decide, fail, transition
from cleargate.gate.rules import GateInput, Verdict
from cleargate.ingest.storage import job_dir, sanitize_display_name, store_upload
from cleargate.ingest.validator import ValidatedFile, file_ext, validate

log = get_logger(__name__)
Progress = Callable[[str, str, int, int], None]  # job_id, stage, done, total


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

    def detect(self, doc: Document, ctx: JobContext) -> list[Finding]: ...


@dataclass
class WriteResult:
    output_path: Path
    sanitized_path: Path
    actions: list[RedactionAction] = field(default_factory=list)


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

    def detect(self, doc: Document, ctx: JobContext) -> list[Finding]:
        return []


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
        return VerificationReport(
            job_id=ctx.job_id,
            checks_run=frozenset({"V1", "V4"}),
            reopen_ok=reopen_ok,
            uninspected_unmasked=len(doc.coverage.uninspected),
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

    return Stages(
        extractors=[PdfExtractor(), DocxExtractor(), PptxExtractor(), ImageExtractor()],
        detector=NoopDetector(),
        writer=IdentityWriter(),
        verifier=CoverageOnlyVerifier(),
    )


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
        self.settings = settings
        self.policy = policy
        self.policy_hash = policy_hash(policy)
        self.store = store
        self.stages = stages or default_stages()
        self.progress = progress

    def process_batch(self, paths: Sequence[Path]) -> BatchResult:
        if len(paths) > self.policy.limits.max_files_per_batch:
            raise ClearGateError(ErrorCode.INTERNAL, stage="too_many_files")
        batch_id = new_id("batch")
        self.store.create_batch(batch_id, self.policy.policy_name, self.policy_hash)
        return BatchResult(batch_id, [self.process_file(batch_id, p) for p in paths])

    def process_file(self, batch_id: str, src: Path, display_name: str | None = None) -> JobResult:
        job_id = new_id("job")
        name = sanitize_display_name(display_name or src.name)
        self.store.create_job(job_id, batch_id, name, self.policy_hash)
        ctx = JobContext(
            job_id=job_id,
            batch_id=batch_id,
            job_dir=job_dir(self.settings.data_dir, job_id),
            policy=self.policy,
            policy_hash=self.policy_hash,
            settings=self.settings,
            store=self.store,
            progress=self.progress,
        )
        try:
            stored = store_upload(src, ctx.job_dir, file_ext(name))
            with ctx.stage("validate"):
                validated = validate(stored, self.policy.limits, display_name=name)
        except ClearGateError as exc:
            fail(self.store, job_id, exc.code, rule="ingest")
            return self._result(ctx, name)
        except OSError:
            fail(self.store, job_id, ErrorCode.MALFORMED, rule="ingest")
            return self._result(ctx, name)
        with self.store.transaction():
            self.store.conn.execute(
                "UPDATE jobs SET fmt = ?, sha256 = ?, size_bytes = ? WHERE job_id = ?",
                (validated.fmt.value, validated.sha256, validated.size_bytes, job_id),
            )
        transition(self.store, job_id, JobState.PROCESSING, rule="ingest", reason="validated")
        self.run_job(ctx, validated)
        return self._result(ctx, name)

    def run_job(self, ctx: JobContext, vf: ValidatedFile) -> Verdict | None:
        out_dir = ctx.job_dir / "out"
        out_dir.mkdir(exist_ok=True)
        sanitized = out_dir / "sanitized.txt"
        try:
            gate_input = self._run_stages(ctx, vf, out_dir)
        except ClearGateError as exc:
            gate_input = GateInput(job_id=ctx.job_id, processing_error=exc.code)
            log.warning("stage failed", exc_info=True, extra={"job_id": ctx.job_id})
        except Exception:  # fail closed on anything unexpected
            gate_input = GateInput(job_id=ctx.job_id, processing_error=ErrorCode.INTERNAL)
            log.warning("stage crashed", exc_info=True, extra={"job_id": ctx.job_id})
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

    def _run_stages(self, ctx: JobContext, vf: ValidatedFile, out_dir: Path) -> GateInput:
        extractor = self.stages.extractor_for(vf.fmt)
        with ctx.stage("extract"):
            doc = extractor.extract(vf.path, vf.fmt, ctx)
        with ctx.stage("detect"):
            findings = self.stages.detector.detect(doc, ctx)
        with ctx.stage("redact"):
            result = self.stages.writer.apply(vf.path, doc, findings, out_dir, ctx)
        with ctx.stage("verify"):
            report = self.stages.verifier.verify(vf.path, result, doc, findings, ctx)
        if findings:
            self.store.add_findings(ctx.job_id, findings)
        return GateInput(
            job_id=ctx.job_id,
            verification=report,
            coverage=doc.coverage,
            actions=tuple(result.actions),
            open_review_items=sum(1 for f in findings if f.decision == "review"),
            unreadable_policy=self.policy.ocr.unreadable_policy,
            srs_min=self.policy.verification.srs_min,
        )

    def _result(self, ctx: JobContext, name: str) -> JobResult:
        job = self.store.get_job(ctx.job_id)
        assert job is not None
        counts: dict[str, int] = {}
        for row in self.store.findings(ctx.job_id):
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
