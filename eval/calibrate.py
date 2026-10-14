"""Calibrate ``detection.review_threshold`` (TR-DT-30, FR-07).

The threshold routes the score-based findings (``SINGLE_SIGNAL`` vs ``LOW``). It is fitted
to maximise recall subject to precision >= target, with k-fold cross-validation over
segments: each fold's threshold is fitted on the other folds and scored on the held-out
fold, so the reported recall/precision never come from the data the threshold saw.

``calibrate(items)`` is pure. ``write_threshold`` rewrites only the ``review_threshold``
line of the policy file (comments kept); the policy hash changes with it. Writing is
opt-in (``python -m eval.run_eval --write-threshold``) and never automatic.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.metrics import Scored, fit_threshold, kfold, routed

DEFAULT_TARGET = 0.50
DEFAULT_K = 5
LINE = re.compile(r"^(\s*review_threshold:\s*)([0-9.]+)(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class Fold:
    threshold: float
    tp: int
    fp: int
    positives: int


@dataclass(frozen=True)
class Calibration:
    threshold: float  # fitted on all items
    folds: list[Fold]
    n: int
    positives: int
    target: float

    @property
    def cv_recall(self) -> float | None:
        pos = sum(f.positives for f in self.folds)
        return sum(f.tp for f in self.folds) / pos if pos else None

    @property
    def cv_precision(self) -> float | None:
        red = sum(f.tp + f.fp for f in self.folds)
        return sum(f.tp for f in self.folds) / red if red else None


def calibrate(
    items: Sequence[Scored], target: float = DEFAULT_TARGET, k: int = DEFAULT_K
) -> Calibration:
    folds = []
    for train, test in kfold(items, k):
        t = fit_threshold(train, target) if train else fit_threshold(test, target)
        tp, fp, pos = routed(test, t)
        folds.append(Fold(t, tp, fp, pos))
    return Calibration(
        threshold=fit_threshold(items, target),
        folds=folds,
        n=len(items),
        positives=sum(it.positive for it in items),
        target=target,
    )


def write_threshold(policy_path: Path, threshold: float) -> None:
    text = policy_path.read_text(encoding="utf-8")
    new, count = LINE.subn(lambda m: f"{m.group(1)}{threshold:.2f}{m.group(3)}", text, count=1)
    if count != 1:
        raise ValueError("review_threshold line not found in the policy file")
    policy_path.write_text(new, encoding="utf-8", newline="\n")
