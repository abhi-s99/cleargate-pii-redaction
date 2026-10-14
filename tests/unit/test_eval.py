"""Evaluation harness units (FR-15, TR-DT-30, TRD section 9). Invented values only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cleargate.core.config import REPO_ROOT, load_policy
from cleargate.core.models import DEFAULT_RISK, EntityType, Evidence, Finding
from eval.calibrate import calibrate, write_threshold
from eval.gold import GoldItem, GoldKeep, GoldSet, from_jsonl, locate
from eval.harness import score_job
from eval.metrics import (
    Prf,
    Scored,
    Span,
    fit_threshold,
    kfold,
    overlap_match,
    percentile,
    routed,
    span_iou,
    strict_match,
    wilson,
)
from tests.unit.detect_support import doc_of, seg


def finding(
    s_id: str,
    start: int,
    end: int,
    value: str,
    etype: EntityType = EntityType.PERSON,
    decision: str = "auto_redact",
    tier: str = "CORROBORATED",
    score: float | None = None,
) -> Finding:
    return Finding(
        finding_id=f"{s_id}:{start}",
        segment_id=s_id,
        start=start,
        end=end,
        entity_type=etype,
        risk=DEFAULT_RISK[etype],
        tier=tier,  # type: ignore[arg-type]
        evidence=[Evidence(detector="t", layer="L3", rule_id="ner.person", raw_score=score)],
        value=value,
        value_hmac="h",
        preview="p",
        decision=decision,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ metrics


def test_wilson_interval_contains_point_and_is_bounded() -> None:
    lo, hi = wilson(9, 10)
    assert 0.0 <= lo < 0.9 < hi <= 1.0
    assert wilson(0, 0) == (0.0, 1.0)
    lo0, hi0 = wilson(0, 62)
    assert lo0 == 0.0
    assert 0.0 < hi0 < 0.1


def test_span_matching_modes() -> None:
    gold = Span("d:0", 4, 17, "PERSON", "Anna Kowalska")
    longer = Span("d:0", 0, 17, "PERSON", "Dr. Anna Kowalska")
    other_type = Span("d:0", 4, 17, "EMAIL_ADDRESS", "Anna Kowalska")
    far = Span("d:0", 30, 40, "PERSON", "Jan Nowaks")
    assert span_iou(gold, longer) == pytest.approx(13 / 17)
    assert overlap_match(gold, longer)
    assert not strict_match(gold, longer)
    assert strict_match(gold, gold)
    assert not overlap_match(gold, other_type)
    assert not overlap_match(gold, far)
    assert span_iou(gold, far) == 0.0
    assert span_iou(gold, Span("d:1", 4, 17, "PERSON", "x")) == 0.0


def test_prf_properties() -> None:
    p = Prf(tp=3, fp=1, found=3, gold=4)
    assert p.precision == 0.75
    assert p.recall == 0.75
    assert p.f1 == pytest.approx(0.75)
    assert Prf().precision is None
    assert Prf().recall is None
    assert Prf().f1 is None


def test_fit_threshold_maximises_recall_under_precision_target() -> None:
    items = [
        Scored("a", 0.9, True),
        Scored("b", 0.8, True),
        Scored("c", 0.6, False),
        Scored("d", 0.5, True),
        Scored("e", 0.3, False),
        Scored("f", 0.2, False),
    ]
    # t=0.5: tp 3, fp 1 -> precision 0.75; t=0.3: precision 0.6; t=0.2: 0.5
    assert fit_threshold(items, 0.75) == 0.5
    assert fit_threshold(items, 0.99) == 0.8
    assert fit_threshold(items, 0.5) == 0.5  # recall already 1.0 at 0.5: the higher wins
    assert fit_threshold([], 0.5) == 0.0


def test_fit_threshold_fails_closed_when_target_unreachable() -> None:
    items = [Scored("a", 0.9, False), Scored("b", 0.4, False)]
    assert fit_threshold(items, 0.5) == 0.4  # redact more, never less


@given(st.lists(st.tuples(st.floats(0, 1), st.booleans()), min_size=1, max_size=40))
def test_fitted_threshold_meets_target_when_possible(raw: list[tuple[float, bool]]) -> None:
    items = [Scored(f"s{i}", s, pos) for i, (s, pos) in enumerate(raw)]
    t = fit_threshold(items, 0.5)
    tp, fp, _ = routed(items, t)
    reachable = any(
        (lambda r: r[0] / (r[0] + r[1]) >= 0.5 if r[0] + r[1] else True)(routed(items, x.score))
        for x in items
    )
    if reachable:
        assert tp + fp == 0 or tp / (tp + fp) >= 0.5
    else:
        assert t == min(x.score for x in items)


def test_kfold_keeps_segments_together_and_covers_everything() -> None:
    items = [Scored(f"s{i % 7}", i / 20, i % 2 == 0) for i in range(20)]
    folds = kfold(items, 5)
    assert len(folds) == 5
    held = [it for _, test in folds for it in test]
    assert sorted(held, key=id) == sorted(items, key=id)
    for train, test in folds:
        assert not {i.segment_id for i in train} & {i.segment_id for i in test}
    assert len(kfold(items[:1], 5)) == 1


def test_percentile_nearest_rank() -> None:
    assert percentile([], 50) is None
    assert percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert percentile([float(i) for i in range(1, 21)], 95) == 19.0


# ------------------------------------------------------------------ calibration


def test_calibration_reports_held_out_folds() -> None:
    items = [Scored(f"s{i}", 0.3 + (i % 5) / 10, i % 5 >= 2) for i in range(25)]
    cal = calibrate(items, target=0.9, k=5)
    assert cal.n == 25
    assert cal.positives == 15
    assert len(cal.folds) == 5
    assert sum(f.positives for f in cal.folds) == 15
    assert cal.threshold == pytest.approx(0.5)
    assert cal.cv_recall == 1.0
    assert cal.cv_precision == 1.0


def test_write_threshold_changes_only_that_line_and_the_hash(tmp_path: Path) -> None:
    src = REPO_ROOT / "config" / "policy.default.yaml"
    policy = tmp_path / "policy.yaml"
    policy.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    before = policy.read_text(encoding="utf-8").splitlines()
    write_threshold(policy, 0.55)
    after = policy.read_text(encoding="utf-8").splitlines()
    changed = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert len(changed) == 1
    assert "review_threshold: 0.55" in changed[0][1]
    assert "#" in changed[0][1]
    assert load_policy(policy).detection.review_threshold == 0.55
    bad = tmp_path / "bad.yaml"
    bad.write_text("policy_name: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="review_threshold"):
        write_threshold(bad, 0.5)


# ------------------------------------------------------------------ gold


def test_locate_is_whitespace_and_case_tolerant_and_fuzzy_only_when_asked() -> None:
    s = seg("Owner: anna   KOWALSKA (risk lead)")
    sp = locate(s, "Anna Kowalska", fuzzy=False)
    assert sp is not None
    assert s.text[sp.start : sp.end] == "anna   KOWALSKA"
    ocr = seg("Owner: Anna Kowa1ska (risk lead)", method="ocr")
    assert locate(ocr, "Anna Kowalska", fuzzy=False) is None
    hit = locate(ocr, "Anna Kowalska", fuzzy=True)
    assert hit is not None
    assert "Kowa1ska" in ocr.text[hit.start : hit.end]
    assert locate(seg("short"), "Anna Kowalska", fuzzy=True) is None


def test_jsonl_gold_resolves_by_segment_hash_and_locator(tmp_path: Path) -> None:
    s0 = seg("Prepared by Jan Brzezinski", idx=0)
    s1 = seg("Platform: Torii", idx=1)
    doc = doc_of(s0, s1)
    sha = lambda t: hashlib.sha256(t.encode()).hexdigest()  # noqa: E731
    lines = [
        {"doc": "t.docx", "locator": {"part": "word/document.xml"}, "text_sha256": sha(s0.text),
         "start": 12, "end": 26, "type": "PERSON"},
        {"doc": "t.docx", "locator": {}, "text_sha256": sha(s1.text), "start": 10, "end": 15,
         "type": "PRODUCT", "keep": True},
        {"doc": "t.docx", "region": "face", "locator": {"page": 2}},
        {"doc": "other.docx", "locator": {}, "text_sha256": "0", "start": 0, "end": 1,
         "type": "PERSON"},
        {"doc": "t.docx", "locator": {}, "text_sha256": "missing", "start": 0, "end": 3,
         "type": "US_SSN"},
    ]  # fmt: skip
    (tmp_path / "t.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n\n")
    gold = from_jsonl({"t.docx": doc}, tmp_path)
    assert [g.value for g in gold.items] == ["Jan Brzezinski", ""]
    assert gold.items[0].spans[0] == Span("d:0", 12, 26, "PERSON", "Jan Brzezinski")
    assert gold.items[1].spans == []  # unresolved gold stays in the denominator
    assert [k.value for k in gold.keeps] == ["Torii"]
    assert [(r.kind, r.locator) for r in gold.regions] == [("face", {"page": 2})]


# ------------------------------------------------------------------ scoring


def test_score_job_counts_tp_fp_copies_leaks_keeps_and_calibration_items() -> None:
    s0 = seg("Contact Jan Brzezinski at jan.b@example.test", idx=0)
    s1 = seg("Again: Jan Brzezinski uses Torii", idx=1)
    s2 = seg("Meeting with Pawel Zielony today", idx=2)
    doc = doc_of(s0, s1, s2)
    gold = GoldSet(
        items=[
            GoldItem("g1", "t.docx", "PERSON", "Jan Brzezinski",
                     spans=[Span("d:0", 8, 22, "PERSON", "Jan Brzezinski")]),
            GoldItem("g2", "t.docx", "EMAIL_ADDRESS", "jan.b@example.test",
                     spans=[Span("d:0", 26, 44, "EMAIL_ADDRESS", "jan.b@example.test")]),
            GoldItem("g3", "t.docx", "PERSON", "Pawel Zielony",
                     spans=[Span("d:2", 13, 26, "PERSON", "Pawel Zielony")]),
        ],
        keeps=[GoldKeep("t.docx", "Torii")],
    )  # fmt: skip
    findings = [
        finding("d:0", 8, 22, "Jan Brzezinski"),
        finding("d:1", 7, 21, "Jan Brzezinski"),  # propagated copy
        finding("d:1", 27, 32, "Torii", decision="review", tier="SINGLE_SIGNAL", score=0.5),
        finding("d:2", 13, 26, "Pawel Zielony", decision="discarded", tier="LOW", score=0.3),
    ]
    hay = "contact [person_1] at jan.b@example.test"
    je = score_job("t.docx", doc, findings, gold, hay, "")
    person, email = je.overlap["PERSON"], je.overlap["EMAIL_ADDRESS"]
    assert (person.gold, person.found, person.tp, person.fp) == (2, 1, 1, 1)  # Torii is FP
    assert (email.gold, email.found, email.tp, email.fp) == (1, 0, 0, 0)
    assert je.copies == 1
    assert je.leaks == {"EMAIL_ADDRESS": 1}
    assert (je.keeps_redacted, je.keeps_total) == (1, 1)
    assert (je.findings, je.review) == (3, 1)
    assert sorted((s.score, s.positive) for s in je.scored) == [(0.3, True), (0.5, False)]
    assert je.units == 1  # a DOCX counts as one timing unit


def test_score_job_digit_leak_needs_six_digits() -> None:
    doc = doc_of(seg("SSN 123-45-6789 and code 12-34", idx=0))
    gold = GoldSet(
        items=[
            GoldItem("a", "t.docx", "US_SSN", "123-45-6789"),
            GoldItem("b", "t.docx", "EMPLOYEE_ID", "12-34"),
        ]
    )
    je = score_job("t.docx", doc, [], gold, "ssn 123 45 6789", "1234567891234")
    assert je.leaks == {"US_SSN": 1}
    assert je.gold_unextracted == 2
