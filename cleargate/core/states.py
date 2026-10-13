"""Job states of the privacy gate (ADR-09, TRD section 8.2).

Only the state names live here. The transition whitelist and its enforcement
belong to ``cleargate.gate.machine`` (TR-GT-01).
"""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    VALIDATED_SAFE = "VALIDATED_SAFE"


TERMINAL_STATES: frozenset[JobState] = frozenset(
    {JobState.FAILED, JobState.BLOCKED, JobState.VALIDATED_SAFE}
)
