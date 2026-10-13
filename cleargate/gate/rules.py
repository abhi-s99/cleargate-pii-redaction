"""Gate rules G0..G7 (TRD 8.2): pure functions, evaluated in order, first match wins.

``evaluate(GateInput) -> Verdict``. Each rule returns the list of reason codes
that trigger it (empty = rule does not fire). ``VALIDATED_SAFE`` (G7) is only
reached when every earlier rule returned nothing; a missing verification report
is itself a G0 failure, so "unverified" can never be read as "safe".

Interpretations recorded in ADR-21:
* masked unreadable/photo regions count as open review items under
  ``mask_and_review``, as uncovered parts (G3) under ``block``, and as neither
  under ``mask_only``;
* an uninspected part is acceptable only if its locator is in ``masked_parts``;
* SRS that was not measured is a G6 review item, not a pass.

ADR-24: a check missing from ``VerificationReport.checks_run`` counts as failed (V1 in
G0, V2..V5 in G3, V6 in G6), so a partial verifier can never produce SAFE.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cleargate.core.errors import ErrorCode
from cleargate.core.models import Coverage, Locator, RedactionAction, VerificationReport
from cleargate.core.states import JobState

RuleId = Literal["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]
UnreadablePolicy = Literal["mask_and_review", "mask_only", "block"]


class GateInput(BaseModel):
    """Everything the gate looks at. Counts, flags and locators only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str
    processing_error: ErrorCode | None = None
    vault_available: bool = True
    verification: VerificationReport | None = None
    coverage: Coverage = Field(default_factory=Coverage)
    masked_parts: frozenset[Locator] = frozenset()
    actions: tuple[RedactionAction, ...] = ()
    open_review_items: int = Field(0, ge=0)
    masked_regions: int = Field(0, ge=0)
    unreadable_policy: UnreadablePolicy = "mask_and_review"
    srs_min: float = Field(0.80, ge=0.0, le=1.0)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: JobState
    rule: RuleId
    reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        """Compact, content-free reason string for history and reports."""
        return ",".join(self.reasons) if self.reasons else "all_rules_passed"


def g0_failed(i: GateInput) -> list[str]:
    out: list[str] = []
    if i.processing_error is not None:
        out.append(i.processing_error.value)
    if not i.vault_available:
        out.append(ErrorCode.VAULT_UNAVAILABLE.value)
    if i.verification is None:
        out.append("VERIFICATION_MISSING")
    elif "V1" not in i.verification.checks_run:
        out.append("V1_NOT_RUN")
    elif not i.verification.reopen_ok:
        out.append("V1_REOPEN_FAILED")
    return out


def g1_leak(i: GateInput) -> list[str]:
    v = i.verification
    return [f"V2_LEAK_HITS={v.leak_hits}"] if v and v.leak_hits else []


def g2_residual_deterministic(i: GateInput) -> list[str]:
    v = i.verification
    if v and v.residual_deterministic:
        return [f"V3_RESIDUAL_DETERMINISTIC={v.residual_deterministic}"]
    return []


def g3_coverage(i: GateInput) -> list[str]:
    out: list[str] = []
    unmasked = [loc for loc in i.coverage.uninspected if loc not in i.masked_parts]
    if unmasked:
        out.append(f"UNINSPECTED_PARTS={len(unmasked)}")
    v = i.verification
    if v and v.uninspected_unmasked:
        out.append(f"V4_UNINSPECTED={v.uninspected_unmasked}")
    if v and not v.unit_counts_equal:
        out.append("V4_UNIT_COUNTS_DIFFER")
    if i.masked_regions and i.unreadable_policy == "block":
        out.append(f"MASKED_REGIONS_POLICY_BLOCK={i.masked_regions}")
    if v is not None:
        # A verification check that did not run is an uninspected dimension (ADR-24).
        out.extend(f"{c}_NOT_RUN" for c in ("V2", "V3", "V4", "V5") if c not in v.checks_run)
    return out


def g4_unapplied(i: GateInput) -> list[str]:
    unapplied = sum(1 for a in i.actions if not a.applied)
    return [f"UNAPPLIED_ACTIONS={unapplied}"] if unapplied else []


def g5_consistency(i: GateInput) -> list[str]:
    v = i.verification
    return ["V5_INCONSISTENT"] if v and not v.consistency_ok else []


def g6_review(i: GateInput) -> list[str]:
    out: list[str] = []
    if i.open_review_items:
        out.append(f"OPEN_REVIEW_ITEMS={i.open_review_items}")
    if i.masked_regions and i.unreadable_policy == "mask_and_review":
        out.append(f"MASKED_REGIONS={i.masked_regions}")
    v = i.verification
    if v and v.residual_other:
        out.append(f"V3_RESIDUAL_OTHER={v.residual_other}")
    if v and ("V6" not in v.checks_run or v.srs is None):
        out.append("V6_SRS_NOT_MEASURED")
    elif v and v.srs is not None and v.srs < i.srs_min:
        out.append("V6_SRS_BELOW_MIN")
    return out


RULES: tuple[tuple[RuleId, JobState, Callable[[GateInput], list[str]]], ...] = (
    ("G0", JobState.FAILED, g0_failed),
    ("G1", JobState.BLOCKED, g1_leak),
    ("G2", JobState.BLOCKED, g2_residual_deterministic),
    ("G3", JobState.BLOCKED, g3_coverage),
    ("G4", JobState.BLOCKED, g4_unapplied),
    ("G5", JobState.BLOCKED, g5_consistency),
    ("G6", JobState.REVIEW_REQUIRED, g6_review),
)


def triggered(i: GateInput) -> list[RuleId]:
    """All rules that fire (for reports); ``evaluate`` uses the first."""
    return [rule for rule, _, fn in RULES if fn(i)]


def evaluate(i: GateInput) -> Verdict:
    for rule, state, fn in RULES:
        reasons = fn(i)
        if reasons:
            return Verdict(state=state, rule=rule, reasons=tuple(reasons))
    return Verdict(state=JobState.VALIDATED_SAFE, rule="G7", reasons=())
