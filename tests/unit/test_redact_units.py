"""Redaction and verification building blocks (TR-RD-01/02/10/30, V2, V5, V6).

Invented values only.
"""

from __future__ import annotations

import io
import sqlite3
import struct
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken
from lxml import etree
from PIL import Image, ImageDraw
from pydantic import SecretStr

from cleargate.core.errors import ClearGateError, ErrorCode
from cleargate.core.models import (
    Document,
    EntityType,
    FileFormat,
    Finding,
    Locator,
    Segment,
)
from cleargate.extract.textmap import docx_paragraph, generic, replace_spans, text_of
from cleargate.redact.text_renderer import apply_spans, render, span_plan
from cleargate.redact.tokens import TokenService
from cleargate.redact.vault import Vault
from cleargate.redact.writers.image import emf_from_image, encode, span_boxes
from cleargate.verify import coverage, leak, structure

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
E = EntityType


def finding(
    fid: str, seg: str, start: int, end: int, etype: EntityType, value: str, **kw: object
) -> Finding:
    data: dict[str, object] = {
        "finding_id": fid,
        "segment_id": seg,
        "start": start,
        "end": end,
        "entity_type": etype,
        "risk": "MEDIUM",
        "tier": "DETERMINISTIC",
        "evidence": [],
        "value": value,
        "value_hmac": f"h-{value}",
        "preview": "****",
        "decision": "auto_redact",
    }
    data.update(kw)
    return Finding.model_validate(data)


# ------------------------------------------------------------------ run-level edits


def paragraph(*runs: tuple[str, bool]) -> etree._Element:
    xml = "".join(
        f'<w:r>{"<w:rPr><w:b/></w:rPr>" if bold else ""}<w:t xml:space="preserve">{t}</w:t></w:r>'
        for t, bold in runs
    )
    return etree.fromstring(f'<w:p xmlns:w="{W}">{xml}</w:p>')


def test_span_crossing_three_runs_keeps_first_run_formatting() -> None:
    p = paragraph(
        ("Escalate to ", False), ("Pri", True), ("ya Halv", False), ("orsen today", False)
    )
    pieces = docx_paragraph(p)
    text = text_of(pieces)
    start = text.index("Priya")
    assert replace_spans(pieces, [(start, start + len("Priya Halvorsen"), "[PERSON_1]")]) == [True]
    runs = p.findall(f"{{{W}}}r")
    texts = [r.find(f"{{{W}}}t").text for r in runs]
    assert texts == ["Escalate to ", "[PERSON_1]", "", " today"]
    assert runs[1].find(f"{{{W}}}rPr/{{{W}}}b") is not None  # first run's formatting kept


def test_several_spans_in_one_run_and_unmappable_span() -> None:
    p = paragraph(("SSN 900-12-3456 and 900-55-1212", False))
    pieces = docx_paragraph(p)
    flags = replace_spans(pieces, [(4, 15, "[SSN]"), (20, 31, "[SSN]"), (40, 45, "[X]")])
    assert flags == [True, True, False]
    assert text_of(docx_paragraph(p)) == "SSN [SSN] and [SSN]"


def test_generic_pieces_keep_surrounding_whitespace() -> None:
    root = etree.fromstring("<a><b>  Owner: Ana Ruiz  </b><c>x</c></a>")
    pieces = generic(root)
    text = text_of(pieces)
    s = text.index("Ana Ruiz")
    replace_spans(pieces, [(s, s + 8, "[PERSON_1]")])
    assert root.find("b").text == "  Owner: [PERSON_1]  "


# ------------------------------------------------------------------ vault and tokens


def key() -> SecretStr:
    return SecretStr(Fernet.generate_key().decode())


def test_vault_refuses_to_start_without_a_valid_key(tmp_path: Path) -> None:
    for bad in (None, SecretStr("short")):
        with pytest.raises(ClearGateError) as err:
            Vault(tmp_path / "vault.db", bad)
        assert err.value.code is ErrorCode.VAULT_UNAVAILABLE


def test_vault_ciphertext_is_unreadable_without_the_key(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault.db", key())
    TokenService(vault).lookup_or_create("b1", E.PERSON, "h1", "p:1", "Imogen Quarrie")
    vault.close()
    raw = (tmp_path / "vault.db").read_bytes()
    assert b"Imogen" not in raw
    assert b"Quarrie" not in raw
    (ct,) = sqlite3.connect(tmp_path / "vault.db").execute("SELECT value_ct FROM tokens").fetchone()
    with pytest.raises(InvalidToken):  # another key cannot decrypt it
        Fernet(Fernet.generate_key()).decrypt(ct)


def test_tokens_are_batch_scoped_typed_and_consistent(tmp_path: Path) -> None:
    svc = TokenService(Vault(tmp_path / "vault.db", key()))
    a = svc.lookup_or_create("b1", E.PERSON, "h-full", "p:7", "Priya Halvorsen")
    b = svc.lookup_or_create("b1", E.PERSON, "h-short", "p:7", "P. Halvorsen")  # same person
    c = svc.lookup_or_create("b1", E.PERSON, "h-other", "p:8", "Cyrus Mbeki")
    e = svc.lookup_or_create("b1", E.EMAIL_ADDRESS, "h-mail", None, "p.halvorsen@x.example")
    s = svc.lookup_or_create("b1", E.US_SSN, "h-ssn", None, "900-12-3456")
    other_batch = svc.lookup_or_create("b2", E.PERSON, "h-full", "p:7", "Priya Halvorsen")
    assert (a, b, c, e, s) == ("[PERSON_1]", "[PERSON_1]", "[PERSON_2]", "[EMAIL_1]", "[SSN]")
    assert other_batch == "[PERSON_1]"  # numbering starts again in another batch
    assert svc.lookup_or_create("b1", E.PHOTO, "h", None, "") is None  # regions: masks only


def test_token_styles(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault.db", key())
    assert (
        TokenService(vault, "typed").lookup_or_create("b", E.PERSON, "h1", None, "x") == "[PERSON]"
    )
    assert (
        TokenService(vault, "fixed").lookup_or_create("c", E.PERSON, "h1", None, "x")
        == "[REDACTED]"
    )


def test_batch_delete_removes_vault_rows(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault.db", key())
    TokenService(vault).lookup_or_create("b1", E.PERSON, "h1", None, "x")
    vault.delete_batch("b1")
    assert vault.entries("b1") == {}


def test_job_state_is_encrypted(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault.db", key())
    vault.save_state(tmp_path, {"texts": ["Imogen Quarrie"]})
    assert b"Imogen" not in (tmp_path / "state.enc").read_bytes()
    assert vault.load_state(tmp_path) == {"texts": ["Imogen Quarrie"]}


# ------------------------------------------------------------------ renderer


def seg(
    sid: str,
    text: str,
    kind: str = "paragraph",
    order: int = 0,
    heading_level: int | None = None,
    **loc: object,
) -> Segment:
    return Segment(
        segment_id=sid,
        kind=kind,
        text=text,
        order_index=order,  # type: ignore[arg-type]
        heading_level=heading_level,
        locator=Locator(part=str(loc.pop("part", "word/document.xml")), **loc),  # type: ignore[arg-type]
        method="native",
    )


def test_span_plan_outer_span_wins_and_overlaps_union() -> None:
    fs = [
        finding("f1", "s", 0, 40, E.HOME_ADDRESS, "a", token="[HOME_ADDRESS]"),
        finding("f2", "s", 3, 16, E.PERSON, "b", token="[PERSON_1]"),
        finding("f3", "t", 0, 5, E.PERSON, "c", token="[PERSON_2]"),
        finding("f4", "t", 3, 9, E.PERSON, "d", token="[PERSON_3]"),
        finding("f5", "t", 20, 22, E.PERSON, "e", token="[PERSON_4]", decision="discarded"),
    ]
    plan = span_plan(fs)
    assert plan == {"s": [(0, 40, "[HOME_ADDRESS]")], "t": [(0, 9, "[PERSON_2]")]}
    assert apply_spans("Ana Ruiz and Bo", [(0, 8, "[PERSON_1]")]) == "[PERSON_1] and Bo"


def test_render_markers_and_tokens() -> None:
    doc = Document(doc_id="d", filename="x.pdf", sha256="", fmt=FileFormat.PDF, size_bytes=0)
    doc.segments = [
        seg("d:0", "Overview", "heading", 0, part="page", page=1, heading_level=2),
        seg("d:1", "Contact Ana Ruiz now.", "paragraph", 1, part="page", page=1, bbox=(0, 0, 1, 1)),
        seg("d:2", "Name", "table_cell", 2, part="page", page=2, table=0, row=0, col=0),
        seg("d:3", "Ana Ruiz", "table_cell", 3, part="page", page=2, table=0, row=0, col=1),
        seg(
            "d:4",
            "Badge holder Bo Li",
            "ocr_line",
            4,
            part="page-image",
            page=2,
            image_ref="xref:5",
        ),
        seg("d:5", "Ana Ruiz", "metadata", 5, part="pdf:info", xpath="author"),
    ]
    fs = [
        finding("f1", "d:1", 8, 16, E.PERSON, "Ana Ruiz", token="[PERSON_1]"),
        finding("f2", "d:3", 0, 8, E.PERSON, "Ana Ruiz", token="[PERSON_1]"),
        finding("f3", "d:4", 13, 18, E.PERSON, "Bo Li", token="[PERSON_2]"),
        finding(
            "f4",
            "d:region0",
            0,
            0,
            E.PHOTO,
            "",
            locator=Locator(part="page-image", page=2, bbox=(1, 1, 5, 5)),
        ),
    ]
    text = render(doc, fs)
    assert text.splitlines() == [
        "[Page 1]",
        "## Overview",
        "Contact [PERSON_1] now.",
        "[Page 2]",
        "| Name | [PERSON_1] |",
        "[Image: 4 words OCR'd, 1 redactions]",
        "[Image region redacted: photo]",
        "  Badge holder [PERSON_2]",
    ]
    assert "Ana" not in text  # metadata is never rendered


# ------------------------------------------------------------------ rasters


def test_span_boxes_cover_only_the_span_words() -> None:
    s = Segment(
        segment_id="s",
        kind="ocr_line",
        text="Customer: Fenella Marchetti ok",
        order_index=0,
        locator=Locator(part="page", page=1, bbox=(0, 0, 400, 20)),
        method="ocr",
        ocr_word_boxes=[(0, 0, 90, 20), (100, 0, 180, 20), (190, 0, 300, 20), (310, 0, 330, 20)],
    )
    assert span_boxes(s, 10, 27) == [(100, 0, 300, 20)]


def test_encode_keeps_format_and_strips_metadata() -> None:
    img = Image.new("RGB", (40, 20), "white")
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x013B] = "Invented Artist"  # Artist
    img.save(buf, "JPEG", exif=exif)
    out = encode(img, "JPEG", buf.getvalue())
    assert out is not None
    back = Image.open(io.BytesIO(out))
    assert back.format == "JPEG"
    assert not back.getexif()


def test_emf_rebuild_keeps_frame() -> None:
    img = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(img).rectangle((20, 20, 80, 60), fill="black")
    header = struct.pack("<II4i4i", 1, 88, 0, 0, 199, 99, 0, 0, 5291, 2645) + b" EMF" + b"\0" * 44
    emf = emf_from_image(img, header)
    assert emf is not None
    assert emf[40:44] == b" EMF"
    assert struct.unpack_from("<4i", emf, 24) == (0, 0, 5291, 2645)  # rclFrame unchanged


# ------------------------------------------------------------------ V2 leak search


def test_needles_and_boundaries() -> None:
    segs = {"s": seg("s", "card ending 4417 and SSN 900-12-3456")}
    fs = [
        finding("f1", "s", 12, 16, E.FINANCIAL_PARTIAL, "4417"),
        finding("f2", "s", 25, 36, E.US_SSN, "900-12-3456"),
        finding("f3", "x", 0, 5, E.PERSON, "Grace", tier="SINGLE_SIGNAL", decision="review"),
        finding("f4", "x", 0, 15, E.PERSON, "Priya Halvorsen", tier="CORROBORATED"),
    ]
    needles = leak.needles(fs, segs)
    hay = [
        "In 4417 cases the grace period applied.",  # short number without its context word
        "Ref 900123456.",  # SSN digits in another formatting
        "Owner: P. Halvorsen; Grace approved.",  # registry variant, cased one-word value
        "PRIYA HALVORSEN",  # case-folded multi-word value
        "x900-12-34567",  # boundaries
    ]
    hits = leak.leak_hits(needles, hay)
    assert hits == {"US_SSN": 1, "PERSON": 3}
    assert leak.leak_hits(needles, ["card ending 4417"]) == {"FINANCIAL_PARTIAL": 1}


# ------------------------------------------------------------------ V5, V6, V4


def test_consistency_checks() -> None:
    entries = {"[PERSON_1]": {"PERSON"}, "[EMAIL_1]": {"EMAIL_ADDRESS"}, "[SSN]": {"US_SSN"}}
    ok = structure.consistency(
        ["[PERSON_1] wrote to [EMAIL_1] ([SSN]) [REDACTED] [Page 3]"], entries, {}, []
    )
    assert ok
    assert not structure.consistency(["[PERSON_9]"], entries, {}, [])  # not in the vault
    assert not structure.consistency(["[PERS[EMAIL_1]ON_1]"], entries, {}, [])  # nested
    assert not structure.consistency([""], entries, {"p:1": {"[PERSON_1]", "[PERSON_2]"}}, [])


def test_srs_and_crs() -> None:
    src = Document(doc_id="d", filename="x.docx", sha256="", fmt=FileFormat.DOCX, size_bytes=0)
    src.segments = [
        seg("d:0", "Title", "heading", 0, paragraph_index=0, heading_level=1),
        seg("d:1", "Owner Ana Ruiz approved the plan", "paragraph", 1, paragraph_index=1),
    ]
    out = src.model_copy(deep=True)
    assert structure.srs(src, out) == 1.0
    out.segments = out.segments[:1]
    assert structure.srs(src, out) == 0.5
    fs = [finding("f", "d:1", 6, 14, E.PERSON, "Ana Ruiz", token="[PERSON_1]")]
    assert structure.crs(src, fs) == 1.0


def test_mask_effect_codes_tolerated_only_on_masked_rasters() -> None:
    src = Document(doc_id="d", filename="x.pdf", sha256="", fmt=FileFormat.PDF, size_bytes=0)
    out = src.model_copy(deep=True)
    out.coverage.register(Locator(part="page", page=2), inspected=False, code="OCR_UNREADABLE")
    assert coverage.uninspected_unmasked(src, out, [], {"page:2"}) == 0
    assert coverage.uninspected_unmasked(src, out, [], set()) == 1
    out.coverage.register(Locator(part="page", page=3), inspected=False, code="OCR_UNAVAILABLE")
    assert coverage.uninspected_unmasked(src, out, [], {"page:2", "page:3"}) == 1
