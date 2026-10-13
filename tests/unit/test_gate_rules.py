"""Gate rules G0..G7: table-driven, including rule ordering (TRD 8.2, ADR-21)."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from cleargate.core.errors import ErrorCode
from cleargate.core.models import (
    ALL_CHECKS,
    Coverage,
    Locator,
    RedactionAction,
    VerificationReport,
)
from cleargate.core.states import JobState
from cleargate.gate.rules import GateInput, evaluate, triggered

PAGE3 = Locator(part="page", page=3)
UNAPPLIED = RedactionAction(finding_ids=["f1"], locator=PAGE3, method="pixel_mask")
APPLIED = UNAPPLIED.model_copy(update={"applied": True})

# A case = (top-level GateInput overrides, VerificationReport overrides or None to drop it).
Case = tuple[dict[str, Any], dict[str, Any] | None]


def build(top: dict[str, Any], ver: dict[str, Any] | None) -> GateInput:
    base_ver: dict[str, Any] = {
        "job_id": "j",
        "checks_run": ALL_CHECKS,
        "reopen_ok": True,
        "srs": 0.95,
        "crs": 0.9,
    }
    verification = None if ver is None else VerificationReport(**{**base_ver, **ver})
    return GateInput(**{"job_id": "j", "verification": verification, **top})


# name -> (case, expected rule, expected state, expected reason)
SINGLE: dict[str, tuple[Case, str, JobState, str]] = {
    "g0_exception": (
        ({"processing_error": ErrorCode.OCR_TIMEOUT}, {}),
        "G0",
        JobState.FAILED,
        "OCR_TIMEOUT",
    ),
    "g0_vault": (({"vault_available": False}, {}), "G0", JobState.FAILED, "VAULT_UNAVAILABLE"),
    "g0_no_verification": (({}, None), "G0", JobState.FAILED, "VERIFICATION_MISSING"),
    "g0_reopen": (({}, {"reopen_ok": False}), "G0", JobState.FAILED, "V1_REOPEN_FAILED"),
    "g0_v1_not_run": (
        ({}, {"checks_run": ALL_CHECKS - {"V1"}}),
        "G0",
        JobState.FAILED,
        "V1_NOT_RUN",
    ),
    **{
        f"g3_{c.lower()}_not_run": (
            ({}, {"checks_run": ALL_CHECKS - {c}}),
            "G3",
            JobState.BLOCKED,
            f"{c}_NOT_RUN",
        )
        for c in ("V2", "V3", "V4", "V5")
    },
    "g6_v6_not_run": (
        ({}, {"checks_run": ALL_CHECKS - {"V6"}}),
        "G6",
        JobState.REVIEW_REQUIRED,
        "V6_SRS_NOT_MEASURED",
    ),
    "g1_leak": (({}, {"leak_hits": 2}), "G1", JobState.BLOCKED, "V2_LEAK_HITS=2"),
    "g2_residual": (
        ({}, {"residual_deterministic": 1}),
        "G2",
        JobState.BLOCKED,
        "V3_RESIDUAL_DETERMINISTIC=1",
    ),
    "g3_uninspected": (
        ({"coverage": Coverage(uninspected=[PAGE3])}, {}),
        "G3",
        JobState.BLOCKED,
        "UNINSPECTED_PARTS=1",
    ),
    "g3_v4": (({}, {"uninspected_unmasked": 1}), "G3", JobState.BLOCKED, "V4_UNINSPECTED=1"),
    "g3_units": (
        ({}, {"unit_counts_equal": False}),
        "G3",
        JobState.BLOCKED,
        "V4_UNIT_COUNTS_DIFFER",
    ),
    "g3_policy_block": (
        ({"masked_regions": 1, "unreadable_policy": "block"}, {}),
        "G3",
        JobState.BLOCKED,
        "MASKED_REGIONS_POLICY_BLOCK=1",
    ),
    "g4_unapplied": (
        ({"actions": (APPLIED, UNAPPLIED)}, {}),
        "G4",
        JobState.BLOCKED,
        "UNAPPLIED_ACTIONS=1",
    ),
    "g5_consistency": (({}, {"consistency_ok": False}), "G5", JobState.BLOCKED, "V5_INCONSISTENT"),
    "g6_review_items": (
        ({"open_review_items": 3}, {}),
        "G6",
        JobState.REVIEW_REQUIRED,
        "OPEN_REVIEW_ITEMS=3",
    ),
    "g6_masked_regions": (
        ({"masked_regions": 2}, {}),
        "G6",
        JobState.REVIEW_REQUIRED,
        "MASKED_REGIONS=2",
    ),
    "g6_residual_other": (
        ({}, {"residual_other": 1}),
        "G6",
        JobState.REVIEW_REQUIRED,
        "V3_RESIDUAL_OTHER=1",
    ),
    "g6_srs_low": (({}, {"srs": 0.79}), "G6", JobState.REVIEW_REQUIRED, "V6_SRS_BELOW_MIN"),
    "g6_srs_missing": (({}, {"srs": None}), "G6", JobState.REVIEW_REQUIRED, "V6_SRS_NOT_MEASURED"),
}

SAFE_CASES: dict[str, Case] = {
    "clean": ({}, {}),
    "uninspected_but_masked": (
        {"coverage": Coverage(uninspected=[PAGE3]), "masked_parts": frozenset({PAGE3})},
        {},
    ),
    "masked_regions_mask_only": ({"masked_regions": 4, "unreadable_policy": "mask_only"}, {}),
    "srs_exactly_min": ({}, {"srs": 0.80}),
    "all_actions_applied": ({"actions": (APPLIED, APPLIED)}, {}),
    "custom_srs_min": ({"srs_min": 0.5}, {"srs": 0.6}),
}


@pytest.mark.parametrize("name", list(SINGLE))
def test_each_rule_fires_alone(name: str) -> None:
    (top, ver), rule, state, reason = SINGLE[name]
    verdict = evaluate(build(top, ver))
    assert (verdict.rule, verdict.state) == (rule, state)
    assert reason in verdict.reasons


@pytest.mark.parametrize("name", list(SAFE_CASES))
def test_safe_only_when_nothing_fires(name: str) -> None:
    verdict = evaluate(build(*SAFE_CASES[name]))
    assert (verdict.rule, verdict.state, verdict.reasons) == ("G7", JobState.VALIDATED_SAFE, ())
    assert verdict.reason == "all_rules_passed"


def merge(a: Case, b: Case) -> Case:
    top = {**a[0], **b[0]}
    if a[1] is None or b[1] is None:
        return top, None
    return top, {**a[1], **b[1]}


# One representative per rule; combinations must keep these independent of each other.
REPRESENTATIVE = {
    "G0": SINGLE["g0_exception"][0],
    "G1": SINGLE["g1_leak"][0],
    "G2": SINGLE["g2_residual"][0],
    "G3": SINGLE["g3_uninspected"][0],
    "G4": SINGLE["g4_unapplied"][0],
    "G5": SINGLE["g5_consistency"][0],
    "G6": SINGLE["g6_review_items"][0],
}


@pytest.mark.parametrize(
    ("first", "second"), list(itertools.combinations(sorted(REPRESENTATIVE), 2)), ids="+".join
)
def test_rule_ordering_first_match_wins(first: str, second: str) -> None:
    gi = build(*merge(REPRESENTATIVE[first], REPRESENTATIVE[second]))
    assert evaluate(gi).rule == first
    assert triggered(gi) == [first, second]


def test_all_rules_at_once_gives_g0() -> None:
    case: Case = ({}, {})
    for rep in REPRESENTATIVE.values():
        case = merge(case, rep)
    gi = build(*case)
    assert evaluate(gi).state is JobState.FAILED
    assert triggered(gi) == sorted(REPRESENTATIVE)


def test_missing_verification_beats_everything() -> None:
    gi = build({"open_review_items": 1, "actions": (UNAPPLIED,)}, None)
    assert evaluate(gi).rule == "G0"


def test_multiple_reasons_are_all_reported() -> None:
    gi = build({"open_review_items": 1, "masked_regions": 1}, {"residual_other": 2})
    assert evaluate(gi).reasons == (
        "OPEN_REVIEW_ITEMS=1",
        "MASKED_REGIONS=1",
        "V3_RESIDUAL_OTHER=2",
    )
    assert evaluate(gi).reason == "OPEN_REVIEW_ITEMS=1,MASKED_REGIONS=1,V3_RESIDUAL_OTHER=2"


def test_rules_are_pure() -> None:
    gi = build(*SINGLE["g4_unapplied"][0])
    assert evaluate(gi) == evaluate(gi)
    assert gi.actions[1].applied is False


def test_report_defaults_to_no_checks_run() -> None:
    # Fail closed: a verifier that does not declare its checks cannot produce SAFE.
    gi = GateInput(job_id="j", verification=VerificationReport(job_id="j", reopen_ok=True, srs=1.0))
    assert evaluate(gi).rule == "G0"
    assert evaluate(gi).reasons == ("V1_NOT_RUN",)


def test_partial_verifier_blocks_via_g3() -> None:
    # The Phase 2/3 stub verifier runs only V1 and V4.
    ver = VerificationReport(job_id="j", checks_run=frozenset({"V1", "V4"}), reopen_ok=True)
    verdict = evaluate(GateInput(job_id="j", verification=ver))
    assert (verdict.rule, verdict.state) == ("G3", JobState.BLOCKED)
    assert verdict.reasons == ("V2_NOT_RUN", "V3_NOT_RUN", "V5_NOT_RUN")
