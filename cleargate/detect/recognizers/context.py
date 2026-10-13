"""L4 context rules (TR-DT-14, ADR-04 layer 4).

* Person field labels (``Name``, ``Users``, ``Created by``, ``Led by``, ``Owner`` ...): a
  name-shaped token group right after the label in the same segment, or every name-shaped
  sub-span of a cell whose column header (or row label) is such a label.
* Honorific + capitalised token(s), hyphen-aware (``Ms Delacroix-Navarro``).
* Initials + surname (``R. J. Thornfield``), accepted in table header cells, on lines that
  carry a person label, or when the surname is already in the person registry; first name +
  middle initial(s) + surname (``Robert J. Thornfield``) everywhere (ADR-28).
* Partial financial identifiers (``card ending 4417``, ``last four digits ... (4417)``) and
  SSN last four with SSN context.
* Home address: trigger phrase (``home address``, ``home at`` ...) followed by the US
  street + state + ZIP grammar. Corporate addresses have no trigger and are kept.

Person candidates carry a pre-calibration ``score`` (ADR-28): lower when every token is a
common English word or there is a single token, so weak single signals fall to ``LOW``.
"""

from __future__ import annotations

import re

from cleargate.core.models import EntityType, Segment
from cleargate.detect.base import Candidate, DocContext, candidate, evidence
from cleargate.detect.lexicon import is_common_word
from cleargate.detect.presplit import sub_spans

E = EntityType
PERSON_LABELS = (
    r"names?|full\s+name|users?|members?|attendees?|created\s+by|owners?|chair(?:person)?|led\s+by|"
    r"attested\s+by|challenged\s+by|authors?|reviewers?|reviewed\s+by|contacts?|"
    r"escalation\s+contact|incident\s+manager|investigating\s+officer|prepared\s+by|"
    r"approved\s+by|approvers?|signed(?:\s+by)?|requested\s+by|raised\s+by|assigned\s+to|"
    r"submitted\s+by|customer|employee|badge\s+holder|account\s+holder|cardholder|"
    r"applicant|director|manager|confirm\s+with|contact\s+person"
)
LABEL_INLINE = re.compile(rf"(?<![\w])(?:{PERSON_LABELS})(?![\w])\s*[:\-]?\s*", re.I)
LABEL_FULL = re.compile(rf"(?:{PERSON_LABELS})\s*:?", re.I)
_WORD = r"[A-Z][a-z\u00e0-\u00ff'\u2019]+"
NAME_TOKEN = rf"(?:[A-Z]\.\s?){{0,2}}{_WORD}(?:-{_WORD})?"
NAME_RE = re.compile(rf"{NAME_TOKEN}(?:\s+{NAME_TOKEN}){{0,3}}")
HONORIFIC_RE = re.compile(
    r"\b(?:Mr|Ms|Mrs|Miss|Mx|Dr|Prof)\.?\s+([A-Z][\w'\u2019-]+(?:\s+[A-Z][\w'\u2019-]+)?)"
)
MIDDLE_INITIAL_RE = re.compile(
    r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?\s+(?:[A-Z]\.\s?){1,2}[A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b"
)
INITIALS_RE = re.compile(r"\b((?:[A-Z]\.\s?){1,2}([A-Z][a-z]+(?:-[A-Z][a-z]+)?))\b")
FINANCIAL_RES = [
    re.compile(
        r"\b(?:card|account|acct\.?|a/c)\s+(?:number\s+|no\.?\s+)?(?:ending|ends)\s+"
        r"(?:in\s+|with\s+)?(\d{4})\b",
        re.I,
    ),
    re.compile(r"\blast\s+(?:four|4)\s+digits[^()]{0,40}\((\d{4})\)", re.I),
    re.compile(r"\b(?:card|account)\s*(?:no\.?|number)?\s*[*xX\u2022.]{4,}[\s-]*(\d{4})\b", re.I),
]
SSN_LAST4_RES = [
    re.compile(
        r"\b(?:SSN|social\s+security(?:\s+number)?)\s+(?:ending|ends)\s+(?:in\s+|with\s+)?(\d{4})\b",
        re.I,
    ),
    re.compile(
        r"\blast\s+(?:four|4)(?:\s+digits)?\s+of\s+(?:the\s+|her\s+|his\s+|their\s+)?"
        r"(?:SSN|social\s+security\s+number)\D{0,20}(\d{4})\b",
        re.I,
    ),
]
ADDRESS_TRIGGER = re.compile(
    r"\b(?:home\s+address|home\s+at|to\s+your\s+home\s+at|resides?\s+at|residing\s+at|"
    r"lives\s+at|living\s+at|residential\s+address)\b[\s:,]*",
    re.I,
)
STREET_RE = re.compile(
    r"\d{1,6}\s+[A-Z][\w\s.'-]*?\b(?:Street|St|Avenue|Ave|Lane|Ln|Court|Ct|Crescent|Road|Rd|"
    r"Drive|Dr|Boulevard|Blvd|Way|Place|Pl|Terrace|Close)\b\.?[^.;\n]{0,60}?\b[A-Z]{2}\s\d{5}(?:-\d{4})?"
)
NOT_NAMES = frozenset(
    {
        "n/a",
        "na",
        "none",
        "tbd",
        "tbc",
        "yes",
        "no",
        "all",
        "team",
        "group",
        "legal",
        "finance",
        "pending",
        "approved",
        "board",
        "committee",
        "vendor",
        "staff",
    }
)


def person_score(name: str) -> float:
    """Pre-calibration score for a context-only PERSON candidate (ADR-28)."""
    tokens = [t for t in re.split(r"[\s.]+", name) if len(t) > 1]
    if not tokens or name.casefold() in NOT_NAMES:
        return 0.0
    common = all(is_common_word(t) for t in tokens)
    if len(tokens) >= 2:
        return 0.35 if common else 0.6
    return 0.2 if common else 0.45


def _names_in(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Name-shaped spans fully inside ``text[start:end]`` that start at ``start``."""
    m = NAME_RE.match(text, start, end)
    return [(m.start(), m.end())] if m else []


class ContextRecognizer:
    name = "context"
    version = "0.5.0"
    layer = "L4"

    def ev(self, rule: str, context: list[str] | None = None, score: float | None = None):  # type: ignore[no-untyped-def]
        return evidence(self.name, "L4", rule, score=score, context=context)

    def anchored(self, rule: str, context: list[str]):  # type: ignore[no-untyped-def]
        # Trigger-anchored grammars are label-anchored captures (ADR-04 L2, ADR-28).
        return evidence(self.name, "L2", rule, score=1.0, context=context)

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out: list[Candidate] = []
        out += self._labels(seg, ctx)
        out += self._honorifics(seg)
        out += self._initials(seg, ctx)
        out += self._middle_initial(seg)
        out += self._financial(seg)
        out += self._address(seg)
        return out

    # -------------------------------------------------------------- persons

    def _labels(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out = []
        text = seg.text
        for m in LABEL_INLINE.finditer(text):
            for s, e in _names_in(text, m.end(), len(text)):
                score = person_score(text[s:e])
                if score:
                    rule = f"label:{m.group(0).strip(' :-').casefold()}"
                    out.append(
                        candidate(
                            seg,
                            s,
                            e,
                            E.PERSON,
                            self.ev(rule, [m.group(0).strip()], score),
                            score=score,
                        )
                    )
        for source, header in (
            ("header", ctx.column_header.get(seg.segment_id)),
            ("row_label", ctx.row_label.get(seg.segment_id)),
        ):
            if not header or not LABEL_FULL.fullmatch(header.strip()):
                continue
            for s, e in sub_spans(seg):
                nm = NAME_RE.fullmatch(text, s, e) or NAME_RE.match(text, s, e)
                if nm is None:
                    continue
                score = person_score(nm.group(0))
                if score:
                    rule = f"{source}:{header.strip(' :').casefold()}"
                    out.append(
                        candidate(
                            seg,
                            nm.start(),
                            nm.end(),
                            E.PERSON,
                            self.ev(rule, [header.strip()], score),
                            score=score,
                        )
                    )
        return out

    def _honorifics(self, seg: Segment) -> list[Candidate]:
        out = []
        for m in HONORIFIC_RE.finditer(seg.text):
            name = m.group(1)
            if name.casefold() in NOT_NAMES:
                continue
            score = max(0.6, person_score(name))
            out.append(
                candidate(
                    seg,
                    m.start(),
                    m.end(),
                    E.PERSON,
                    self.ev("honorific", score=score),
                    score=score,
                )
            )
        return out

    def _initials(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out = []
        role_line = seg.segment_id in ctx.in_table_header or LABEL_INLINE.search(seg.text)
        for m in INITIALS_RE.finditer(seg.text):
            surname = m.group(2)
            known = ctx.registry is not None and ctx.registry.has_surname(surname)
            if not (role_line or known):
                continue
            rule = "initials.registry" if known else "initials.role_line"
            out.append(
                candidate(seg, m.start(1), m.end(1), E.PERSON, self.ev(rule, score=0.6), score=0.6)
            )
        return out

    def _middle_initial(self, seg: Segment) -> list[Candidate]:
        """``First M. Last``: a name grammar NER does not need (ADR-28)."""
        out = []
        for m in MIDDLE_INITIAL_RE.finditer(seg.text):
            first = m.group(1).split()[0]
            if first.casefold() in NOT_NAMES:
                continue
            out.append(
                candidate(
                    seg,
                    m.start(1),
                    m.end(1),
                    E.PERSON,
                    self.ev("name.middle_initial", score=0.6),
                    score=0.6,
                )
            )
        return out

    # -------------------------------------------------------------- numbers, addresses

    def _financial(self, seg: Segment) -> list[Candidate]:
        out = []
        for rx in FINANCIAL_RES:
            for m in rx.finditer(seg.text):
                out.append(
                    candidate(
                        seg,
                        m.start(1),
                        m.end(1),
                        E.FINANCIAL_PARTIAL,
                        self.anchored("financial.ending", [m.group(0)[:12]]),
                    )
                )
        for rx in SSN_LAST4_RES:
            for m in rx.finditer(seg.text):
                out.append(
                    candidate(
                        seg, m.start(1), m.end(1), E.US_SSN, self.anchored("ssn.last4", ["SSN"])
                    )
                )
        return out

    def _address(self, seg: Segment) -> list[Candidate]:
        out = []
        for t in ADDRESS_TRIGGER.finditer(seg.text):
            m = STREET_RE.match(seg.text, t.end())
            if m and m.start() - t.end() <= 10:
                out.append(
                    candidate(
                        seg,
                        m.start(),
                        m.end(),
                        E.HOME_ADDRESS,
                        self.anchored("address.home_trigger", [t.group(0).strip()]),
                    )
                )
        return out
