"""L1 deterministic recognizers with validators (TR-DT-10, ADR-04 layer 1).

Each recognizer has a regex, a validator, optional ``context_terms`` and the TRD 4.1 risk.
A match whose validator fails is not emitted by L1 (the label-anchored layer L2 may still
capture it, flagged ``format_invalid``).

* SSN: Presidio's invalidation rules (mismatched delimiters, all-same digit, zero group or
  serial, ``000``/``666`` and sample prefixes). The 9xx area is **not** rejected (ITINs are
  personal data and the sample uses 900-series values). Undelimited 9-digit numbers need a
  context term.
* PAN: ``[A-Z]{3}[PCHFATBLJG][A-Z]\\d{4}[A-Z]``; holder ``P`` is personal, any other holder
  type is a business PAN and is discarded with reason ``business_pan``.
* PESEL: checksum (weights 1,3,7,9,1,3,7,9,1,3) and a valid encoded birth date; the masked
  form ``NNNNNNxxxxx`` only when ``PESEL`` occurs within 3 tokens before it.
* Card: 13-19 digits, Luhn, IIN prefix sanity.
* Email: RFC-lite local part, dotted domain, alphabetic TLD of 2+ characters (``.example``
  is accepted; no network lookup, TR-SEC-01).
* Passport: context-required (``passport`` within 40 characters before).
* Employee IDs: the policy's ``employee_id_patterns``.
"""

from __future__ import annotations

import re
from datetime import date

from cleargate.core.models import EntityType, Segment
from cleargate.detect.base import Candidate, DocContext, candidate, evidence

SSN_RE = re.compile(r"(?<![\d-])(\d{3})([- .]?)(\d{2})\2(\d{4})(?![\d-])")
SSN_INVALID_PREFIXES = ("000", "666", "123456789", "98765432", "078051120")
SSN_CONTEXT = re.compile(r"\b(ssn|ss#|social\s+security|itin)\b", re.I)
PAN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z])(?![A-Za-z0-9])")
PAN_SHAPE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
PESEL_RE = re.compile(r"(?<![\dA-Za-z])(\d{11})(?![\dA-Za-z])")
PESEL_MASKED_RE = re.compile(r"(?<![\dA-Za-z])(\d{6}[xX*]{5})(?![\w*])")
PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
CARD_RE = re.compile(r"(?<![\d-])(\d(?:[ -]?\d){12,18})(?![\d-])")
EMAIL_RE = re.compile(
    r"(?<![\w.+'-])([A-Za-z0-9](?:[A-Za-z0-9._%+'-]{0,62}[A-Za-z0-9_-])?"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24})(?![\w-])"
)
PASSPORT_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{0,2}\d{6,9})(?![A-Za-z0-9])")
PASSPORT_CONTEXT = re.compile(r"\bpassport\b", re.I)


# --------------------------------------------------------------------- validators


def ssn_valid(value: str) -> bool:
    m = SSN_RE.fullmatch(value.strip())
    if not m:
        return False
    digits = m.group(1) + m.group(3) + m.group(4)
    if len(set(digits)) == 1:
        return False
    if m.group(3) == "00" or m.group(4) == "0000":
        return False
    return not digits.startswith(SSN_INVALID_PREFIXES)


def pan_holder(value: str) -> str | None:
    """Holder-type character of a well-formed PAN, else ``None``."""
    v = value.strip().upper()
    return v[3] if PAN_SHAPE.match(v) and v[3] in "PCHFATBLJG" else None


def pesel_valid(value: str) -> bool:
    v = value.strip()
    if not re.fullmatch(r"\d{11}", v):
        return False
    digits = [int(c) for c in v]
    check = (10 - sum(w * d for w, d in zip(PESEL_WEIGHTS, digits, strict=False)) % 10) % 10
    if check != digits[10]:
        return False
    return pesel_birth_date(v) is not None


def pesel_birth_date(value: str) -> date | None:
    yy, mm, dd = int(value[0:2]), int(value[2:4]), int(value[4:6])
    century = {0: 1900, 20: 2000, 40: 2100, 60: 2200, 80: 1800}
    base = (mm // 20) * 20
    if base not in century:
        return None
    try:
        return date(century[base] + yy, mm - base, dd)
    except ValueError:
        return None


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iin_plausible(digits: str) -> bool:
    n = len(digits)
    two, four = int(digits[:2]), int(digits[:4])
    if digits[0] == "4":
        return n in (13, 16, 19)
    if 51 <= two <= 55 or 2221 <= four <= 2720:
        return n == 16
    if two in (34, 37):
        return n == 15
    if digits.startswith(("6011", "65")) or 644 <= int(digits[:3]) <= 649:
        return 16 <= n <= 19
    if 3528 <= four <= 3589:
        return 16 <= n <= 19
    if two in (36, 38) or 300 <= int(digits[:3]) <= 305:
        return n in (14, 16, 19)
    return False


def card_valid(value: str) -> bool:
    digits = re.sub(r"[ -]", "", value)
    return (
        digits.isdigit()
        and 13 <= len(digits) <= 19
        and luhn_valid(digits)
        and iin_plausible(digits)
    )


def email_valid(value: str) -> bool:
    m = EMAIL_RE.fullmatch(value.strip())
    return bool(m) and value.rsplit(".", 1)[-1].isalpha()


def tokens_before(text: str, pos: int, n: int) -> list[str]:
    return re.findall(r"[\w#.]+", text[:pos])[-n:]


# --------------------------------------------------------------------- recognizers


class _L1:
    layer = "L1"
    version = "0.4.0"
    name = "l1"

    def ev(self, rule: str, context: list[str] | None = None):  # type: ignore[no-untyped-def]
        return evidence(self.name, "L1", rule, score=1.0, context=context)


class SsnRecognizer(_L1):
    name = "ssn"

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out = []
        for m in SSN_RE.finditer(seg.text):
            if not ssn_valid(m.group(0)):
                continue
            if not m.group(2) and not SSN_CONTEXT.search(
                seg.text[max(0, m.start() - 40) : m.start()]
            ):
                continue  # undelimited 9 digits need context (Presidio behaviour)
            out.append(
                candidate(seg, m.start(), m.end(), EntityType.US_SSN, self.ev("ssn.presidio_rules"))
            )
        return out


class PanRecognizer(_L1):
    name = "in_pan"

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out = []
        for m in PAN_RE.finditer(seg.text):
            holder = pan_holder(m.group(1))
            out.append(
                candidate(
                    seg,
                    m.start(1),
                    m.end(1),
                    EntityType.IN_PAN,
                    self.ev(f"pan.holder_{holder}"),
                    discard_reason=None if holder == "P" else "business_pan",
                )
            )
        return out


class PeselRecognizer(_L1):
    name = "pl_pesel"

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out = []
        for m in PESEL_RE.finditer(seg.text):
            if pesel_valid(m.group(1)):
                out.append(
                    candidate(
                        seg, m.start(1), m.end(1), EntityType.PL_PESEL, self.ev("pesel.checksum")
                    )
                )
        for m in PESEL_MASKED_RE.finditer(seg.text):
            before = [t.upper() for t in tokens_before(seg.text, m.start(1), 3)]
            if "PESEL" in before and pesel_birth_date(m.group(1)[:6] + "00000") is not None:
                out.append(
                    candidate(
                        seg,
                        m.start(1),
                        m.end(1),
                        EntityType.PL_PESEL,
                        self.ev("pesel.masked", ["PESEL"]),
                    )
                )
        return out


class CardRecognizer(_L1):
    name = "payment_card"

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        return [
            candidate(seg, m.start(1), m.end(1), EntityType.PAYMENT_CARD, self.ev("card.luhn"))
            for m in CARD_RE.finditer(seg.text)
            if card_valid(m.group(1))
        ]


class EmailRecognizer(_L1):
    name = "email"

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        return [
            candidate(
                seg, m.start(1), m.end(1), EntityType.EMAIL_ADDRESS, self.ev("email.rfc_lite")
            )
            for m in EMAIL_RE.finditer(seg.text)
            if email_valid(m.group(1))
        ]


class PassportRecognizer(_L1):
    name = "passport"

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        out = []
        for m in PASSPORT_RE.finditer(seg.text):
            if PASSPORT_CONTEXT.search(seg.text[max(0, m.start() - 40) : m.start()]):
                out.append(
                    candidate(
                        seg,
                        m.start(1),
                        m.end(1),
                        EntityType.PASSPORT,
                        self.ev("passport.context", ["passport"]),
                    )
                )
        return out


class EmployeeIdRecognizer(_L1):
    name = "employee_id"

    def __init__(self, patterns: list[str]) -> None:
        self.patterns = [
            (p, re.compile(rf"(?<![A-Za-z0-9])(?:{p})(?![A-Za-z0-9])")) for p in patterns
        ]

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        return [
            candidate(seg, m.start(), m.end(), EntityType.EMPLOYEE_ID, self.ev(f"pattern:{p}"))
            for p, rx in self.patterns
            for m in rx.finditer(seg.text)
        ]


def l1_recognizers(employee_id_patterns: list[str]) -> list[_L1]:
    return [
        EmailRecognizer(),
        SsnRecognizer(),
        PanRecognizer(),
        PeselRecognizer(),
        CardRecognizer(),
        PassportRecognizer(),
        EmployeeIdRecognizer(employee_id_patterns),
    ]
