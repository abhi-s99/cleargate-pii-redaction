"""Shared detection types and helpers (TRD 6, ADR-04).

* ``Candidate``: one detector hit on a segment span, before or after merging. The raw
  ``value`` stays in memory only. Merge consumes and produces candidates, so merge can be
  tested for idempotence (TRD 6.3 point 6).
* ``DocContext``: per-document lookups recognizers share (segments by id, table column
  headers and row labels, the batch person registry).
* ``normalise_value`` / ``value_hmac`` / ``preview``: the only ways a finding value is
  turned into something that may be stored (HMAC) or shown (masked preview, at most 2 + 2
  characters or the last 4 digits, TRD 4).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol

from cleargate.core.models import DEFAULT_RISK, Document, EntityType, Evidence, Layer, Segment

if TYPE_CHECKING:
    from cleargate.detect.registry import PersonRegistry

NUMERIC_TYPES = frozenset(
    {
        EntityType.US_SSN,
        EntityType.PL_PESEL,
        EntityType.PAYMENT_CARD,
        EntityType.PHONE_NUMBER,
        EntityType.FINANCIAL_PARTIAL,
    }
)
ALNUM_TYPES = frozenset({EntityType.IN_PAN, EntityType.PASSPORT, EntityType.TAX_ID})
# Built with chr(): the characters themselves trip linters and the style rule.
DASHES = dict.fromkeys(
    [0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFE58, 0xFE63, 0xFF0D], "-"
)
QUOTES = dict.fromkeys([0x2018, 0x2019, 0x201A, 0x201B, 0x2032], "'") | dict.fromkeys(
    [0x201C, 0x201D, 0x201E, 0x201F, 0x2033], '"'
)
TOKEN_RE = re.compile(r"\[(?:[A-Z][A-Z_]*?)(?:_\d+)?\]")


@dataclass(frozen=True)
class Candidate:
    segment_id: str
    start: int
    end: int
    entity_type: EntityType
    evidence: tuple[Evidence, ...]
    value: str = field(repr=False, compare=False)  # [RAW]
    format_invalid: bool = False
    discard_reason: str | None = None
    person_key: str | None = None
    score: float = 1.0  # pre-calibration score for non-deterministic tiers (ADR-28)

    @property
    def length(self) -> int:
        return self.end - self.start

    def with_evidence(self, extra: tuple[Evidence, ...]) -> Candidate:
        seen = {(e.detector, e.layer, e.rule_id) for e in self.evidence}
        new = tuple(e for e in extra if (e.detector, e.layer, e.rule_id) not in seen)
        return replace(self, evidence=self.evidence + new) if new else self

    def overlaps(self, other: Candidate) -> bool:
        return (
            self.segment_id == other.segment_id
            and self.start < other.end
            and other.start < self.end
        )


def evidence(
    detector: str,
    layer: Layer,
    rule_id: str,
    *,
    score: float | None = None,
    context: list[str] | None = None,
) -> Evidence:
    return Evidence(
        detector=detector,
        layer=layer,
        rule_id=rule_id,
        raw_score=score,
        context_terms=context or [],
    )


def candidate(
    seg: Segment,
    start: int,
    end: int,
    etype: EntityType,
    ev: Evidence,
    *,
    format_invalid: bool = False,
    discard_reason: str | None = None,
    score: float = 1.0,
) -> Candidate:
    # Trim whitespace and trailing punctuation so spans line up across detectors.
    text = seg.text
    while start < end and text[start].isspace():
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in ".,;:"):
        end -= 1
    return Candidate(
        segment_id=seg.segment_id,
        start=start,
        end=end,
        entity_type=etype,
        evidence=(ev,),
        value=text[start:end],
        format_invalid=format_invalid,
        discard_reason=discard_reason,
        score=score,
    )


@dataclass
class DocContext:
    """Lookups shared by recognizers for one document (and its batch)."""

    doc: Document
    segments: dict[str, Segment]
    column_header: dict[str, str]  # segment_id -> header text of its column
    row_label: dict[str, str]  # segment_id -> text of the first cell in its row
    registry: PersonRegistry | None = None
    in_table_header: set[str] = field(default_factory=set)  # segment ids of header cells

    @classmethod
    def build(cls, doc: Document, registry: PersonRegistry | None = None) -> DocContext:
        segs = {s.segment_id: s for s in doc.segments}
        cells: dict[tuple[str, int | None, int], dict[tuple[int, int], Segment]] = {}
        for s in doc.segments:
            loc = s.locator
            if s.kind == "table_cell" and loc.table is not None and loc.row is not None:
                key = (loc.part, loc.slide, loc.table)
                cells.setdefault(key, {})[(loc.row, loc.col or 0)] = s
        header: dict[str, str] = {}
        label: dict[str, str] = {}
        header_ids: set[str] = set()
        for grid in cells.values():
            two_columns = max(c for _, c in grid) == 1
            for (r, c), s in grid.items():
                first = grid.get((r, 0))
                if c > 0 and first is not None and (r > 0 or two_columns):
                    # Row 0 of a wider table is the header row, not a label/value pair.
                    label[s.segment_id] = first.text
                if r == 0:
                    header_ids.add(s.segment_id)
                    continue
                top = grid.get((0, c))
                if top is not None:
                    header[s.segment_id] = top.text
        return cls(doc, segs, header, label, registry, header_ids)


class Recognizer(Protocol):
    name: str
    version: str
    layer: Layer

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]: ...


# --------------------------------------------------------------------- value helpers


def normalise_text(text: str) -> str:
    """NFKC, ligatures, unified dashes and quotes, collapsed whitespace (TR-DT-02)."""
    t = unicodedata.normalize("NFKC", text).translate(DASHES).translate(QUOTES)
    return re.sub(r"\s+", " ", t).strip()


def normalise_value(value: str, etype: EntityType) -> str:
    t = normalise_text(value)
    if etype in NUMERIC_TYPES:
        digits = re.sub(r"\D", "", t)
        if etype is EntityType.PHONE_NUMBER and t.lstrip().startswith("+"):
            return "+" + digits
        return digits or t.casefold()
    if etype in ALNUM_TYPES:
        return re.sub(r"[^0-9A-Za-z]", "", t).upper()
    return t.casefold()


def value_hmac(key: bytes, value: str, etype: EntityType) -> str:
    # Name and email values share a normal form, so PERSON and EMAIL owners can be linked.
    return hmac.new(key, normalise_value(value, etype).encode(), hashlib.sha256).hexdigest()


def preview(value: str, etype: EntityType) -> str:
    """Masked preview: last 4 digits for long numbers, else at most 2 + 2 characters."""
    v = normalise_text(value)
    digits = re.sub(r"\D", "", v)
    if etype in NUMERIC_TYPES or (etype in ALNUM_TYPES and len(digits) >= 6):
        if len(digits) >= 8:
            masked = re.sub(r"\d", "*", v[: len(v) - 4]) + v[-4:]
            return re.sub(r"[A-Za-z]", "*", masked[:-4]) + masked[-4:]
        return "*" * max(4, len(v))
    if len(v) >= 10:
        return v[:2] + "****" + v[-2:]
    if len(v) >= 5:
        return v[:1] + "****" + v[-1:]
    return "****"


def default_risk(etype: EntityType) -> str:
    return DEFAULT_RISK[etype]


def overlaps_token(text: str, start: int, end: int) -> bool:
    """True if [start, end) touches a ClearGate token (verification profile)."""
    return any(m.start() < end and start < m.end() for m in TOKEN_RE.finditer(text))
