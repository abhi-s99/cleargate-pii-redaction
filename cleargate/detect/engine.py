"""Detection engine: layers L1..L5, merge, allowlist, tiers, decisions (TRD 6, ADR-04).

``DetectionEngine.detect_batch`` runs over every document of a batch so the person registry
(and with it person tokens) is shared (TR-DT-15 point 5):

1. rule layers on every segment: L1 validators, phone, L2 label-anchored (inline, column
   headers, row labels, OCR confusion), L4 context rules, and person metadata fields
   (``dc:creator``, ``cp:lastModifiedBy``, PDF ``author``, author attributes, EXIF artist),
   which are label-anchored by construction;
2. L3 NER (Presidio + spaCy) on pre-split sub-spans;
3. a first merge seeds the registry with PERSON findings of tier CORROBORATED or better;
4. context rules run again with the registry (initials rule), and the L5 sweep adds
   registry matches (exact, fuzzy on OCR, unique surname);
5. final merge, allowlist (NER-only suppression), tiers and decisions;
6. faces and unreadable regions become region findings (TR-DT-16).

Profiles: ``default``; ``verify`` (V3 residual scan: allowlist off, propagation on,
``review_threshold * 0.5``, spans touching ClearGate tokens ignored).
"""

from __future__ import annotations

import itertools
import re
from dataclasses import replace
from typing import Any, Literal

from cleargate.core.config import Policy
from cleargate.core.models import (
    DEFAULT_RISK,
    Document,
    EntityType,
    Finding,
    Locator,
    Segment,
)
from cleargate.detect.allowlist import Allowlist
from cleargate.detect.base import (
    NUMERIC_TYPES,
    Candidate,
    DocContext,
    candidate,
    evidence,
    overlaps_token,
    preview,
    value_hmac,
)
from cleargate.detect.merge import decide, merge, tier_of
from cleargate.detect.ner import NerRecognizer, OrgSpan
from cleargate.detect.presplit import sub_spans
from cleargate.detect.propagate import Propagator
from cleargate.detect.recognizers.context import NAME_RE, ContextRecognizer, person_score
from cleargate.detect.recognizers.deterministic import l1_recognizers
from cleargate.detect.recognizers.label_anchored import LabelAnchoredRecognizer
from cleargate.detect.recognizers.phone import PhoneRecognizer
from cleargate.detect.registry import PersonRegistry, canonical_key

Profile = Literal["default", "verify"]
PERSON_META = re.compile(
    r"(?:^|/@|:)(?:creator|lastModifiedBy|author|Author|Artist|XPAuthor|initials|userId|"
    r"providerId|name|CameraOwnerName|title)$"
)
PERSON_META_KEYS = re.compile(
    r"^(?:dc:creator|cp:lastModifiedBy|author|exif:Artist|exif:XPAuthor|exif:CameraOwnerName)$"
)
ATTR_KEYS = re.compile(r"/@(?:author|initials|userId|providerId|name|lastModifiedBy)$")
REGION_TYPE = {"face": EntityType.PHOTO, "unreadable": EntityType.UNREADABLE_IMAGE_REGION}


def person_metadata(seg: Segment) -> bool:
    key = seg.locator.xpath or ""
    if seg.kind != "metadata":
        return False
    if seg.locator.part == "page-annots" and key.endswith(":title"):
        return True  # PDF annotation author
    return bool(PERSON_META_KEYS.match(key) or ATTR_KEYS.search(key))


class DetectionEngine:
    name = "detection-engine"
    version = "0.5.0"

    def __init__(
        self, policy: Policy, *, profile: Profile = "default", use_ner: bool = True
    ) -> None:
        self.policy = policy
        self.profile = profile
        self.verify = profile == "verify"
        factor = 0.5 if self.verify else 1.0
        self.threshold = policy.detection.review_threshold * factor
        self.enabled = set(policy.entities.enabled) | {EntityType.UNREADABLE_IMAGE_REGION}
        self.rules: list[Any] = [
            *l1_recognizers(list(policy.entities.employee_id_patterns)),
            PhoneRecognizer(),
            LabelAnchoredRecognizer(),
        ]
        self.context = ContextRecognizer()
        self.ner = (
            NerRecognizer(policy.detection.ner_model, skip_tokens=self.verify) if use_ner else None
        )

    def versions(self) -> dict[str, str]:
        out = {r.name: r.version for r in self.rules}
        out[self.context.name] = self.context.version
        if self.ner:
            out[self.ner.name] = self.ner.version
        out[self.name] = self.version
        return out

    # ------------------------------------------------------------------ public API

    def detect(
        self, doc: Document, ctx: Any, registry: PersonRegistry | None = None
    ) -> list[Finding]:
        return self.detect_batch([doc], key=_key(ctx), registry=registry)[0]

    def detect_batch(
        self,
        docs: list[Document],
        *,
        key: bytes,
        registry: PersonRegistry | None = None,
    ) -> list[list[Finding]]:
        registry = registry if registry is not None else PersonRegistry(key)
        staged: list[tuple[Document, DocContext, list[Candidate], list[OrgSpan]]] = []
        for doc in docs:
            dctx = DocContext.build(doc, registry)
            cands = self._rules(doc, dctx)
            orgs: list[OrgSpan] = []
            if self.ner:
                people, orgs = self.ner.analyze_batch(doc.segments)
                cands += people
                cands += list_siblings(doc, people)
            staged.append((doc, dctx, cands, orgs))
        if not self.verify:
            for _doc, _dctx, cands, _orgs in staged:
                for c in merge(cands, self.threshold):
                    if (
                        c.entity_type is EntityType.PERSON
                        and not c.discard_reason
                        and tier_of(c, self.threshold) in ("DETERMINISTIC", "CORROBORATED")
                    ):
                        registry.add(c.value)
        prop = Propagator(
            registry,
            fuzzy_ratio=self.policy.detection.fuzzy_ocr_ratio,
            surname_only=self.policy.detection.surname_only_propagation,
            skip_tokens=self.verify,
        )
        results = []
        for doc, dctx, cands, orgs in staged:
            more: list[Candidate] = []
            for seg in doc.segments:
                more += self.context.analyze(seg, dctx)  # second pass: initials vs registry
                more += prop.sweep(seg)
            merged = merge(cands + more, self.threshold)
            allow = (
                None if self.verify else Allowlist.build(self.policy.allowlist, orgs, dctx.segments)
            )
            results.append(self._finalize(doc, dctx, merged, allow, registry))
        if not self.verify:
            results = propagate_values(docs, results, registry.hmac_key)
        return results

    # ------------------------------------------------------------------ internals

    def _rules(self, doc: Document, dctx: DocContext) -> list[Candidate]:
        out: list[Candidate] = []
        for seg in doc.segments:
            if person_metadata(seg):
                stripped = seg.text.strip()
                if stripped and not stripped.startswith("[REDACTED"):
                    s = seg.text.index(stripped)
                    out.append(
                        candidate(
                            seg,
                            s,
                            s + len(stripped),
                            EntityType.PERSON,
                            evidence("metadata", "L2", f"metadata:{_meta_key(seg)}", score=1.0),
                        )
                    )
            for r in self.rules:
                out += r.analyze(seg, dctx)
            out += self.context.analyze(seg, dctx)
        if self.verify:
            out = [
                c
                for c in out
                if not overlaps_token(dctx.segments[c.segment_id].text, c.start, c.end)
            ]
        return [c for c in out if c.entity_type in self.enabled]

    def _covered(
        self, c: Candidate, merged: list[Candidate], dctx: DocContext, doc: Document
    ) -> bool:
        """A weak signal already removed by a stronger redaction (ADR-28).

        * inside a DETERMINISTIC ``HOME_ADDRESS`` span (the outer span wins anyway);
        * on an OCR line whose box lies inside a masked face/unreadable region.
        """
        if tier_of(c, self.threshold) not in ("SINGLE_SIGNAL", "LOW"):
            return False
        for o in merged:
            if (
                o is not c
                and o.entity_type is EntityType.HOME_ADDRESS
                and o.segment_id == c.segment_id
                and o.start <= c.start
                and c.end <= o.end
                and tier_of(o, self.threshold) == "DETERMINISTIC"
            ):
                return True
        loc = dctx.segments[c.segment_id].locator
        if loc.bbox is None:
            return False
        cx, cy = (loc.bbox[0] + loc.bbox[2]) / 2, (loc.bbox[1] + loc.bbox[3]) / 2
        for r in doc.regions:
            rl = r.locator
            if (rl.part, rl.page, rl.slide, rl.image_ref) != (
                loc.part,
                loc.page,
                loc.slide,
                loc.image_ref,
            ):
                continue
            if rl.bbox and rl.bbox[0] <= cx <= rl.bbox[2] and rl.bbox[1] <= cy <= rl.bbox[3]:
                return True
        return False

    def _finalize(
        self,
        doc: Document,
        dctx: DocContext,
        merged: list[Candidate],
        allow: Allowlist | None,
        registry: PersonRegistry,
    ) -> list[Finding]:
        order = {s.segment_id: s.order_index for s in doc.segments}
        merged = [
            c
            for c in merged
            if c.entity_type in self.enabled and not self._covered(c, merged, dctx, doc)
        ]
        merged.sort(key=lambda c: (order.get(c.segment_id, 0), c.start, -c.length))
        key = registry.hmac_key
        findings: list[Finding] = []
        for c in merged:
            seg = dctx.segments[c.segment_id]
            value = seg.text[c.start : c.end]
            tier = tier_of(c, self.threshold)
            decision = decide(c, tier)
            ev = list(c.evidence)
            if allow is not None and decision != "discarded":
                term = allow.suppresses(c, registry)
                if term is not None:
                    decision = "suppressed"
                    ev.append(evidence("allowlist", "L3", "allowlist:term"))
            if c.discard_reason:
                ev.append(evidence("policy", ev[0].layer, f"discard:{c.discard_reason}"))
            person_key = c.person_key
            if c.entity_type is EntityType.PERSON and person_key is None:
                resolved = registry.resolve(value) or canonical_key(value)
                person_key = registry.person_key(resolved)
            findings.append(
                Finding(
                    finding_id=f"{doc.doc_id}:f{len(findings):04d}",
                    segment_id=c.segment_id,
                    start=c.start,
                    end=c.end,
                    entity_type=c.entity_type,
                    risk=DEFAULT_RISK[c.entity_type],
                    tier=tier,
                    evidence=ev,
                    format_invalid=c.format_invalid,
                    value=value,
                    value_hmac=value_hmac(key, value, c.entity_type),
                    preview=preview(value, c.entity_type),
                    person_key=person_key,
                    decision=decision,
                    locator=seg.locator,
                )
            )
        for i, region in enumerate(doc.regions):
            etype = REGION_TYPE[region.kind]
            ref = f"{region.locator.part}:{region.locator.page}:{region.locator.bbox}"
            findings.append(
                Finding(
                    finding_id=f"{doc.doc_id}:r{i:04d}",
                    segment_id=f"{doc.doc_id}:region{i}",
                    start=0,
                    end=0,
                    entity_type=etype,
                    risk="HIGH",
                    tier="DETERMINISTIC",
                    evidence=[
                        evidence(
                            "face_detector" if region.kind == "face" else "ocr_confidence",
                            "REGION",
                            f"region:{region.kind}",
                            score=region.mean_conf,
                        )
                    ],
                    value="",
                    value_hmac=value_hmac(key, ref, etype),
                    preview=f"[{region.kind} region]",
                    decision="auto_redact",
                    locator=region.locator,
                )
            )
        return findings


def _value_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def propagate_values(
    docs: list[Document], results: list[list[Finding]], key: bytes
) -> list[list[Finding]]:
    """Every other occurrence of a redacted value becomes a linked finding (ADR-28).

    Detection can miss a repeated value (an OCR line, a product of an earlier decision); the
    writer, the sanitized text and V2 must all agree, so each redacted value (4+ characters,
    not a number shorter than 6 digits) and each redacted email's local part (6+) is matched
    in every segment of the batch: case-sensitive for one-word values (``Grace`` is not
    ``grace period``), case-insensitive otherwise, word-bounded. A copy inherits the type,
    tier, decision and person of its source, with L5 evidence ``value_propagation``.
    """
    sources: dict[str, Finding] = {}
    for findings in results:
        for f in findings:
            if f.decision not in ("auto_redact", "review") or f.entity_type in REGION_TYPE.values():
                continue
            v = f.value.strip()
            if len(v) >= 4 and not (v.isdigit() and len(v) < 6):
                prev = sources.get(_value_key(v))
                if prev is None or (prev.decision == "review" and f.decision == "auto_redact"):
                    sources[_value_key(v)] = f
            if f.entity_type is EntityType.EMAIL_ADDRESS and "@" in v:
                local = v.split("@", 1)[0]
                if len(local) >= 6 and not local.isdigit():
                    sources.setdefault(_value_key(local), f)
    if not sources:
        return results
    # Numbers of 6+ digits also match in any formatting: "+1 (415) 555-0132" vs "415 555 0132".
    numeric: dict[str, Finding] = {}
    for f in sources.values():
        digits = re.sub(r"\D", "", f.value)
        if f.entity_type in NUMERIC_TYPES and len(digits) >= 6:
            numeric.setdefault(digits, f)
    single = [k for k in sources if " " not in k]
    multi = [k for k in sources if " " in k]
    patterns: list[re.Pattern[str]] = []
    if multi:
        alts = "|".join(
            re.escape(k).replace(r"\ ", r"\s+") for k in sorted(multi, key=len, reverse=True)
        )
        patterns.append(re.compile(rf"(?<![A-Za-z0-9])({alts})(?![A-Za-z0-9])", re.I))
    if single:
        originals = sorted(
            {sources[k].value.strip() if _value_key(sources[k].value) == k else k for k in single},
            key=len,
            reverse=True,
        )
        cased = [o for o in originals if " " not in o]
        if cased:
            patterns.append(
                re.compile(
                    r"(?<![A-Za-z0-9])("
                    + "|".join(re.escape(o) for o in cased)
                    + r")(?![A-Za-z0-9])"
                )
            )
    digit_rx = (
        re.compile(
            r"(?<![\d])("
            + "|".join(r"[\s\-./()]{0,3}".join(d) for d in sorted(numeric, key=len, reverse=True))
            + r")(?![\d])"
        )
        if numeric
        else None
    )
    out: list[list[Finding]] = []
    for doc, findings in zip(docs, results, strict=True):
        covered: dict[str, list[tuple[int, int]]] = {}
        for f in findings:
            if f.decision in ("auto_redact", "review", "suppressed"):
                covered.setdefault(f.segment_id, []).append((f.start, f.end))
        extra: list[Finding] = []

        def add(
            seg: Segment,
            s: int,
            e: int,
            src: Finding,
            covered: dict[str, list[tuple[int, int]]] = covered,
            extra: list[Finding] = extra,
            doc: Document = doc,
        ) -> None:
            covered.setdefault(seg.segment_id, []).append((s, e))
            value = seg.text[s:e]
            extra.append(
                src.model_copy(
                    update={
                        "finding_id": f"{doc.doc_id}:v{len(extra):04d}",
                        "segment_id": seg.segment_id,
                        "start": s,
                        "end": e,
                        "evidence": [
                            evidence(
                                "value_propagation",
                                "L5",
                                "value_propagation",
                                score=src.evidence[0].raw_score if src.evidence else None,
                            ),
                            *[
                                ev.model_copy(update={"rule_id": f"source:{ev.rule_id}"})
                                for ev in src.evidence[:2]
                            ],
                        ],
                        "value": value,
                        "value_hmac": value_hmac(key, value, src.entity_type),
                        "preview": preview(value, src.entity_type),
                        "locator": seg.locator,
                        "token": None,
                    }
                )
            )

        def free(
            seg: Segment, s: int, e: int, covered: dict[str, list[tuple[int, int]]] = covered
        ) -> bool:
            return not any(a < e and s < b for a, b in covered.get(seg.segment_id, []))

        for seg in doc.segments:
            for rx in patterns:
                for m in rx.finditer(seg.text):
                    src = sources.get(_value_key(m.group(1)))
                    if src is not None and free(seg, m.start(1), m.end(1)):
                        add(seg, m.start(1), m.end(1), src)
            if numeric and digit_rx is not None:
                for m in digit_rx.finditer(seg.text):
                    src = numeric.get(re.sub(r"\D", "", m.group(1)))
                    if src is not None and free(seg, m.start(1), m.end(1)):
                        add(seg, m.start(1), m.end(1), src)
        # A value broken over two OCR lines of the same raster (V2 reads the lines joined).
        lines = [
            s for s in sorted(doc.segments, key=lambda x: x.order_index) if s.kind == "ocr_line"
        ]
        for a, b in itertools.pairwise(lines):
            la, lb = a.locator, b.locator
            if (la.part, la.page, la.slide, la.image_ref) != (
                lb.part,
                lb.page,
                lb.slide,
                lb.image_ref,
            ):
                continue
            joined = a.text + " " + b.text
            cut = len(a.text)
            for rx in [*patterns, *([digit_rx] if digit_rx is not None else [])]:
                for m in rx.finditer(joined):
                    s, e = m.start(1), m.end(1)
                    if not (s < cut < e):
                        continue
                    src = sources.get(_value_key(m.group(1))) or numeric.get(
                        re.sub(r"\D", "", m.group(1))
                    )
                    if src is None or not free(a, s, cut) or not free(b, 0, e - cut - 1):
                        continue
                    add(a, s, cut, src)
                    if e - cut - 1 > 0:
                        add(b, 0, e - cut - 1, src)
        out.append(findings + extra)
    return out


def list_siblings(doc: Document, people: list[Candidate]) -> list[Candidate]:
    """Name-shaped items of a delimiter list in which another item is a PERSON (ADR-28).

    The model misses some names once a ``/``-separated cell is split (TR-DT-01); a sibling
    of recognised names in the same list gets L4 evidence ``context.list_sibling``.
    """
    by_seg: dict[str, list[Candidate]] = {}
    for c in people:
        by_seg.setdefault(c.segment_id, []).append(c)
    out: list[Candidate] = []
    for seg in doc.segments:
        found = by_seg.get(seg.segment_id)
        if not found:
            continue
        pieces = sub_spans(seg)
        if len(pieces) < 2:
            continue
        for s, e in pieces:
            inside = [c for c in found if c.start < e and s < c.end]
            if any(c.start <= s and e <= c.end for c in inside):
                continue  # NER already covers the whole item
            if NAME_RE.fullmatch(seg.text, s, e):  # missed, or only partly tagged ("Cyrus")
                score = person_score(seg.text[s:e])
                if score:
                    out.append(
                        candidate(
                            seg,
                            s,
                            e,
                            EntityType.PERSON,
                            evidence("context", "L4", "context.list_sibling", score=score),
                            score=score,
                        )
                    )
    return out


def _meta_key(seg: Segment) -> str:
    key = seg.locator.xpath or ""
    return key.rsplit("/@", 1)[-1] if "/@" in key else key


def _key(ctx: Any) -> bytes:
    vk = ctx.settings.vault_key
    return vk.get_secret_value().encode() if vk is not None else b""


def finding_locator(f: Finding) -> Locator | None:
    return f.locator


def redacted(findings: list[Finding]) -> list[Finding]:
    """Findings the writers must apply (auto-redact, plus redact-and-review)."""
    return [f for f in findings if f.decision in ("auto_redact", "review")]


def with_decision(f: Finding, decision: str) -> Finding:
    return f.model_copy(update={"decision": decision})


__all__ = ["DetectionEngine", "redacted", "replace"]
