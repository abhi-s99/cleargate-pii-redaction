"""Hypothesis properties for the gate (TR-GT-01/02, TRD 8.2, brief Phase 1 exit).

1. Stateful: random sequences of legal moves, illegal moves, forged handles and
   raw SQL updates against a real meta.db never reach VALIDATED_SAFE except via
   PROCESSING -> G7 with a valid, issued handle; history always forms an
   unbroken chain of whitelisted edges ending at the current state.
2. Pure rules: SAFE iff no rule fires; the verdict is the first rule that fires;
   adding any fault never makes the outcome less strict.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from cleargate.core.db import ALLOWED_TRANSITIONS
from cleargate.core.errors import ClearGateError, ErrorCode
from cleargate.core.models import Coverage, Locator, RedactionAction, VerificationReport
from cleargate.core.states import JobState
from cleargate.gate.handle import SafeHandle, verify_against_store
from cleargate.gate.machine import decide, is_allowed, transition
from cleargate.gate.rules import GateInput, evaluate, triggered
from tests.unit.gate_support import GATE_KEY, new_job, open_store

STATES = list(JobState)
SEVERITY = {
    JobState.VALIDATED_SAFE: 0,
    JobState.REVIEW_REQUIRED: 1,
    JobState.BLOCKED: 2,
    JobState.FAILED: 3,
}

# ------------------------------------------------------------------ strategies

reports = st.builds(
    VerificationReport,
    job_id=st.just("job-1"),
    reopen_ok=st.booleans(),
    leak_hits=st.integers(0, 2),
    residual_deterministic=st.integers(0, 2),
    residual_other=st.integers(0, 2),
    uninspected_unmasked=st.integers(0, 2),
    unit_counts_equal=st.booleans(),
    consistency_ok=st.booleans(),
    srs=st.none() | st.floats(0.0, 1.0),
)
locators = st.builds(
    Locator, part=st.sampled_from(["page", "word/media/image1.png"]), page=st.integers(1, 3)
)
actions = st.builds(
    RedactionAction,
    finding_ids=st.just(["f"]),
    locator=locators,
    method=st.just("token_replace"),
    applied=st.booleans(),
)
gate_inputs = st.builds(
    GateInput,
    job_id=st.just("job-1"),
    processing_error=st.none() | st.sampled_from([ErrorCode.OCR_TIMEOUT, ErrorCode.INTERNAL]),
    vault_available=st.booleans(),
    verification=st.none() | reports,
    coverage=st.builds(Coverage, uninspected=st.lists(locators, max_size=2)),
    masked_parts=st.frozensets(locators, max_size=2),
    actions=st.lists(actions, max_size=3).map(tuple),
    open_review_items=st.integers(0, 2),
    masked_regions=st.integers(0, 2),
    unreadable_policy=st.sampled_from(["mask_and_review", "mask_only", "block"]),
)

# Faults that each make at least one rule fire, applied on top of any input.
FAULTS: list[tuple[str, dict[str, Any]]] = [
    ("processing_error", {"processing_error": ErrorCode.INTERNAL}),
    ("vault", {"vault_available": False}),
    ("no_verification", {"verification": None}),
    ("review", {"open_review_items": 1}),
    (
        "unapplied",
        {
            "actions": (
                RedactionAction(finding_ids=["x"], locator=Locator(part="p"), method="pixel_mask"),
            )
        },
    ),
    ("uninspected", {"coverage": Coverage(uninspected=[Locator(part="unmaskable")])}),
]
VER_FAULTS: list[dict[str, Any]] = [
    {"reopen_ok": False},
    {"leak_hits": 1},
    {"residual_deterministic": 1},
    {"residual_other": 1},
    {"uninspected_unmasked": 1},
    {"unit_counts_equal": False},
    {"consistency_ok": False},
    {"srs": 0.1},
    {"srs": None},
]


def with_fault(gi: GateInput, data: st.DataObject) -> GateInput:
    if gi.verification is not None and data.draw(st.booleans()):
        ver = gi.verification.model_copy(update=data.draw(st.sampled_from(VER_FAULTS)))
        return gi.model_copy(update={"verification": ver})
    _, update = data.draw(st.sampled_from(FAULTS))
    return gi.model_copy(update=update)


# ------------------------------------------------------------------ pure properties


@given(gate_inputs)
def test_safe_iff_no_rule_fires(gi: GateInput) -> None:
    verdict = evaluate(gi)
    fired = triggered(gi)
    assert (verdict.state is JobState.VALIDATED_SAFE) == (fired == [])
    assert verdict.rule == (fired[0] if fired else "G7")


@given(gate_inputs, st.data())
def test_adding_a_fault_never_relaxes_the_outcome(gi: GateInput, data: st.DataObject) -> None:
    worse = with_fault(gi, data)
    assert evaluate(worse).state is not JobState.VALIDATED_SAFE
    assert SEVERITY[evaluate(worse).state] >= SEVERITY[evaluate(gi).state]


@given(gate_inputs)
def test_reasons_are_identifier_like(gi: GateInput) -> None:
    verdict = evaluate(gi)
    assert all(" " not in r and len(r) < 64 for r in verdict.reasons)


# ------------------------------------------------------------------ stateful machine


class GateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.dir = Path(tempfile.mkdtemp(prefix="cg-gate-"))
        self.store = open_store(self.dir / "meta.db")
        self.sanitized = self.dir / "sanitized.txt"
        self.sanitized.write_text("[PERSON_1] signed.\n", encoding="utf-8")
        new_job(self.store)
        self.model = JobState.RECEIVED

    def teardown(self) -> None:
        self.store.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    @rule(
        to=st.sampled_from(STATES),
        rule_id=st.sampled_from(["G0", "G1", "G6", "G7", "review", "ingest"]),
    )
    def attempt_transition(self, to: JobState, rule_id: str) -> None:
        # Public transition: whitelist only, and never into SAFE.
        legal = is_allowed(self.model, to) and to is not JobState.VALIDATED_SAFE
        try:
            transition(self.store, "job-1", to, rule=rule_id, reason="prop")
        except ClearGateError:
            assert not legal
            return
        assert legal
        self.model = to

    @rule(to=st.sampled_from(STATES))
    def raw_sql_update(self, to: JobState) -> None:
        try:
            self.store.conn.execute("UPDATE jobs SET state = ? WHERE job_id = 'job-1'", (to.value,))
        except sqlite3.IntegrityError:
            return
        # Only a no-op update (same state) may succeed.
        assert to is self.model

    @rule(gi=gate_inputs)
    def run_decide(self, gi: GateInput) -> None:
        try:
            verdict = decide(self.store, gi, gate_key=GATE_KEY, sanitized_path=self.sanitized)
        except ClearGateError:
            assert self.model is not JobState.PROCESSING
            return
        assert self.model is JobState.PROCESSING
        assert verdict.state is evaluate(gi).state
        self.model = verdict.state

    @invariant()
    def db_matches_model(self) -> None:
        assert self.store.job_state("job-1") is self.model

    @invariant()
    def history_is_an_unbroken_whitelisted_chain(self) -> None:
        current = JobState.RECEIVED
        for row in self.store.history("job-1"):
            src, dst = JobState(row["from_state"]), JobState(row["to_state"])
            assert src is current
            assert (src, dst) in ALLOWED_TRANSITIONS
            if dst is JobState.VALIDATED_SAFE:
                assert src is JobState.PROCESSING
                assert row["rule"] == "G7"
            current = dst
        assert current is self.model

    @invariant()
    def safe_implies_issued_valid_handle(self) -> None:
        stored = self.store.handle_json("job-1")
        if self.model is JobState.VALIDATED_SAFE:
            assert stored is not None
            verify_against_store(self.store, SafeHandle.from_json(stored), GATE_KEY, self.sanitized)
        else:
            assert stored is None


GateMachine.TestCase.settings = settings(max_examples=150, stateful_step_count=25, deadline=None)
test_gate_state_machine = GateMachine.TestCase
