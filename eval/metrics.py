"""Metric definitions from TRD section 9 (FR-15). Pure functions, no I/O, no values kept.

* ``wilson``: 95 % Wilson score interval for a proportion (n is always reported with it).
* ``span_iou`` / ``strict_match`` / ``overlap_match``: span matching on the same segment,
  (a) strict = identical offsets or identical normalised text, (b) overlap = character
  IoU >= 0.5 with the same type.
* ``Prf``: precision / recall / F1 counts per entity type and overall.
* ``fit_threshold``: the review threshold that maximises recall subject to
  precision >= target (TR-DT-30); ``kfold`` splits scored items by segment.
* ``percentile``: nearest-rank p50 / p95 for timings.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

Z95 = 1.959963984540054
OVERLAP_IOU = 0.5


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95 % Wilson interval for k successes out of n (``(0, 1)`` when n is 0)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class Span:
    segment_id: str
    start: int
    end: int
    entity_type: str
    text: str = field(repr=False, compare=False)  # [RAW], memory only


def span_iou(a: Span, b: Span) -> float:
    if a.segment_id != b.segment_id:
        return 0.0
    inter = min(a.end, b.end) - max(a.start, b.start)
    if inter <= 0:
        return 0.0
    union = max(a.end, b.end) - min(a.start, b.start)
    return inter / union


def strict_match(gold: Span, pred: Span) -> bool:
    if gold.segment_id != pred.segment_id or gold.entity_type != pred.entity_type:
        return False
    same_offsets = (gold.start, gold.end) == (pred.start, pred.end)
    return same_offsets or (span_iou(gold, pred) > 0 and norm(gold.text) == norm(pred.text))


def overlap_match(gold: Span, pred: Span) -> bool:
    return gold.entity_type == pred.entity_type and span_iou(gold, pred) >= OVERLAP_IOU


@dataclass
class Prf:
    tp: int = 0  # predictions that match a gold span
    fp: int = 0  # predictions that match nothing
    found: int = 0  # gold items matched by at least one prediction
    gold: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.found / self.gold if self.gold else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)

    def add(self, other: Prf) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.found += other.found
        self.gold += other.gold


@dataclass(frozen=True)
class Scored:
    """A threshold-routed finding: its score, its segment (fold unit) and its gold label."""

    segment_id: str
    score: float
    positive: bool


def routed(items: Iterable[Scored], threshold: float) -> tuple[int, int, int]:
    """(true positives, false positives, positives) when ``score >= threshold`` redacts."""
    tp = fp = pos = 0
    for it in items:
        pos += it.positive
        if it.score >= threshold:
            tp += it.positive
            fp += not it.positive
    return tp, fp, pos


def fit_threshold(items: Sequence[Scored], precision_target: float) -> float:
    """Highest-recall threshold whose precision meets the target (ties: the higher one).

    Candidate thresholds are the observed scores. When no threshold meets the target the
    lowest observed score is returned: fail closed means redacting more, never less.
    """
    scores = sorted({it.score for it in items})
    if not scores:
        return 0.0
    best: tuple[float, float] | None = None  # (recall, threshold)
    for t in scores:
        tp, fp, pos = routed(items, t)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / pos if pos else 1.0
        if precision >= precision_target and (best is None or (recall, t) >= best):
            best = (recall, t)
    return best[1] if best is not None else scores[0]


def kfold(items: Sequence[Scored], k: int) -> list[tuple[list[Scored], list[Scored]]]:
    """k folds by segment (all items of a segment stay together), deterministic order."""
    segments = sorted({it.segment_id for it in items})
    k = max(1, min(k, len(segments)))
    fold_of = {s: i % k for i, s in enumerate(segments)}
    return [
        (
            [it for it in items if fold_of[it.segment_id] != f],
            [it for it in items if fold_of[it.segment_id] == f],
        )
        for f in range(k)
    ]


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def fmt(x: float | None, digits: int = 3) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def fmt_ci(k: int, n: int) -> str:
    if n == 0:
        return "- (n=0)"
    lo, hi = wilson(k, n)
    return f"{k / n:.3f} [{lo:.3f}, {hi:.3f}] (n={n})"
