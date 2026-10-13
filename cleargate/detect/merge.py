"""Merge, tiering and decisions (TRD 6.3, ADR-04).

``merge(candidates)`` is a pure function from candidates to candidates:

1. identical ``(segment, start, end, type)`` hits are combined (evidence union);
2. overlapping hits of the **same** type are unioned into one span;
3. overlapping hits of **compatible** types are both kept (``PERSON`` inside a
   ``HOME_ADDRESS``: the outer span wins at redaction time);
4. overlapping hits of **conflicting** types: the higher priority survives (HIGH-risk
   DETERMINISTIC > MEDIUM DETERMINISTIC > CORROBORATED > SINGLE_SIGNAL > LOW, then the longer
   span) and keeps the loser's evidence, tagged ``merged:<TYPE>:<rule>`` so it does not count
   towards the winner's tier. Two HIGH-risk DETERMINISTIC hits are unioned, so a HIGH-risk
   deterministic span is never dropped.

Passes repeat until nothing changes, so ``merge(merge(x)) == merge(x)`` and the result does
not depend on input order (hypothesis tests).

``tier_of`` implements TRD 6.3 point 4 and ``decide`` point 5.
"""

from __future__ import annotations

from dataclasses import replace

from cleargate.core.models import DEFAULT_RISK, Decision, EntityType, Evidence, Tier
from cleargate.detect.base import Candidate

COMPATIBLE = frozenset({frozenset({EntityType.PERSON, EntityType.HOME_ADDRESS})})
TIER_RANK = {"DETERMINISTIC": 0, "CORROBORATED": 1, "SINGLE_SIGNAL": 2, "LOW": 3}
INDEPENDENT = frozenset({"L3", "L4", "L5"})


def own_evidence(c: Candidate) -> list[Evidence]:
    return [e for e in c.evidence if not e.rule_id.startswith("merged:")]


def tier_of(c: Candidate, review_threshold: float) -> Tier:
    own = own_evidence(c)
    layers = {e.layer for e in own}
    if layers & {"L1", "L2"}:
        return "DETERMINISTIC"
    # An exact full-name match of a registered (already corroborated) person (ADR-28).
    if len(layers & INDEPENDENT) >= 2 or any(e.rule_id == "registry.exact_full" for e in own):
        return "CORROBORATED"
    return "SINGLE_SIGNAL" if c.score >= review_threshold else "LOW"


def priority(c: Candidate, review_threshold: float) -> tuple[int, int, int]:
    tier = tier_of(c, review_threshold)
    rank = TIER_RANK[tier] * 2
    if tier == "DETERMINISTIC" and DEFAULT_RISK[c.entity_type] != "HIGH":
        rank += 1
    return (rank, -c.length, 0)


def _sort_key(c: Candidate) -> tuple[object, ...]:
    return (
        c.segment_id,
        c.start,
        -c.length,
        c.entity_type.value,
        tuple(sorted((e.layer, e.detector, e.rule_id) for e in c.evidence)),
    )


def _union(a: Candidate, b: Candidate) -> Candidate:
    start, end = min(a.start, b.start), max(a.end, b.end)
    value = a.value
    if (start, end) != (a.start, a.end):
        # Rebuild the value from both pieces; only the span matters downstream.
        left, right = (a, b) if a.start <= b.start else (b, a)
        overlap = left.end - right.start
        value = left.value + right.value[max(0, overlap) :] if right.end > left.end else left.value
    merged = replace(
        a,
        start=start,
        end=end,
        value=value,
        format_invalid=a.format_invalid and b.format_invalid,
        discard_reason=a.discard_reason if a.discard_reason == b.discard_reason else None,
        person_key=a.person_key or b.person_key,
        score=max(a.score, b.score),
    )
    return merged.with_evidence(b.evidence)


def _absorb(winner: Candidate, loser: Candidate) -> Candidate:
    tagged = tuple(
        e
        if e.rule_id.startswith("merged:")
        else e.model_copy(update={"rule_id": f"merged:{loser.entity_type.value}:{e.rule_id}"})
        for e in loser.evidence
    )
    return winner.with_evidence(tagged)


def _combine_identical(cands: list[Candidate]) -> list[Candidate]:
    by_key: dict[tuple[str, int, int, EntityType], Candidate] = {}
    for c in sorted(cands, key=_sort_key):
        key = (c.segment_id, c.start, c.end, c.entity_type)
        by_key[key] = _union(by_key[key], c) if key in by_key else c
    return list(by_key.values())


def _pass(cands: list[Candidate], threshold: float) -> list[Candidate]:
    ordered = sorted(cands, key=lambda c: (priority(c, threshold), _sort_key(c)))
    accepted: list[Candidate] = []
    for c in ordered:
        absorbed = False
        for i, a in enumerate(accepted):
            if not a.overlaps(c):
                continue
            if a.entity_type == c.entity_type:
                accepted[i] = _union(a, c)
                absorbed = True
                break
            if frozenset({a.entity_type, c.entity_type}) in COMPATIBLE:
                continue
            both_high_det = all(
                tier_of(x, threshold) == "DETERMINISTIC" and DEFAULT_RISK[x.entity_type] == "HIGH"
                for x in (a, c)
            )
            merged = _absorb(a, c)
            if both_high_det:
                merged = replace(merged, start=min(a.start, c.start), end=max(a.end, c.end))
            accepted[i] = merged
            absorbed = True
            break
        if not absorbed:
            accepted.append(c)
    return sorted(accepted, key=_sort_key)


def merge(cands: list[Candidate], review_threshold: float = 0.40) -> list[Candidate]:
    current = _combine_identical(cands)
    for _ in range(20):
        nxt = _combine_identical(_pass(current, review_threshold))
        if [(_sort_key(c), c.evidence) for c in nxt] == [
            (_sort_key(c), c.evidence) for c in current
        ]:
            return nxt
        current = nxt
    return current


def decide(c: Candidate, tier: Tier) -> Decision:
    if c.discard_reason:
        return "discarded"
    if tier in ("DETERMINISTIC", "CORROBORATED"):
        return "auto_redact"
    if tier == "SINGLE_SIGNAL":
        return "review"  # redacted now, confirmed by a reviewer (all types are >= MEDIUM)
    return "discarded"
