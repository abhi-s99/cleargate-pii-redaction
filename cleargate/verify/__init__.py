"""Independent verification V1..V6 (TRD 8.1, ADR-08).

``IndependentVerifier.verify`` checks the **output file**, not the writer's own account:

* V1 reopen through two parsers (``reextract.reopen``); failure ends the job ``FAILED``;
* V2 leak search of every redacted value and its variants over the raw re-read output
  (``reextract.haystacks``) and the sanitized text (``leak``);
* V3 residual scan of the re-extracted output CDM (``residual``);
* V4 coverage and unit counts (``coverage``);
* V5 token consistency against the vault (``structure.consistency``);
* V6 SRS and CRS (``structure``).

Any exception here is not caught: the pipeline turns it into G0 ``FAILED`` (verification
crashed is not verified). Residual non-deterministic hits are returned on the instance for
the review queue (``last_residual``), counts only in the report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cleargate.core.models import Document, Finding, VerificationReport
from cleargate.verify import coverage, leak, reextract, residual, structure


def masked_rasters(actions: list[Any]) -> set[str]:
    """Rasters the writer burned masks into (``part`` or ``page:<n>``)."""
    out = set()
    for a in actions:
        if a.method == "pixel_mask" and a.applied:
            loc = a.locator
            out.add(f"{loc.part}:{loc.page}" if loc.part == "page" else loc.part)
    return out


class IndependentVerifier:
    name = "independent-verifier"
    version = "0.7.0"

    def __init__(self) -> None:
        self.last_residual: dict[str, list[Finding]] = {}
        self.last_repair: dict[
            str, dict[tuple[str, str | int], list[tuple[float, float, float, float]]]
        ] = {}
        self.last_residual_boxes: dict[str, dict[str, list[Any]]] = {}
        self.last_output_doc: dict[str, Document] = {}

    def verify(
        self, src: Path, result: Any, doc: Document, findings: list[Finding], ctx: Any
    ) -> VerificationReport:
        out_path: Path = result.output_path
        fmt = doc.fmt
        ok = reextract.reopen(out_path, fmt)
        if not ok:
            return VerificationReport(
                job_id=ctx.job_id, checks_run=frozenset({"V1"}), reopen_ok=False
            )
        segs = {s.segment_id: s for s in doc.segments}
        texts, missed = reextract.haystacks(out_path, fmt, ctx)
        sanitized = Path(result.sanitized_path).read_text(encoding="utf-8")
        needle_map = leak.needles(findings, segs)
        hits = leak.leak_hits(needle_map, [*texts, sanitized])
        rasters = reextract.RASTERS.pop(ctx.job_id, [])
        if hits:  # where in the output rasters: input for one repair pass (ADR-30)
            self.last_repair[ctx.job_id] = leak.locate(needle_map, rasters)
        out_doc = self._reextract_doc(out_path, fmt, ctx)
        det, other = residual.residual(out_doc, findings, ctx)
        if det:  # new identifiers visible in output rasters: located for the repair pass
            boxes = self.last_repair.setdefault(ctx.job_id, {})
            for key, bxs in residual.raster_boxes_of(out_doc, det).items():
                boxes.setdefault(key, []).extend(bxs)
        self.last_residual[ctx.job_id] = other
        self.last_residual_boxes[ctx.job_id] = residual.raster_boxes_by_finding(out_doc, other)
        self.last_output_doc[ctx.job_id] = out_doc
        vault = ctx.vault if hasattr(ctx, "vault") else None
        entries = vault.entries(ctx.batch_id) if vault else {}
        persons = vault.person_tokens(ctx.batch_id) if vault else {}
        consistent = (
            structure.consistency([sanitized, *texts], entries, persons, findings)
            if vault
            else False
        )
        return VerificationReport(
            job_id=ctx.job_id,
            checks_run=frozenset(
                {"V1", "V2", "V3", "V4", "V5", "V6"} if vault else {"V1", "V2", "V3", "V4", "V6"}
            ),
            reopen_ok=True,
            leak_hits=sum(hits.values()),
            residual_deterministic=len(det),
            residual_other=len(other),
            uninspected_unmasked=coverage.uninspected_unmasked(
                doc, out_doc, result.masked_parts, masked_rasters(result.actions)
            )
            + missed,
            unit_counts_equal=coverage.units_equal(doc, out_doc),
            consistency_ok=consistent,
            srs=structure.srs(doc, out_doc),
            crs=structure.crs(doc, findings),
            verifiers={self.name: self.version},
        )

    @staticmethod
    def _reextract_doc(path: Path, fmt: Any, ctx: Any) -> Document:
        from cleargate.pipeline import default_extractor

        out_ctx = ctx.__class__(
            **{**ctx.__dict__, "job_id": f"{ctx.job_id}-out", "progress": None, "timings": {}}
        )
        return default_extractor(fmt).extract(path, fmt, out_ctx)
