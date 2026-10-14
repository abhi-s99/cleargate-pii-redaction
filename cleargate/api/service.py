"""Application service behind the API (FR-02, FR-12, FR-13, FR-14, TR-RV-01..04, TR-SEC-05/06).

Routes stay thin; everything stateful lives here:

* one background worker thread runs batches and review re-runs in order (OCR itself uses
  its own process pool), with live progress per job (TR-PF-04);
* every request opens its own ``MetaStore`` connection (SQLite WAL);
* review items are grouped by ``(type, value HMAC)``, so one decision covers every copy of
  a value (ADR-31); regions and residual verification hits are review items too;
* decisions are validated first (no reject of HIGH-risk DETERMINISTIC findings, a
  justification for rejects), then applied to the encrypted job state, logged without raw
  values, and the job goes ``REVIEW_REQUIRED -> PROCESSING`` for re-redaction and
  re-verification; detection is not re-run except value propagation of added spans;
* artifacts and handoff re-verify the SafeHandle against the file on disk every time.
"""

from __future__ import annotations

import base64
import io
import shutil
import threading
import time
import uuid
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from cleargate.core.config import Policy, Settings
from cleargate.core.db import MetaStore
from cleargate.core.errors import ClearGateError, ErrorCode, HandleError
from cleargate.core.logging import get_logger
from cleargate.core.models import DEFAULT_RISK, EntityType, Finding, Locator
from cleargate.core.states import JobState
from cleargate.detect.base import preview, value_hmac
from cleargate.detect.engine import propagate_values
from cleargate.extract.image import open_image
from cleargate.gate.handle import SafeHandle, verify_against_store
from cleargate.gate.handoff import AIHandoff
from cleargate.gate.machine import transition
from cleargate.ingest.storage import existing_job_dir as job_dir
from cleargate.ingest.storage import sanitize_display_name
from cleargate.pipeline import Pipeline, load_doc
from cleargate.redact.vault import Vault
from cleargate.report.builder import build_report, digest, to_markdown

log = get_logger(__name__)
REDACTING = ("auto_redact", "review")
REGION_TYPES = (EntityType.PHOTO, EntityType.UNREADABLE_IMAGE_REGION)
THUMB_DPI = 50
THUMB_MAX = 520
ACTIONS = ("confirm", "reject", "retype", "add", "add_region", "reject_document")


def clean(obj: Any) -> Any:
    """Drop ``None`` values: the UI's schemas treat absent and null differently (ADR-32)."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, job_id: str | None = None) -> None:
        super().__init__(code)
        self.status, self.code, self.message, self.job_id = status, code, message, job_id


def _evidence_dicts(f: Finding) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in f.evidence]


def _locator_dict(loc: Locator | None) -> dict[str, Any] | None:
    return loc.model_dump(mode="json", exclude_none=True) if loc else None


class ClearGateService:
    def __init__(self, settings: Settings, policy: Policy) -> None:
        self.settings = settings
        self.policy = policy
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = settings.data_dir / "meta.db"
        MetaStore.open(self.db_path).close()  # create / migrate once
        self.vault = Vault(settings.data_dir / "vault.db", settings.vault_key)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cleargate-worker")
        self.progress: dict[str, dict[str, Any]] = {}
        self._worker: Pipeline | None = None
        self._thumbs: dict[tuple[str, str], tuple[str, float]] = {}
        self._stop = threading.Event()

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def store(self) -> Iterator[MetaStore]:
        s = MetaStore.open(self.db_path)
        try:
            yield s
        finally:
            s.close()

    def on_progress(self, job_id: str, stage: str, done: int, total: int) -> None:
        self.progress[job_id] = {"stage": stage, "done": done, "total": total, "at": time.time()}

    def worker(self) -> Pipeline:
        if self._worker is None:  # created in the worker thread, with its own connection
            self._worker = Pipeline(
                self.settings, self.policy, MetaStore.open(self.db_path), progress=self.on_progress
            )
        return self._worker

    def shutdown(self) -> None:
        self._stop.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _job(self, store: MetaStore, job_id: str) -> Any:
        row = store.get_job(job_id)
        if row is None:
            raise ApiError(404, "JOB_NOT_FOUND", "Job not found", job_id)
        return row

    def _state(self, job_id: str) -> dict[str, Any] | None:
        try:
            return self.vault.load_state(job_dir(self.settings.data_dir, job_id))
        except ClearGateError:
            return None

    # ------------------------------------------------------------------ batches

    def submit(self, uploads: list[tuple[str, bytes]]) -> dict[str, Any]:
        if not uploads:
            raise ApiError(400, "NO_FILES", "No files were uploaded")
        if len(uploads) > self.policy.limits.max_files_per_batch:
            raise ApiError(
                400,
                "TOO_MANY_FILES",
                f"At most {self.policy.limits.max_files_per_batch} files per batch",
            )
        tmp = self.settings.data_dir / "uploads" / uuid.uuid4().hex
        tmp.mkdir(parents=True)
        try:
            paths, names = [], []
            for i, (name, data) in enumerate(uploads):
                safe = sanitize_display_name(name)
                if len(data) > self.policy.limits.max_file_bytes:
                    data = data[: self.policy.limits.max_file_bytes + 1]  # the validator rejects it
                path = tmp / f"{i:03d}{Path(safe).suffix.lower() or '.bin'}"
                path.write_bytes(data)
                paths.append(path)
                names.append(safe)
            with self.store() as store:
                pipeline = Pipeline(self.settings, self.policy, store, progress=self.on_progress)
                try:
                    batch_id, prepared = pipeline.submit_batch(paths, names)
                finally:
                    pipeline.close()
                jobs = [
                    {
                        "job_id": p.ctx.job_id,
                        "filename": p.name,
                        "state": self._job(store, p.ctx.job_id)["state"],
                    }
                    for p in prepared
                ]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        live = [j["job_id"] for j in jobs if j["state"] == JobState.PROCESSING.value]
        for jid in live:
            self.on_progress(jid, "queued", 0, 1)
        if live:
            self.executor.submit(self._run_batch, batch_id, live)
        return {"batch_id": batch_id, "jobs": jobs}

    def _run_batch(self, batch_id: str, job_ids: list[str]) -> None:
        from cleargate.ingest.validator import validate
        from cleargate.pipeline import Prepared

        pipeline = self.worker()
        prepared = []
        for jid in job_ids:
            ctx = pipeline.context(jid, batch_id, create=False)
            row = pipeline.store.get_job(jid)
            assert row is not None
            try:
                stored = next(ctx.job_dir.glob("original.*"))
                vf = validate(stored, self.policy.limits, display_name=row["filename"])
            except (StopIteration, ClearGateError):
                vf = None
            prepared.append(Prepared(ctx, row["filename"], vf))
        try:
            pipeline.run_batch(prepared)
        except Exception:  # never leave a job in PROCESSING
            log.error("batch run crashed", exc_info=True, extra={"batch_id": batch_id})
            for p in prepared:
                if pipeline.store.job_state(p.ctx.job_id) is JobState.PROCESSING:
                    from cleargate.gate.machine import fail

                    fail(pipeline.store, p.ctx.job_id, ErrorCode.INTERNAL)
        for jid in job_ids:
            self.progress[jid] = {"stage": "done", "done": 1, "total": 1, "at": time.time()}

    def delete_batch(self, batch_id: str) -> dict[str, Any]:
        with self.store() as store:
            jobs = store.batch_jobs(batch_id)
            if (
                not jobs
                and store.conn.execute(
                    "SELECT 1 FROM batches WHERE batch_id = ?", (batch_id,)
                ).fetchone()
                is None
            ):
                raise ApiError(404, "BATCH_NOT_FOUND", "Batch not found")
            if any(j["state"] in ("RECEIVED", "PROCESSING") for j in jobs):
                raise ApiError(409, "BATCH_BUSY", "Batch is still processing")
            for j in jobs:
                shutil.rmtree(job_dir(self.settings.data_dir, j["job_id"]), ignore_errors=True)
                self.progress.pop(j["job_id"], None)
            self.vault.delete_batch(batch_id)
            store.delete_batch(batch_id)
        return {"deleted": True, "batch_id": batch_id, "jobs": len(jobs)}

    def sweep(self) -> int:
        """TR-SEC-06: delete batches older than ``retention.job_ttl_hours``."""
        cutoff = datetime.now(tz=UTC) - timedelta(hours=self.policy.retention.job_ttl_hours)
        with self.store() as store:
            old = store.batches_before(cutoff.isoformat(timespec="microseconds"))
        done = 0
        for b in old:
            try:
                self.delete_batch(b)
                done += 1
            except ApiError:
                continue
        return done

    # ------------------------------------------------------------------ jobs

    def job(self, job_id: str) -> dict[str, Any]:
        import json

        with self.store() as store:
            row = self._job(store, job_id)
            counts: dict[str, int] = {}
            for f in store.findings(job_id):
                if f["decision"] in REDACTING:
                    counts[f["entity_type"]] = counts.get(f["entity_type"], 0) + 1
            run = store.run(job_id)
        state = row["state"]
        prog = self.progress.get(job_id)
        if prog is None or state not in ("RECEIVED", "PROCESSING"):
            prog = {
                "stage": "done" if state not in ("RECEIVED", "PROCESSING") else "queued",
                "done": 1,
                "total": 1,
            }
        js = self._state(job_id) or {}
        unresolved = (
            len(self.review_items(job_id, with_text=False))
            if state == JobState.REVIEW_REQUIRED.value
            else 0
        )
        warnings = [
            f"{i['code']}:{i['locator'].get('part')}"
            for i in js.get("doc", {}).get("coverage", {}).get("issues", [])
        ]
        return {
            "job_id": job_id,
            "batch_id": row["batch_id"],
            "filename": row["filename"],
            "format": row["fmt"],
            "state": state,
            "progress": {k: prog[k] for k in ("stage", "done", "total")},
            "counts_by_type": counts,
            "timings": json.loads(run["timings_json"]) if run else {},
            "warnings": warnings + list(js.get("warnings", [])),
            "deciding_rule": row["rule"] or "",
            "reason": row["reason"] or "",
            "policy_hash": row["policy_hash"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "unresolved_items_count": unresolved,
        }

    def findings(self, job_id: str, include_text: bool) -> list[dict[str, Any]]:
        js = self._state(job_id)
        if js is None:
            with self.store() as store:
                self._job(store, job_id)
            return []
        doc, findings = load_doc(js)
        segs = {s.segment_id: s for s in doc.segments}
        out = []
        for f in findings:
            item = {
                "finding_id": f.finding_id,
                "segment_id": f.segment_id,
                "start": f.start,
                "end": f.end,
                "entity_type": f.entity_type.value,
                "risk": f.risk,
                "tier": f.tier,
                "evidence": _evidence_dicts(f),
                "format_invalid": f.format_invalid,
                "preview": f.preview,
                "decision": f.decision,
                "token": f.token,
                "locator": _locator_dict(f.locator),
            }
            if include_text and f.segment_id in segs:
                item["segment_text"] = segs[f.segment_id].text
            out.append(item)
        return out

    # ------------------------------------------------------------------ review

    def _groups(
        self, findings: list[Finding], reviewed: set[str]
    ) -> dict[tuple[str, str], list[Finding]]:
        groups: dict[tuple[str, str], list[Finding]] = {}
        for f in findings:
            if (
                f.decision == "review"
                and f.finding_id not in reviewed
                and f.entity_type not in REGION_TYPES
            ):
                groups.setdefault((f.entity_type.value, f.value_hmac), []).append(f)
        return groups

    def review_items(self, job_id: str, with_text: bool = True) -> list[dict[str, Any]]:
        with self.store() as store:
            row = self._job(store, job_id)
        if row["state"] != JobState.REVIEW_REQUIRED.value:
            return []
        js = self._state(job_id)
        if js is None:
            return []
        doc, findings = load_doc(js)
        reviewed = set(js.get("reviewed", []))
        segs = {s.segment_id: s for s in doc.segments}
        items: list[dict[str, Any]] = []
        for group in self._groups(findings, reviewed).values():
            f = group[0]
            seg = segs.get(f.segment_id)
            items.append(
                self._item(
                    job_id,
                    f,
                    "finding",
                    len(group),
                    seg.text if (seg and with_text) else None,
                    doc.fmt.value,
                )
            )
        for f in findings:
            if (
                f.entity_type in REGION_TYPES
                and f.decision in REDACTING
                and f.finding_id not in reviewed
            ):
                items.append(self._item(job_id, f, "region", 1, None, doc.fmt.value))
        known = set(js.get("known_residual", []))
        for data, value in zip(js.get("residual", []), js.get("residual_values", []), strict=False):
            if data["value_hmac"] in known:
                continue
            f = Finding.model_validate({**data, "value": value})
            item = self._item(job_id, f, "residual", 1, value if with_text else None, doc.fmt.value)
            item["finding_id"] = f"residual:{f.finding_id}"
            items.append(item)
        return items

    def _item(
        self, job_id: str, f: Finding, kind: str, count: int, text: str | None, fmt: str
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "finding_id": f.finding_id,
            "kind": kind,
            "occurrences": count,
            "segment_id": f.segment_id,
            "start": f.start,
            "end": f.end,
            "entity_type": f.entity_type.value,
            "risk": f.risk,
            "tier": f.tier,
            "preview": f.preview,
            "evidence": _evidence_dicts(f),
            "format_invalid": f.format_invalid,
            "proposed_token": f.token,
            "token": f.token,
            "locator": _locator_dict(f.locator),
        }
        if text is not None:
            item["segment_text"] = text
        thumb = self.thumbnail(job_id, f.locator, fmt)
        if thumb:
            item["thumbnail_data"] = thumb
        return item

    def thumbnail(self, job_id: str, loc: Locator | None, fmt: str) -> str | None:
        """PNG data URI of the redacted output around ``loc`` (masks applied, TR-RV-01)."""
        if loc is None:
            return None
        out_dir = job_dir(self.settings.data_dir, job_id) / "out"
        key = None
        try:
            if fmt == "pdf" and loc.page:
                key = f"page:{loc.page}"
                if (job_id, key) not in self._thumbs:
                    with pymupdf.open(out_dir / "redacted.pdf") as pdf:
                        pix = pdf[loc.page - 1].get_pixmap(dpi=THUMB_DPI, alpha=False)
                        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    self._thumbs[(job_id, key)] = (self._png(img), self.policy.ocr.dpi / THUMB_DPI)
            elif (
                fmt in ("docx", "pptx") and loc.image_ref and loc.part.startswith(("word/", "ppt/"))
            ):
                key = f"media:{loc.part}"
                if (job_id, key) not in self._thumbs:
                    with zipfile.ZipFile(next(out_dir.glob("redacted.*"))) as zf:
                        img = open_image(zf.read(loc.part)).convert("RGB")
                    w = img.width
                    img.thumbnail((THUMB_MAX, THUMB_MAX))
                    self._thumbs[(job_id, key)] = (self._png(img), w / max(img.width, 1))
            elif fmt in ("png", "jpeg", "tiff"):
                key = "image"
                if (job_id, key) not in self._thumbs:
                    img = Image.open(next(out_dir.glob("redacted.*"))).convert("RGB")
                    w = img.width
                    img.thumbnail((THUMB_MAX, THUMB_MAX))
                    self._thumbs[(job_id, key)] = (self._png(img), w / max(img.width, 1))
        except (OSError, StopIteration, KeyError, ValueError):
            return None
        return self._thumbs[(job_id, key)][0] if key and (job_id, key) in self._thumbs else None

    @staticmethod
    def _png(img: Image.Image) -> str:
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def apply_review(
        self, job_id: str, decisions: list[dict[str, Any]], reviewer: str
    ) -> dict[str, Any]:
        jdir = job_dir(self.settings.data_dir, job_id)
        with self.store() as store:
            row = self._job(store, job_id)
            if row["state"] != JobState.REVIEW_REQUIRED.value:
                raise ApiError(
                    409,
                    "INVALID_JOB_STATE",
                    "Decisions are accepted only in REVIEW_REQUIRED",
                    job_id,
                )
            js = self._state(job_id)
            if js is None:
                raise ApiError(409, "STATE_UNAVAILABLE", "Job state is not available", job_id)
            doc, findings = load_doc(js)
            by_id = {f.finding_id: f for f in findings}
            reviewed = set(js.get("reviewed", []))
            known = set(js.get("known_residual", []))
            forced: dict[tuple[str, Any], list[Any]] = {
                (k[0], k[1]): [tuple(b) for b in v] for k, v in js.get("forced_boxes", [])
            }
            residual = {d["finding_id"]: d for d in js.get("residual", [])}
            segs = {s.segment_id: s for s in doc.segments}
            groups = self._groups(findings, reviewed)
            group_of = {f.finding_id: g for g in groups.values() for f in g}
            self._validate(decisions, by_id, group_of, residual, segs)
            values = [f.value for f in findings if len(f.value) >= 4]
            if any(d["action"] == "reject_document" for d in decisions):
                d = next(d for d in decisions if d["action"] == "reject_document")
                store.log_review(
                    job_id, None, reviewer, "reject_document", self._screen(d.get("reason"), values)
                )
                transition(
                    store, job_id, JobState.BLOCKED, rule="review", reason="REVIEWER_REJECTED"
                )
                return {"status": "document_rejected", "applied": 1}
            added: list[Finding] = []
            for d in decisions:
                action, fid = d["action"], d.get("finding_id")
                if fid and fid.startswith("residual:"):
                    rid = fid.split(":", 1)[1]
                    if action == "reject":
                        known.add(residual[rid]["value_hmac"])
                    elif action in ("confirm", "retype"):
                        for key, box in js.get("residual_boxes", {}).get(rid, []):
                            forced.setdefault((key[0], key[1]), []).append(tuple(box))
                        known.add(residual[rid]["value_hmac"])
                elif action in ("confirm", "reject", "retype") and fid:
                    targets = group_of.get(fid) or [by_id[fid]]
                    for f in targets:
                        reviewed.add(f.finding_id)
                        if action == "confirm":
                            by_id[f.finding_id] = f.model_copy(update={"decision": "auto_redact"})
                        elif action == "reject":
                            by_id[f.finding_id] = f.model_copy(
                                update={"decision": "discarded", "token": None}
                            )
                        else:
                            etype = EntityType(d["entity_type"])
                            by_id[f.finding_id] = f.model_copy(
                                update={
                                    "entity_type": etype,
                                    "risk": DEFAULT_RISK[etype],
                                    "decision": "auto_redact",
                                    "token": None,
                                }
                            )
                elif action == "add":
                    added.append(self._added(job_id, len(added), d, segs))
                elif action == "add_region":
                    region = self._added_region(
                        job_id, len(added), d, by_id.get(fid or ""), doc.fmt.value
                    )
                    if region is not None:
                        added.append(region)
                store.log_review(
                    job_id,
                    fid,
                    reviewer,
                    action,
                    self._screen(d.get("justification") or d.get("reason"), values),
                )
            new_findings = [by_id[f.finding_id] for f in findings] + added
            if added:  # added spans seed propagation (TR-RV-03)
                assert self.settings.vault_key is not None
                key = self.settings.vault_key.get_secret_value().encode()
                new_findings = propagate_values([doc], [new_findings], key)[0]
            reviewed.update(f.finding_id for f in new_findings if f.finding_id not in by_id)
            js["findings"] = [f.model_dump(mode="json") for f in new_findings]
            js["values"] = [f.value for f in new_findings]
            js["reviewed"] = sorted(reviewed)
            js["known_residual"] = sorted(known)
            js["forced_boxes"] = [[list(k), [list(b) for b in v]] for k, v in forced.items()]
            self.vault.save_state(jdir, js)
            transition(store, job_id, JobState.PROCESSING, rule="review", reason="REVIEW_SUBMITTED")
        self._thumbs = {k: v for k, v in self._thumbs.items() if k[0] != job_id}
        self.on_progress(job_id, "re_verification", 0, 1)
        self.executor.submit(self._rerun, job_id)
        return {"status": "decisions_accepted", "applied": len(decisions)}

    def _validate(
        self,
        decisions: list[dict[str, Any]],
        by_id: dict[str, Finding],
        group_of: dict[str, list[Finding]],
        residual: dict[str, Any],
        segs: dict[str, Any],
    ) -> None:
        if not decisions:
            raise ApiError(422, "NO_DECISIONS", "No decisions submitted")
        for d in decisions:
            action, fid = d.get("action"), d.get("finding_id")
            if action not in ACTIONS:
                raise ApiError(422, "UNKNOWN_ACTION", "Unknown review action")
            if action in ("confirm", "reject", "retype"):
                if not fid:
                    raise ApiError(422, "FINDING_REQUIRED", f"{action} needs a finding_id")
                if fid.startswith("residual:"):
                    if fid.split(":", 1)[1] not in residual:
                        raise ApiError(422, "FINDING_UNKNOWN", "Unknown residual item")
                    continue
                f = by_id.get(fid)
                if f is None:
                    raise ApiError(422, "FINDING_UNKNOWN", "Unknown finding")
                if action == "reject":
                    if f.risk == "HIGH" and f.tier == "DETERMINISTIC":
                        raise ApiError(
                            422,
                            "REJECT_FORBIDDEN",
                            "HIGH-risk deterministic findings cannot be rejected",
                        )
                    if not (d.get("justification") or "").strip():
                        raise ApiError(
                            422, "JUSTIFICATION_REQUIRED", "A rejection needs a justification"
                        )
                if action == "retype" and d.get("entity_type") not in EntityType.__members__:
                    raise ApiError(422, "UNKNOWN_TYPE", "Unknown entity type")
            if action == "add":
                seg = segs.get(d.get("segment_id", ""))
                s, e = d.get("start"), d.get("end")
                if (
                    seg is None
                    or not isinstance(s, int)
                    or not isinstance(e, int)
                    or not 0 <= s < e <= len(seg.text)
                ):
                    raise ApiError(
                        422, "BAD_SPAN", "The added span does not lie inside the segment"
                    )
                if d.get("entity_type") not in EntityType.__members__:
                    raise ApiError(422, "UNKNOWN_TYPE", "Unknown entity type")
            if action == "add_region":
                bbox = d.get("bbox")
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    raise ApiError(422, "BAD_REGION", "A region needs a bbox of four numbers")

    @staticmethod
    def _screen(text: str | None, values: list[str]) -> str | None:
        """Justifications are free text: withhold any finding value that appears in them."""
        if not text:
            return None
        out = text[:500]
        for v in sorted(values, key=len, reverse=True):
            if v.casefold() in out.casefold():
                import re

                out = re.sub(re.escape(v), "[withheld]", out, flags=re.I)
        return out

    def _added(self, job_id: str, n: int, d: dict[str, Any], segs: dict[str, Any]) -> Finding:
        from cleargate.core.models import Evidence

        seg = segs[d["segment_id"]]
        etype = EntityType(d["entity_type"])
        value = seg.text[d["start"] : d["end"]]
        assert self.settings.vault_key is not None
        key = self.settings.vault_key.get_secret_value().encode()
        return Finding(
            finding_id=f"{job_id}:a{n:04d}",
            segment_id=seg.segment_id,
            start=d["start"],
            end=d["end"],
            entity_type=etype,
            risk=DEFAULT_RISK[etype],
            tier="DETERMINISTIC",
            evidence=[Evidence(detector="reviewer", layer="L2", rule_id="reviewer:add")],
            value=value,
            value_hmac=value_hmac(key, value, etype),
            preview=preview(value, etype),
            decision="auto_redact",
            locator=seg.locator,
        )

    def _added_region(
        self, job_id: str, n: int, d: dict[str, Any], ref: Finding | None, fmt: str
    ) -> Finding | None:
        from cleargate.core.models import Evidence

        base = (
            ref.locator
            if ref and ref.locator
            else Locator(part="page" if fmt == "pdf" else "image", page=d.get("page") or 1)
        )
        key = (
            f"page:{base.page}"
            if fmt == "pdf"
            else f"media:{base.part}"
            if fmt in ("docx", "pptx")
            else "image"
        )
        scale = self._thumbs.get(
            (job_id, key), ("", float(self.policy.ocr.dpi) / THUMB_DPI if fmt == "pdf" else 1.0)
        )[1]
        x0, y0, x1, y1 = (float(v) * scale for v in d["bbox"])
        loc = base.model_copy(update={"bbox": (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))})
        return Finding(
            finding_id=f"{job_id}:ar{n:04d}",
            segment_id=f"{job_id}:region-added{n}",
            start=0,
            end=0,
            entity_type=EntityType.UNREADABLE_IMAGE_REGION,
            risk="HIGH",
            tier="DETERMINISTIC",
            evidence=[Evidence(detector="reviewer", layer="REGION", rule_id="reviewer:add_region")],
            value="",
            value_hmac=f"region-added-{job_id}-{n}",
            preview="[added region]",
            decision="auto_redact",
            locator=loc,
        )

    def _rerun(self, job_id: str) -> None:
        pipeline = self.worker()
        try:
            row = pipeline.store.get_job(job_id)
            assert row is not None
            ctx = pipeline.context(job_id, row["batch_id"], create=False)
            js = self.vault.load_state(ctx.job_dir)
            ctx.reviewed = set(js.get("reviewed", []))
            ctx.known_residual = set(js.get("known_residual", []))
            ctx.forced_boxes = {
                (k[0], k[1]): [tuple(b) for b in v] for k, v in js.get("forced_boxes", [])
            }
            doc, findings = load_doc(js)
            pipeline.rerun(job_id, findings, doc, ctx)
        except Exception:
            log.error("review re-run crashed", exc_info=True, extra={"job_id": job_id})
            if pipeline.store.job_state(job_id) is JobState.PROCESSING:
                from cleargate.gate.machine import fail

                fail(pipeline.store, job_id, ErrorCode.INTERNAL)
        self.progress[job_id] = {"stage": "done", "done": 1, "total": 1, "at": time.time()}

    # ------------------------------------------------------------------ outputs

    def report(self, job_id: str, fmt: str) -> dict[str, Any] | str:
        with self.store() as store:
            self._job(store, job_id)
            data = build_report(store, job_id, self._state(job_id))
            if fmt == "md":
                body = to_markdown(data)
                store.save_report(job_id, "md", digest(body), body)
                return body
            import json

            body = json.dumps(data, sort_keys=True)
            store.save_report(job_id, "json", digest(body), body)
            return data

    def _safe(self, store: MetaStore, job_id: str) -> tuple[Any, Path]:
        row = self._job(store, job_id)
        if row["state"] != JobState.VALIDATED_SAFE.value:
            raise ApiError(
                403,
                "FORBIDDEN_OUTPUT_UNVERIFIED",
                "Outputs are available only in VALIDATED_SAFE",
                job_id,
            )
        sanitized = job_dir(self.settings.data_dir, job_id) / "out" / "sanitized.txt"
        stored = store.handle_json(job_id)
        try:
            if stored is None:
                raise HandleError(job_id=job_id, reason="not_issued")
            assert self.settings.gate_key is not None
            verify_against_store(
                store, SafeHandle.from_json(stored), self.settings.gate_key, sanitized
            )
        except HandleError as exc:
            raise ApiError(409, "HANDLE_INVALID", exc.message, job_id) from None
        return row, sanitized

    def artifact(self, job_id: str, name: str) -> tuple[Path, str]:
        with self.store() as store:
            row, sanitized = self._safe(store, job_id)
        if name == "sanitized.txt":
            return sanitized, f"sanitized-{Path(row['filename']).stem}.txt"
        out = next((job_dir(self.settings.data_dir, job_id) / "out").glob("redacted.*"), None)
        if out is None or name.lower() != out.name.lower():
            raise ApiError(
                404,
                "ARTIFACT_NOT_FOUND",
                f"No artifact {name}; this job produced {out.name if out else 'none'}",
                job_id,
            )
        return out, f"redacted-{row['filename']}"

    def handoff(self, job_id: str) -> dict[str, Any]:
        with self.store() as store:
            row = self._job(store, job_id)
            if row["state"] != JobState.VALIDATED_SAFE.value:
                raise ApiError(
                    409, "CONFLICT_NOT_SAFE", "Handoff is permitted only in VALIDATED_SAFE", job_id
                )
            _, sanitized = self._safe(store, job_id)
            assert self.settings.gate_key is not None
            handle = SafeHandle.from_json(store.handle_json(job_id) or "")
            try:
                result = AIHandoff(store, self.settings.gate_key, self.policy).send(
                    handle, sanitized
                )
            except ClearGateError as exc:
                raise ApiError(409, exc.code.value, exc.message, job_id) from None
        return {
            "status": "completed",
            "handoff_id": f"ho-{uuid.uuid4().hex[:12]}",
            "agent": result.agent,
            "result": result.summary,
            "token_counts": result.token_counts,
            "message": "The AI agent received only the sanitized text, via a verified SafeHandle.",
        }
