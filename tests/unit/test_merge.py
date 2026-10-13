"""Merge, tiering and decisions (TRD 6.3), including hypothesis properties (point 6)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from cleargate.core.models import EntityType
from cleargate.detect.base import Candidate, evidence
from cleargate.detect.merge import decide, merge, tier_of

E = EntityType
LAYER_RULES = {
    "L1": ("l1", "rule.l1"),
    "L2": ("label", "rule.l2"),
    "L3": ("ner", "ner.person"),
    "L4": ("context", "label:owner"),
    "L5": ("registry", "registry.exact_abbrev"),
}


def cand(
    start: int, end: int, etype: EntityType, *layers: str, seg: str = "s:0", score: float = 0.6
) -> Candidate:
    evs = tuple(
        evidence(LAYER_RULES[layer][0], layer, LAYER_RULES[layer][1], score=score)  # type: ignore[arg-type]
        for layer in layers
    )
    return Candidate(seg, start, end, etype, evs, value="x" * (end - start), score=score)


def test_tiers() -> None:
    assert tier_of(cand(0, 5, E.US_SSN, "L1"), 0.4) == "DETERMINISTIC"
    assert tier_of(cand(0, 5, E.PHONE_NUMBER, "L2"), 0.4) == "DETERMINISTIC"
    assert tier_of(cand(0, 5, E.PERSON, "L3", "L4"), 0.4) == "CORROBORATED"
    assert tier_of(cand(0, 5, E.PERSON, "L3", "L5"), 0.4) == "CORROBORATED"
    assert tier_of(cand(0, 5, E.PERSON, "L4", "L5"), 0.4) == "CORROBORATED"
    assert tier_of(cand(0, 5, E.PERSON, "L3"), 0.4) == "SINGLE_SIGNAL"
    assert tier_of(cand(0, 5, E.PERSON, "L3", score=0.3), 0.4) == "LOW"


def test_threshold_changes_routing() -> None:
    """FR-07: changing review_threshold in config changes the decision."""
    c = cand(0, 5, E.PERSON, "L3", score=0.45)
    assert decide(c, tier_of(c, 0.40)) == "review"
    assert decide(c, tier_of(c, 0.50)) == "discarded"


def test_decisions() -> None:
    assert decide(cand(0, 5, E.US_SSN, "L1"), "DETERMINISTIC") == "auto_redact"
    assert decide(cand(0, 5, E.PERSON, "L3", "L4"), "CORROBORATED") == "auto_redact"
    assert decide(cand(0, 5, E.PERSON, "L3"), "SINGLE_SIGNAL") == "review"
    assert decide(cand(0, 5, E.PERSON, "L3"), "LOW") == "discarded"


def test_same_type_overlap_is_unioned_with_all_evidence() -> None:
    out = merge([cand(0, 10, E.PERSON, "L3"), cand(3, 14, E.PERSON, "L4")])
    assert [(c.start, c.end) for c in out] == [(0, 14)]
    assert {e.layer for e in out[0].evidence} == {"L3", "L4"}


def test_conflict_keeps_higher_priority_and_retains_evidence() -> None:
    out = merge([cand(0, 12, E.PERSON, "L3"), cand(0, 12, E.EMAIL_ADDRESS, "L1")])
    assert [c.entity_type for c in out] == [E.EMAIL_ADDRESS]
    assert any(e.rule_id.startswith("merged:PERSON:") for e in out[0].evidence)
    assert tier_of(out[0], 0.4) == "DETERMINISTIC"


def test_high_risk_deterministic_beats_medium_deterministic() -> None:
    out = merge([cand(0, 11, E.PHONE_NUMBER, "L1"), cand(0, 11, E.US_SSN, "L1")])
    assert [c.entity_type for c in out] == [E.US_SSN]


def test_person_inside_home_address_is_kept_both() -> None:
    out = merge([cand(0, 40, E.HOME_ADDRESS, "L2"), cand(3, 16, E.PERSON, "L3", "L4")])
    assert sorted(c.entity_type for c in out) == [E.HOME_ADDRESS, E.PERSON]


def test_absorbed_evidence_does_not_upgrade_tier() -> None:
    out = merge([cand(0, 9, E.PERSON, "L3"), cand(0, 9, E.EMPLOYEE_ID, "L4", score=0.9)])
    assert len(out) == 1
    assert tier_of(out[0], 0.4) == "SINGLE_SIGNAL"


# ------------------------------------------------------------------ properties

TYPES = [E.PERSON, E.EMAIL_ADDRESS, E.US_SSN, E.PHONE_NUMBER, E.HOME_ADDRESS, E.IN_PAN]
LAYER_SETS = [("L1",), ("L2",), ("L3",), ("L4",), ("L3", "L4"), ("L5",), ("L3", "L5")]


@st.composite
def candidates(draw: st.DrawFn) -> list[Candidate]:
    n = draw(st.integers(0, 8))
    out = []
    for _ in range(n):
        start = draw(st.integers(0, 30))
        end = start + draw(st.integers(1, 12))
        seg = draw(st.sampled_from(["s:0", "s:1"]))
        out.append(
            cand(
                start,
                end,
                draw(st.sampled_from(TYPES)),
                *draw(st.sampled_from(LAYER_SETS)),
                seg=seg,
                score=draw(st.sampled_from([0.2, 0.45, 0.6])),
            )
        )
    return out


def key(cands: list[Candidate]) -> list[tuple[object, ...]]:
    return [
        (c.segment_id, c.start, c.end, c.entity_type, sorted(e.rule_id for e in c.evidence))
        for c in cands
    ]


@given(candidates())
def test_merge_is_idempotent(cands: list[Candidate]) -> None:
    once = merge(cands)
    assert key(merge(once)) == key(once)


@given(candidates(), st.randoms())
def test_merge_is_order_independent(cands: list[Candidate], rnd) -> None:  # type: ignore[no-untyped-def]
    shuffled = list(cands)
    rnd.shuffle(shuffled)
    assert key(merge(shuffled)) == key(merge(cands))


@given(candidates())
def test_merge_never_drops_a_high_risk_deterministic_span(cands: list[Candidate]) -> None:
    out = merge(cands)
    for c in cands:
        if (
            c.entity_type in (E.US_SSN, E.IN_PAN, E.HOME_ADDRESS)
            and tier_of(c, 0.4) == "DETERMINISTIC"
        ):
            assert any(
                o.segment_id == c.segment_id and o.start <= c.start and c.end <= o.end for o in out
            ), "a HIGH-risk deterministic span lost coverage"


@given(candidates())
def test_merge_output_has_no_conflicting_overlaps(cands: list[Candidate]) -> None:
    out = merge(cands)
    for i, a in enumerate(out):
        for b in out[i + 1 :]:
            if a.overlaps(b):
                assert {a.entity_type, b.entity_type} == {E.PERSON, E.HOME_ADDRESS}
