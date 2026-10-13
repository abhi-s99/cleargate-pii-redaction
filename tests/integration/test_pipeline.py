"""Walking skeleton: fail-closed from day one (brief Phase 2, Architecture 6, FR-01)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from pydantic import SecretStr

from cleargate.core.config import LimitsPolicy, Policy, Settings
from cleargate.core.db import MetaStore
from cleargate.core.errors import ClearGateError, ErrorCode
from cleargate.core.models import (
    ALL_CHECKS,
    Document,
    FileFormat,
    Finding,
    Locator,
    VerificationReport,
)
from cleargate.core.states import JobState
from cleargate.gate.handle import SafeHandle, verify_against_store
from cleargate.pipeline import (
    CoverageOnlyVerifier,
    IdentityWriter,
    JobContext,
    NoopDetector,
    Pipeline,
    RegisterOnlyExtractor,
    Stages,
    WriteResult,
    default_stages,
)
from tests import filegen

BUILDERS = {
    "docx": filegen.docx,
    "pptx": filegen.pptx,
    "pdf": filegen.pdf,
    "png": filegen.png,
}


def run(pipeline: Pipeline, path: Path, name: str | None = None) -> tuple[str, MetaStore]:
    batch = pipeline.process_batch([path]) if name is None else None
    if batch is None:
        bid = "batch-manual"
        pipeline.store.create_batch(bid, "p", pipeline.policy_hash)
        job = pipeline.process_file(bid, path, display_name=name)
    else:
        (job,) = batch.jobs
    return job.job_id, pipeline.store


def states(store: MetaStore, job_id: str) -> list[str]:
    return [r["to_state"] for r in store.history(job_id)]


@pytest.mark.parametrize("ext", sorted(BUILDERS))
def test_valid_file_ends_blocked_by_g3(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore, ext: str
) -> None:
    path = BUILDERS[ext](tmp_path / f"input.{ext}")
    job_id, _ = run(Pipeline(settings, policy, store), path)
    job = store.get_job(job_id)
    assert job["state"] == "BLOCKED"
    assert job["rule"] == "G3"
    assert "UNINSPECTED_PARTS=" in job["reason"]
    assert states(store, job_id) == ["PROCESSING", "BLOCKED"]
    assert store.handle_json(job_id) is None


def test_upload_is_stored_under_job_dir_as_original(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore
) -> None:
    src = filegen.docx(tmp_path / "Board Pack.docx")
    job_id, _ = run(Pipeline(settings, policy, store), src)
    jd = settings.data_dir / "jobs" / job_id
    assert (jd / "original.docx").read_bytes() == src.read_bytes()
    assert not list(jd.rglob("Board Pack*"))
    assert store.get_job(job_id)["filename"] == "Board Pack.docx"
    assert store.get_job(job_id)["fmt"] == "docx"


def encrypted_pdf(p: Path) -> Path:
    return filegen.pdf(p, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")


def docm(p: Path) -> Path:
    return filegen.docx(p)


def zip_bomb(p: Path) -> Path:
    src = filegen.docx(p.with_name("src.docx"))
    return filegen.rewrite_zip(src, p, add={"word/media/pad.bin": b"\0" * (20 << 20)})


@pytest.mark.parametrize(
    ("builder", "name", "code"),
    [
        (filegen.docx, "wrong.pdf", ErrorCode.EXTENSION_MISMATCH),
        (encrypted_pdf, "locked.pdf", ErrorCode.ENCRYPTED),
        (docm, "macro.docm", ErrorCode.MACRO_ENABLED),
        (zip_bomb, "bomb.docx", ErrorCode.ZIP_BOMB),
        (filegen.docx, "oversize.docx", ErrorCode.FILE_TOO_LARGE),
        (
            lambda p: filegen.ole_file(p, encrypted=False),
            "legacy.doc",
            ErrorCode.UNSUPPORTED_FORMAT,
        ),
    ],
)
def test_invalid_input_ends_failed_with_specific_code(
    tmp_path: Path,
    settings: Settings,
    policy: Policy,
    store: MetaStore,
    builder: object,
    name: str,
    code: ErrorCode,
) -> None:
    if code is ErrorCode.FILE_TOO_LARGE:
        policy = policy.model_copy(update={"limits": LimitsPolicy(max_file_bytes=1000)})
    path = builder(tmp_path / name)  # type: ignore[operator]
    job_id, _ = run(Pipeline(settings, policy, store), path)
    job = store.get_job(job_id)
    assert (job["state"], job["rule"], job["reason"]) == ("FAILED", "ingest", code.value)
    assert states(store, job_id) == ["FAILED"]  # RECEIVED -> FAILED, never PROCESSING


class Boom(RuntimeError):
    pass


def crashing(stage: str, exc: Exception) -> Stages:
    s = default_stages()

    def raise_(*_a: object, **_k: object) -> None:
        raise exc

    target = {
        "extract": s.extractors[0],
        "detect": s.detector,
        "redact": s.writer,
        "verify": s.verifier,
    }[stage]
    method = {"extract": "extract", "detect": "detect", "redact": "apply", "verify": "verify"}[
        stage
    ]
    setattr(target, method, raise_)
    return s


@pytest.mark.parametrize("stage", ["extract", "detect", "redact", "verify"])
def test_crash_in_any_stage_ends_failed(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore, stage: str
) -> None:
    pipeline = Pipeline(
        settings, policy, store, stages=crashing(stage, Boom("Ada Quill 900-11-2222"))
    )
    job_id, _ = run(pipeline, filegen.docx(tmp_path / "x.docx"))
    job = store.get_job(job_id)
    assert (job["state"], job["rule"]) == ("FAILED", "G0")
    assert job["reason"].startswith("INTERNAL")
    assert "Ada" not in job["reason"]  # exception text never reaches the database


@pytest.mark.parametrize("stage", ["extract", "verify"])
def test_typed_stage_error_keeps_its_code(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore, stage: str
) -> None:
    exc = ClearGateError(ErrorCode.OCR_TIMEOUT, page=3, timeout_s=120)
    job_id, _ = run(
        Pipeline(settings, policy, store, stages=crashing(stage, exc)),
        filegen.pdf(tmp_path / "x.pdf"),
    )
    assert store.get_job(job_id)["reason"].startswith("OCR_TIMEOUT")


def test_crash_in_gate_decision_ends_failed(
    tmp_path: Path,
    settings: Settings,
    policy: Policy,
    store: MetaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("gate exploded")

    monkeypatch.setattr("cleargate.pipeline.decide", broken)
    job_id, _ = run(Pipeline(settings, policy, store), filegen.docx(tmp_path / "x.docx"))
    assert store.get_job(job_id)["state"] == "FAILED"
    assert states(store, job_id) == ["PROCESSING", "FAILED"]


def test_pipeline_refuses_to_start_without_keys(
    settings: Settings, policy: Policy, store: MetaStore
) -> None:
    for missing in ("gate_key", "vault_key"):
        with pytest.raises(ClearGateError) as exc_info:
            Pipeline(settings.model_copy(update={missing: None}), policy, store)
        assert exc_info.value.code is ErrorCode.KEY_MISSING
    with pytest.raises(ClearGateError):
        Pipeline(settings.model_copy(update={"gate_key": SecretStr("short")}), policy, store)


def test_batch_size_limit(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore
) -> None:
    policy = policy.model_copy(update={"limits": LimitsPolicy(max_files_per_batch=1)})
    files = [filegen.docx(tmp_path / "a.docx"), filegen.docx(tmp_path / "b.docx")]
    with pytest.raises(ClearGateError):
        Pipeline(settings, policy, store).process_batch(files)


def test_stage_timings_and_progress(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore
) -> None:
    events: list[tuple[str, int]] = []
    pipeline = Pipeline(
        settings, policy, store, progress=lambda _j, s, d, _t: events.append((s, d))
    )
    (job,) = pipeline.process_batch([filegen.pdf(tmp_path / "x.pdf")]).jobs
    assert set(job.timings) == {"validate", "extract", "detect", "redact", "verify", "gate"}
    assert ("extract", 0) in events
    assert ("extract", 1) in events


def test_mixed_batch(tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore) -> None:
    files = [filegen.docx(tmp_path / "a.docx"), filegen.docx(tmp_path / "b.pdf")]
    batch = Pipeline(settings, policy, store).process_batch(files)
    assert [j.state for j in batch.jobs] == [JobState.BLOCKED, JobState.FAILED]
    assert len({j.job_id for j in batch.jobs}) == 2


# --- the skeleton can only produce SAFE when every rule passes ------------------------


class InspectingExtractor(RegisterOnlyExtractor):
    def extract(self, path: Path, fmt: FileFormat, ctx: JobContext) -> Document:
        doc = Document(doc_id=ctx.job_id, filename=path.name, sha256="", fmt=fmt, size_bytes=1)
        doc.coverage.register(Locator(part="page", page=1), inspected=True)
        return doc


class ClaimsEverythingVerifier(CoverageOnlyVerifier):
    """Test double that declares all checks clean: proves the SAFE path works end to end."""

    def verify(
        self,
        src: Path,
        result: WriteResult,
        doc: Document,
        findings: list[Finding],
        ctx: JobContext,
    ) -> VerificationReport:
        return VerificationReport(
            job_id=ctx.job_id, checks_run=ALL_CHECKS, reopen_ok=True, srs=1.0, crs=1.0
        )


def test_partial_verifier_cannot_produce_safe_even_with_full_coverage(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore
) -> None:
    stages = replace(default_stages(), extractors=[InspectingExtractor()])
    job_id, _ = run(
        Pipeline(settings, policy, store, stages=stages), filegen.docx(tmp_path / "x.docx")
    )
    job = store.get_job(job_id)
    assert (job["state"], job["rule"]) == ("BLOCKED", "G3")
    assert job["reason"] == "V2_NOT_RUN,V3_NOT_RUN,V5_NOT_RUN"


def test_safe_path_mints_a_handle_over_the_sanitized_output(
    tmp_path: Path, settings: Settings, policy: Policy, store: MetaStore
) -> None:
    stages = Stages(
        [InspectingExtractor()], NoopDetector(), IdentityWriter(), ClaimsEverythingVerifier()
    )
    job_id, _ = run(
        Pipeline(settings, policy, store, stages=stages), filegen.docx(tmp_path / "x.docx")
    )
    assert store.get_job(job_id)["state"] == "VALIDATED_SAFE"
    stored = store.handle_json(job_id)
    assert stored is not None
    sanitized = settings.data_dir / "jobs" / job_id / "out" / "sanitized.txt"
    assert settings.gate_key is not None
    verify_against_store(store, SafeHandle.from_json(stored), settings.gate_key, sanitized)
