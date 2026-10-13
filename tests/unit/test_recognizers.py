"""L1/L2/L4 recognizers (TR-DT-10, TR-DT-11, TR-DT-12, TR-DT-14).

Every recognizer: at least 5 positives, 5 negatives, and OCR-damaged cases. All values are
invented; card numbers are public test numbers.
"""

from __future__ import annotations

import pytest

from cleargate.core.models import EntityType
from cleargate.detect.base import DocContext
from cleargate.detect.recognizers.context import ContextRecognizer
from cleargate.detect.recognizers.deterministic import (
    CardRecognizer,
    EmailRecognizer,
    EmployeeIdRecognizer,
    PanRecognizer,
    PassportRecognizer,
    PeselRecognizer,
    SsnRecognizer,
    pesel_valid,
    ssn_valid,
)
from cleargate.detect.recognizers.label_anchored import LabelAnchoredRecognizer, ocr_fix
from cleargate.detect.recognizers.phone import PhoneRecognizer
from tests.unit.detect_support import doc_of, run, table, values

E = EntityType
EMP_PATTERNS = [r"EMP-\d{5}", r"DIR-\d{4}", r"MER-[A-Z]{2}-\d{4}", r"EMP\.\d{5}"]

# ------------------------------------------------------------------ SSN


@pytest.mark.parametrize(
    "text",
    [
        "900-12-3456",
        "512 34 6789",
        "771-28-0042",
        "SSN 223456781",
        "623.45.0189",
        "Ref 900-55-1212 noted",
    ],
)
def test_ssn_positives(text: str) -> None:
    assert len(run(SsnRecognizer(), text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "000-12-3456",  # zero area
        "666-12-3456",
        "123-45-6789",  # sample number
        "900-00-3456",  # zero group
        "900-12-0000",  # zero serial
        "111-11-1111",  # all same digit
        "900-12 3456",  # mismatched delimiters
        "223456781",  # undelimited without context
        "RSK-2024-118",
        "9OO-l2-3456",  # OCR-damaged: L1 does not guess
    ],
)
def test_ssn_negatives(text: str) -> None:
    assert run(SsnRecognizer(), text) == []


def test_ssn_900_area_is_not_rejected() -> None:
    assert ssn_valid("900-12-3456")
    assert ssn_valid("987-65-4320") is False


# ------------------------------------------------------------------ PAN


@pytest.mark.parametrize(
    "pan", ["ABCPE1234F", "QWEPR5678T", "LMNPA0001Z", "XYZPK4321B", "ZZZPZ9999A"]
)
def test_pan_person_holder_positives(pan: str) -> None:
    assert values(run(PanRecognizer(), f"PAN {pan} on file")) == [pan]


@pytest.mark.parametrize(
    "pan", ["AAACN1234F", "BBBFX1234Y", "CCCHT0001A", "DDDTA4321B", "EEEGQ1111C"]
)
def test_business_pan_is_discarded_with_reason(pan: str) -> None:
    (c,) = run(PanRecognizer(), f"Company PAN {pan}")
    assert c.discard_reason == "business_pan"


@pytest.mark.parametrize(
    "text",
    [
        "ABCDE12345",  # pragma: allowlist secret
        "ABCQE1234F",
        "abcpe1234f",  # pragma: allowlist secret (invented PAN shape, lower case)
        "ABCPE1234",
        "XABCPE1234FX",
        "PAN BCDPF567BK",
    ],
)
def test_pan_negatives(text: str) -> None:
    assert run(PanRecognizer(), text) == []


# ------------------------------------------------------------------ PESEL


@pytest.mark.parametrize("pesel", ["87021412319", "91052304563", "75120199136", "64031500245"])
def test_pesel_checksum_positives(pesel: str) -> None:
    assert values(run(PeselRecognizer(), f"id {pesel}")) == [pesel]


@pytest.mark.parametrize(
    "text",
    [
        "87021412310",
        "02223077885",
        "88132711456",
        "870214123190",
        "PESEL 87021412318",
        "8702141231",
    ],
)
def test_pesel_negatives(text: str) -> None:
    assert run(PeselRecognizer(), text) == []


@pytest.mark.parametrize(
    "text", ["PESEL 870214xxxxx", "PESEL no 910523XXXXX", "pesel: 751201*****"]
)
def test_masked_pesel_needs_label(text: str) -> None:
    assert len(run(PeselRecognizer(), text)) == 1


@pytest.mark.parametrize("text", ["code 870214xxxxx", "870214xxxxx PESEL", "PESEL 871314xxxxx"])
def test_masked_pesel_negatives(text: str) -> None:
    assert run(PeselRecognizer(), text) == []


def test_pesel_validator_checks_date() -> None:
    assert pesel_valid("87021412319")
    assert not pesel_valid("02223077885")


# ------------------------------------------------------------------ card


@pytest.mark.parametrize(
    "card",
    [
        "4539578123467893",
        "5105 1051 0510 5100",
        "378282246310005",
        "6011-1111-1111-1117",
        "4111111111111111",
    ],
)
def test_card_positives(card: str) -> None:
    assert values(run(CardRecognizer(), f"card {card}")) == [card]


@pytest.mark.parametrize(
    "text",
    [
        "4539578123467894",
        "1234567890123456",
        "4111 1111 1111",
        "0000000000000000",
        "9999999999999995",
    ],
)
def test_card_negatives(text: str) -> None:
    assert run(CardRecognizer(), text) == []


# ------------------------------------------------------------------ email


@pytest.mark.parametrize(
    "email",
    [
        "j.arakawa@northwind.example",
        "a.szabo@cadence.example",
        "first.last+tag@sub.domain.org",
        "o'neil@vendor.co.uk",
        "x_y-z@mail.example.com",
    ],
)
def test_email_positives(email: str) -> None:
    assert values(run(EmailRecognizer(), f"mailto:{email};")) == [email]


@pytest.mark.parametrize(
    "text", ["user@localhost", "a@b.c", "name@domain.123", "@example.com", "foo at bar dot com"]
)
def test_email_negatives(text: str) -> None:
    assert run(EmailRecognizer(), text) == []


# ------------------------------------------------------------------ phone (L1)


@pytest.mark.parametrize(
    "text",
    [
        "+44 20 7946 0123",
        "(212) 555-0187",
        "+1 415 555 0132",
        "020 7946 0958",
        "+48 601 555 019",
        "+33 6 12 34 56 78",
    ],
)
def test_phone_positives(text: str) -> None:
    assert len(run(PhoneRecognizer(), f"call {text} now")) == 1


@pytest.mark.parametrize(
    "text",
    ["+1 (555) 0142", "RSK-2024-118", "12345", "900-12-3456", "Invoice 2024/0042", "v6.0 2026"],
)
def test_phone_negatives(text: str) -> None:
    assert run(PhoneRecognizer(), text) == []


# ------------------------------------------------------------------ passport, employee IDs


@pytest.mark.parametrize(
    "text",
    [
        "passport X1234567",
        "Passport No. AB1234567",
        "passport number 123456789",
        "her passport: Z7654321",
        "PASSPORT C0000001",
    ],
)
def test_passport_needs_context(text: str) -> None:
    assert len(run(PassportRecognizer(), text)) == 1


@pytest.mark.parametrize(
    "text", ["X1234567", "ticket X1234567", "order AB1234567", "123456789", "passport office"]
)
def test_passport_negatives(text: str) -> None:
    assert run(PassportRecognizer(), text) == []


@pytest.mark.parametrize(
    "text", ["EMP-48213", "DIR-1234", "MER-AB-1234", "EMP.48213", "owner EMP-00001."]
)
def test_employee_id_positives(text: str) -> None:
    assert len(run(EmployeeIdRecognizer(EMP_PATTERNS), text)) == 1


@pytest.mark.parametrize(
    "text", ["EMP-4821", "XEMP-48213", "DIR-12345", "MER-A1-1234", "GRP-POL-007"]
)
def test_employee_id_negatives(text: str) -> None:
    assert run(EmployeeIdRecognizer(EMP_PATTERNS), text) == []


# ------------------------------------------------------------------ L2 label-anchored


L2 = LabelAnchoredRecognizer()


@pytest.mark.parametrize(
    ("text", "etype", "value", "invalid"),
    [
        ("SSN 900-55-1212", E.US_SSN, "900-55-1212", False),
        ("SSN: 900-55-121, verified", E.US_SSN, "900-55-121", True),  # OCR lost a digit
        ("DOB 14/02/1987)", E.DATE_OF_BIRTH, "14/02/1987", False),
        ("Date of birth: 3 March 1979.", E.DATE_OF_BIRTH, "3 March 1979", False),
        ("PAN ABCPE1234F, DOB", E.IN_PAN, "ABCPE1234F", False),
        ("PAN ABCPE12F4F", E.IN_PAN, "ABCPE12F4F", True),
        ("Passport No. X1234567", E.PASSPORT, "X1234567", False),
        ("TIN 12-3456789", E.TAX_ID, "12-3456789", False),
        ("Mobile: +1 (555) 0142", E.PHONE_NUMBER, "+1 (555) 0142", True),
        ("M +48 6015550 193", E.PHONE_NUMBER, "+48 6015550 193", True),
        ("PESEL 870214xxxxx on file.", E.PL_PESEL, "870214xxxxx", False),
    ],
)
def test_label_anchored_positives(text: str, etype: EntityType, value: str, invalid: bool) -> None:
    hits = [c for c in run(L2, text) if c.entity_type is etype]
    assert [c.value for c in hits] == [value]
    assert hits[0].format_invalid is invalid


@pytest.mark.parametrize(
    "text",
    [
        "pan out the camera 900",
        "SSN policy applies to all staff",
        "Mobile apps are reviewed yearly",
        "the date of birth field is optional",
        "Passport office hours",
        "M. Lindahl approved",
    ],
)
def test_label_anchored_negatives(text: str) -> None:
    assert run(L2, text) == []


def test_company_pan_under_label_is_discarded() -> None:
    (c,) = run(L2, "Company PAN AAACN1234F (business)")
    assert c.discard_reason == "business_pan"


@pytest.mark.parametrize(
    ("text", "etype"),
    [
        ("SSN 9OO-55-1212", E.US_SSN),  # O for 0 twice
        ("PAN BCDPF567BK", E.IN_PAN),  # B for 8 in a digit position
        ("PAN 8CDPF5678K", E.IN_PAN),  # 8 for B in a letter position
        ("PESEL 87O21412319", E.PL_PESEL),
    ],
)
def test_ocr_confusion_repairs_value_on_ocr_segments(text: str, etype: EntityType) -> None:
    (c,) = [c for c in run(L2, text, kind="ocr_line", method="ocr") if c.entity_type is etype]
    assert not c.format_invalid
    assert c.evidence[0].rule_id == "label.ocr_confusion"


def test_ocr_confusion_not_applied_to_native_text() -> None:
    (c,) = run(L2, "PAN BCDPF567BK")
    assert c.format_invalid
    assert c.evidence[0].rule_id != "label.ocr_confusion"


def test_ocr_confusion_limited_to_two_substitutions() -> None:
    assert ocr_fix(E.US_SSN, "9OO-SS-1212") is None
    assert ocr_fix(E.IN_PAN, "BCDPF5BBBK") is None  # three


def test_column_header_applies_to_every_cell() -> None:
    cells = table(
        [["Name", "Mobile"], ["Anika Szabo", "+1 (555) 0142"], ["Mateo Lindahl", "+1 (555) 0157"]]
    )
    ctx = DocContext.build(doc_of(*cells))
    phones = [c for s in cells for c in L2.analyze(s, ctx) if c.entity_type is E.PHONE_NUMBER]
    assert [c.value for c in phones] == ["+1 (555) 0142", "+1 (555) 0157"]
    assert all(c.format_invalid and c.evidence[0].rule_id.startswith("header:") for c in phones)


def test_row_label_applies_to_value_cell() -> None:
    cells = table([["SSN", "900-12-3456"], ["Notes", "none"]])
    ctx = DocContext.build(doc_of(*cells))
    found = [c for s in cells for c in L2.analyze(s, ctx)]
    assert [(c.entity_type, c.value) for c in found] == [(E.US_SSN, "900-12-3456")]


# ------------------------------------------------------------------ L4 partial financial, address

CTX = ContextRecognizer()


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Refund issued to the card ending 4417.", "4417"),
        ("account ending in 0091", "0091"),
        ("the last four digits of the card (5521)", "5521"),
        ("Account no. **** 7781", "7781"),
        ("Card number ending with 3302", "3302"),
    ],
)
def test_partial_financial_positives(text: str, value: str) -> None:
    hits = [c for c in run(CTX, text) if c.entity_type is E.FINANCIAL_PARTIAL]
    assert [c.value for c in hits] == [value]
    assert hits[0].evidence[0].layer == "L2"  # trigger-anchored (ADR-28)


@pytest.mark.parametrize(
    "text",
    [
        "the card ending soon",
        "fiscal year ending 2024",
        "account 4417 closed",
        "page 4417",
        "ending 4417",
    ],
)
def test_partial_financial_negatives(text: str) -> None:
    assert [c for c in run(CTX, text) if c.entity_type is E.FINANCIAL_PARTIAL] == []


@pytest.mark.parametrize(
    "text",
    [
        "her SSN ending 3456 was used",
        "the last four digits of her SSN, 3456",
        "social security number ends in 3456",
    ],
)
def test_ssn_last_four(text: str) -> None:
    hits = [c for c in run(CTX, text) if c.entity_type is E.US_SSN]
    assert [c.value for c in hits] == ["3456"]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        (
            "posted to her home at 42 Larkspur Lane, Springfield, IL 62704.",
            "42 Larkspur Lane, Springfield, IL 62704",
        ),
        ("Home address: 17 Birch Court, Dayton, OH 45402", "17 Birch Court, Dayton, OH 45402"),
        ("sent to your home at 9 Elm St, Austin, TX 73301-1234", "9 Elm St, Austin, TX 73301-1234"),
    ],
)
def test_home_address_with_trigger(text: str, value: str) -> None:
    hits = [c for c in run(CTX, text) if c.entity_type is E.HOME_ADDRESS]
    assert [c.value for c in hits] == [value]


@pytest.mark.parametrize(
    "text",
    [
        "Our office at 100 Main Street, Boston, MA 02110",  # corporate: no trigger, kept
        "Head office: 1 Market Road, Dover, DE 19901",
        "home at last",
        "the home team won 3-1",
    ],
)
def test_corporate_addresses_are_kept(text: str) -> None:
    assert [c for c in run(CTX, text) if c.entity_type is E.HOME_ADDRESS] == []
