"""L2 label-anchored capture (TR-DT-11) with OCR-confusion tolerance (TR-DT-12).

A high-risk label (``SSN``, ``PAN``, ``PESEL``, ``Passport``, ``DOB``, ``Date of birth``,
``TIN``, ``NI``, ``Mobile``, ``M`` before ``+``) captures the value that follows it,
whatever its format, using a small grammar per type (ID token group, phone digits, date).
The same applies to table cells under a column header, or right of a row label, that
matches the lexicon. Captures are DETERMINISTIC; ``format_invalid`` is set when the L1
validator rejects the value (Architecture D4: OCR damage).

OCR segments only: within the label context, up to two confusion substitutions
(``0/O, 1/I/l, 5/S, 7/T, 8/B, 2/Z``) are tried to reach a validator-passing value; on
success the capture is not ``format_invalid`` and carries rule ``label.ocr_confusion``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from cleargate.core.models import EntityType, Segment
from cleargate.detect.base import Candidate, DocContext, candidate, evidence, normalise_text
from cleargate.detect.recognizers.deterministic import (
    pan_holder,
    pesel_birth_date,
    pesel_valid,
    ssn_valid,
)
from cleargate.detect.recognizers.phone import phone_valid

E = EntityType
# (type, pattern, case-sensitive). Short acronyms are case-sensitive to avoid "pan out".
LABELS: list[tuple[EntityType, str, bool]] = [
    (E.US_SSN, r"SSN#?|S\.S\.N\.?|social\s+security(?:\s+(?:number|no\.?|#))?", False),
    (E.IN_PAN, r"PAN(?:\s+(?:no\.?|number|card))?", True),
    (E.PL_PESEL, r"PESEL(?:\s+(?:no\.?|number))?", False),
    (E.PASSPORT, r"passport(?:\s+(?:no\.?|number|#))?", False),
    (E.DATE_OF_BIRTH, r"DOB|D\.O\.B\.?|date\s+of\s+birth|birth\s*date|born(?:\s+on)?", False),
    (E.TAX_ID, r"TIN|NI(?:\s+(?:no\.?|number))?|NINO", True),
    (
        E.TAX_ID,
        r"tax\s+(?:identifier|identification\s+number|id)|national\s+insurance(?:\s+number)?",
        False,
    ),
    (E.PHONE_NUMBER, r"mobile|mob\.?|cell(?:\s+phone)?|phone|tel\.?|telephone", False),
    (E.PHONE_NUMBER, r"M(?=\s*[:.]?\s*\+)", True),
]
_INLINE = [
    (etype, re.compile(rf"(?<![\w]){pat}(?![\w])", 0 if cs else re.I)) for etype, pat, cs in LABELS
]
_FULL = [(etype, re.compile(rf"{pat}", 0 if cs else re.I)) for etype, pat, cs in LABELS]
SEP = re.compile(r"[\s:#=\-.]*(?:(?:no|nr|number|is)\b\.?[\s:#=.]*)?")
MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
DATE_RES = [
    re.compile(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}(?!\d)"),
    re.compile(r"\d{4}-\d{2}-\d{2}(?!\d)"),
    re.compile(rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS})\.?,?\s+\d{{4}}(?!\d)", re.I),
    re.compile(rf"(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}(?!\d)", re.I),
]
PHONE_VALUE = re.compile(r"\+?\(?\d[\d\s().\-]{4,22}\d")
STOP_CHARS = ",;)("
MAX_DIGITS = {E.US_SSN: 9, E.PL_PESEL: 11, E.PASSPORT: 9, E.TAX_ID: 15, E.IN_PAN: 4}
TO_DIGIT = {
    "O": "0",
    "o": "0",
    "D": "0",
    "I": "1",
    "l": "1",
    "|": "1",
    "i": "1",
    "S": "5",
    "s": "5",
    "T": "7",
    "B": "8",
    "Z": "2",
    "z": "2",
}
TO_LETTER = {"0": "O", "1": "I", "5": "S", "7": "T", "8": "B", "2": "Z"}


def _id_value(rest: str, etype: EntityType) -> tuple[int, int] | None:
    """Span of an ID-like token group at the start of ``rest`` (after separators)."""
    tokens = list(re.finditer(r"\S+", rest[:80]))
    if not tokens or tokens[0].start() > 3:
        return None
    end = None
    digits = 0
    for i, tok in enumerate(tokens[:4]):
        text = tok.group(0)
        cut = next((j for j, ch in enumerate(text) if ch in STOP_CHARS), None)
        piece = text[:cut] if cut is not None else text
        piece = piece.rstrip(".:")
        if not piece:
            break
        has_digit = any(c.isdigit() for c in piece)
        if i == 0:
            if not has_digit or len(piece) > 20:
                return None
        elif not re.fullmatch(r"[\dxX*\-]+", piece) or digits >= MAX_DIGITS.get(etype, 15):
            break
        digits += sum(c.isdigit() for c in piece)
        end = tok.start() + len(piece)
        if cut is not None or "\n" in rest[tok.end() : tok.end() + 1]:
            break
    return (tokens[0].start(), end) if end is not None else None


def _phone_value(rest: str) -> tuple[int, int] | None:
    m = PHONE_VALUE.match(rest)
    if not m or "\n" in m.group(0):
        return None
    return (m.start(), m.end())


def _date_value(rest: str) -> tuple[int, int] | None:
    for rx in DATE_RES:
        m = rx.match(rest)
        if m:
            return (m.start(), m.end())
    tok = re.match(r"\S+", rest)
    if tok and sum(c.isdigit() for c in tok.group(0)) >= 4:
        piece = tok.group(0).rstrip(".,;:)")
        return (0, len(piece))
    return None


def parse_date(value: str) -> date | None:
    v = normalise_text(value)
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", v)
    if m:
        a, b, y = (int(x) for x in m.groups())
        y = y + 1900 if y < 100 else y
        for d, mo in ((a, b), (b, a)):
            try:
                return date(y, mo, d)
            except ValueError:
                continue
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        try:
            return date(*(int(x) for x in m.groups()))
        except ValueError:
            return None
    return date(1900, 1, 1) if any(rx.fullmatch(v) for rx in DATE_RES[2:]) else None


def validate(etype: EntityType, value: str) -> tuple[bool, str | None]:
    """``(valid, discard_reason)`` for a captured value."""
    v = value.strip()
    if etype is E.US_SSN:
        compact = re.sub(r"\s", "-", v)
        return ssn_valid(compact) or (re.fullmatch(r"\d{9}", v) is not None and ssn_valid(v)), None
    if etype is E.IN_PAN:
        holder = pan_holder(v)
        if holder is None:
            return False, None
        return True, None if holder == "P" else "business_pan"
    if etype is E.PL_PESEL:
        masked = re.fullmatch(r"\d{6}[xX*]{5}", v) and pesel_birth_date(v[:6] + "00000")
        return bool(pesel_valid(v) or masked), None
    if etype is E.PASSPORT:
        return re.fullmatch(r"[A-Z]{0,2}\d{6,9}", v) is not None, None
    if etype is E.TAX_ID:
        return re.fullmatch(r"[A-Z0-9][A-Z0-9 \-]{4,18}[A-Z0-9]", v.upper()) is not None, None
    if etype is E.DATE_OF_BIRTH:
        return parse_date(v) is not None, None
    if etype is E.PHONE_NUMBER:
        return phone_valid(v), None
    return True, None


def ocr_fix(etype: EntityType, value: str, max_subs: int = 2) -> str | None:
    """Apply up to ``max_subs`` confusion substitutions to reach a valid value."""
    v = value.strip()
    if etype is E.IN_PAN:
        expect = "LLLLLDDDDL"
        if len(v) != 10:
            return None
        fixed, subs = [], 0
        for ch, kind in zip(v.upper(), expect, strict=True):
            if kind == "D" and not ch.isdigit():
                ch, subs = TO_DIGIT.get(ch, ch), subs + 1
            elif kind == "L" and ch.isdigit():
                ch, subs = TO_LETTER.get(ch, ch), subs + 1
            fixed.append(ch)
        cand = "".join(fixed)
        return cand if subs <= max_subs and pan_holder(cand) else None
    if etype in (E.US_SSN, E.PL_PESEL):
        positions = [i for i, ch in enumerate(v) if ch in TO_DIGIT]
        if not positions or len(positions) > max_subs:
            return None
        chars = list(v)
        for i in positions:
            chars[i] = TO_DIGIT[chars[i]]
        cand = "".join(chars)
        return cand if validate(etype, cand)[0] else None
    return None


def _capture(etype: EntityType) -> Callable[[str], tuple[int, int] | None]:
    if etype is E.PHONE_NUMBER:
        return _phone_value
    if etype is E.DATE_OF_BIRTH:
        return _date_value
    return lambda rest: _id_value(rest, etype)


def header_type(text: str) -> EntityType | None:
    t = normalise_text(text).rstrip(":").strip()
    for etype, rx in _FULL:
        if rx.fullmatch(t):
            return etype
    return None


class LabelAnchoredRecognizer:
    name = "label_anchored"
    version = "0.4.0"
    layer = "L2"

    def _emit(
        self, seg: Segment, start: int, end: int, etype: EntityType, rule: str, label: str
    ) -> Candidate | None:
        value = seg.text[start:end].strip()
        if not value:
            return None
        valid, discard = validate(etype, value)
        if not valid and seg.method == "ocr" and ocr_fix(etype, value) is not None:
            ev = evidence(self.name, "L2", "label.ocr_confusion", score=1.0, context=[label])
            return candidate(seg, start, end, etype, ev)
        ev = evidence(self.name, "L2", rule, score=1.0, context=[label])
        return candidate(
            seg, start, end, etype, ev, format_invalid=not valid, discard_reason=discard
        )

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out: list[Candidate] = []
        text = seg.text
        for etype, rx in _INLINE:
            for m in rx.finditer(text):
                sep = SEP.match(text, m.end())
                pos = sep.end() if sep else m.end()
                span = _capture(etype)(text[pos:])
                if span is None:
                    continue
                c = self._emit(
                    seg, pos + span[0], pos + span[1], etype, f"label:{etype.value}", m.group(0)
                )
                if c is not None:
                    out.append(c)
        for source, header in (
            ("header", ctx.column_header.get(seg.segment_id)),
            ("row_label", ctx.row_label.get(seg.segment_id)),
        ):
            htype = header_type(header) if header else None
            if htype is None:
                continue
            stripped = text.strip()
            if not stripped or not any(c.isdigit() for c in stripped):
                continue
            start = text.index(stripped)
            c = self._emit(
                seg, start, start + len(stripped), htype, f"{source}:{htype.value}", header or ""
            )
            if c is not None:
                out.append(c)
        return out
