"""Deterministic generator for the planted-PII fixtures (brief 4.4 and Phase 3).

    python tests/fixtures/make_fixtures.py [OUT_DIR]     (default tests/fixtures/synthetic)

Every value is invented. Each planted item is recorded in ``manifest.json`` with its
type, channel (native / ocr / metadata) and expected locator, so every downstream
phase can assert: extracted at the right place, detected with the right type,
redacted, absent from all outputs, and the gate state.

Files: ``planted.docx``, ``planted.pptx``, ``planted_native.pdf``,
``planted_scanned.pdf`` (image-only pages with a face and an illegible screenshot
region), ``planted.png`` (text plus EXIF author). The face is the public-domain test
photo in ``tests/fixtures/assets`` (see its README).

Rendering uses Pillow's built-in scalable font so rasters are identical across
platforms. Office containers embed timestamps, so determinism is asserted on the
manifest and on extracted content, not on container bytes.
"""

from __future__ import annotations

import io
import json
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pymupdf
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import parse_xml
from docx.shared import Inches
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.util import Inches as PInches
from pptx.util import Pt

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
SEED = 20261013
FIXED_TIME = datetime(2026, 10, 13, 9, 0, 0)


@dataclass
class Item:
    id: str
    file: str
    type: str
    value: str
    channel: str  # native | ocr | metadata
    expect: dict[str, Any] = field(default_factory=dict)
    note: str = ""


ITEMS: list[Item] = []
DECOYS: list[dict[str, str]] = []
REGIONS: list[dict[str, Any]] = []


def plant(file: str, type_: str, value: str, channel: str, note: str = "", **expect: Any) -> str:
    ITEMS.append(
        Item(
            f"{file.replace('.', '_')}-{len([i for i in ITEMS if i.file == file]) + 1:02d}",
            file,
            type_,
            value,
            channel,
            expect,
            note,
        )
    )
    return value


def decoy(file: str, value: str, kind: str) -> str:
    DECOYS.append({"file": file, "value": value, "kind": kind})
    return value


# ------------------------------------------------------------------ helpers


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def text_image(lines: list[str], size: int = 44, width: int = 1600, pad: int = 40) -> Image.Image:
    f = font(size)
    height = pad * 2 + len(lines) * int(size * 1.6)
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((pad, pad + i * int(size * 1.6)), line, fill="black", font=f)
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def face(size: int) -> Image.Image:
    return Image.open(ASSETS / "face_public_domain.png").convert("RGB").resize((size, size))


def pesel(prefix9: str, serial: str = "1") -> str:
    digits = prefix9 + serial
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    check = (10 - sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 10) % 10
    return digits + str(check)


def luhn_complete(prefix: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(prefix)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return prefix + str((10 - total % 10) % 10)


# ------------------------------------------------------------------ DOCX

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
)


def textbox_run(text: str) -> Any:
    """A text box the way Word writes it: DrawingML Choice plus a VML Fallback copy.

    Word refuses a ``wp:anchor`` or ``wps:wsp`` without its required children (position,
    wrapping, frame and shape properties, body properties), so they are all present.
    """
    para = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
    return parse_xml(
        f'<w:r {NS}><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
        '<wp:anchor distT="0" distB="0" distL="114300" distR="114300" simplePos="0" '
        'relativeHeight="251659264" behindDoc="0" locked="0" layoutInCell="1" '
        'allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        '<wp:extent cx="2000000" cy="400000"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:wrapNone/><wp:docPr id="900" name="Text Box 1"/><wp:cNvGraphicFramePr/>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/'
        'wordprocessingShape"><wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr>'
        '<a:xfrm><a:off x="0" y="0"/><a:ext cx="2000000" cy="400000"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></wps:spPr>'
        f"<wps:txbx><w:txbxContent>{para}</w:txbxContent></wps:txbx>"
        '<wps:bodyPr rot="0" vert="horz" wrap="square" anchor="t"/></wps:wsp>'
        "</a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
        '<mc:Fallback><w:pict><v:shape id="TextBox1" type="#_x0000_t202" '
        'style="position:absolute;width:157.5pt;height:31.5pt"><v:textbox>'
        f"<w:txbxContent>{para}</w:txbxContent>"
        "</v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>"
    )


def make_docx(out: Path) -> None:
    f = "planted.docx"
    doc = Document()
    cp = doc.core_properties
    cp.author = plant(
        f,
        "PERSON",
        "Benedikt Saarinen",
        "metadata",
        part="docProps/core.xml",
        key="dc:creator",
        kind="metadata",
    )
    cp.last_modified_by = plant(
        f,
        "PERSON",
        "Halima Oduya",
        "metadata",
        part="docProps/core.xml",
        key="cp:lastModifiedBy",
        kind="metadata",
    )
    cp.title = "Vendor onboarding review"
    cp.created = cp.modified = FIXED_TIME
    cp.revision = 1

    section = doc.sections[0]
    hdr = plant(f, "PERSON", "Lucinda Farrow", "native", kind="header", part_prefix="word/header")
    section.header.paragraphs[0].text = f"Prepared by {hdr}"
    section.footer.paragraphs[0].text = "Internal - Cadence Financial Group"

    doc.add_heading("Vendor Onboarding Review", level=1)
    name = plant(
        f,
        "PERSON",
        "Priya Halvorsen",
        "native",
        kind="paragraph",
        part="word/document.xml",
        note="narrative",
    )
    ssn = plant(f, "US_SSN", "900-12-3456", "native", kind="paragraph", note="900 area")
    passport = plant(f, "PASSPORT", "X1234567", "native", kind="paragraph")
    pan = plant(f, "IN_PAN", "ABCPE1234F", "native", kind="paragraph")
    dob = plant(f, "DATE_OF_BIRTH", "14/02/1987", "native", kind="paragraph")
    addr = plant(
        f, "HOME_ADDRESS", "42 Larkspur Lane, Springfield, IL 62704", "native", kind="paragraph"
    )
    doc.add_paragraph(
        f"On 3 March the analyst {name} (SSN {ssn}, passport {passport}, PAN {pan}, "
        f"DOB {dob}) asked for refunds to be posted to her home at {addr}."
    )
    decoy(f, "RSK-2024-118", "risk_id")
    decoy(f, "INC-5531", "incident_id")
    led = plant(f, "PERSON", "Tobiah Wrenfield", "native", kind="paragraph", note="Led by")
    doc.add_paragraph(f"Led by {led}, the review closed RSK-2024-118 and INC-5531 on time.")
    card = plant(f, "FINANCIAL_PARTIAL", "4417", "native", kind="paragraph", note="ending NNNN")
    masked = plant(f, "PL_PESEL", "870214xxxxx", "native", kind="paragraph", note="masked PESEL")
    doc.add_paragraph(f"Refund issued to the card ending {card}; PESEL {masked} on file.")
    email = plant(f, "EMAIL_ADDRESS", "j.arakawa@northwind.example", "native", kind="list_item")
    doc.add_paragraph(f"Escalate to {email}", style="List Bullet")
    decoy(f, "OneTrust", "product")
    decoy(f, "Torii", "product")
    doc.add_paragraph("Licences are tracked in OneTrust and Torii; Ironclad holds contracts.")

    # Table 0: /-separated names under "Users", two-common-word name under "Created by".
    t0 = doc.add_table(rows=2, cols=3)
    for c, h in enumerate(("Workstream", "Users", "Created by")):
        t0.cell(0, c).text = h
    users = ["Ottoline Brandt", "Cyrus Mbeki", "Jun Arakawa"]
    for u in users:
        plant(
            f,
            "PERSON",
            u,
            "native",
            kind="table_cell",
            table=0,
            row=1,
            col=1,
            note="slash-separated cell",
        )
    t0.cell(1, 0).text = "Contract review"
    t0.cell(1, 1).text = " / ".join(users)
    t0.cell(1, 2).text = plant(
        f,
        "PERSON",
        "Grace Hunter",
        "native",
        kind="table_cell",
        table=0,
        row=1,
        col=2,
        note="two common words, Created by",
    )

    # Table 1: merged cells must be extracted once.
    t1 = doc.add_table(rows=3, cols=3)
    for c, h in enumerate(("Item", "Owner", "Status")):
        t1.cell(0, c).text = h
    h_merge = t1.cell(1, 0).merge(t1.cell(1, 1))
    hon = plant(
        f,
        "PERSON",
        "Delacroix-Navarro",
        "native",
        kind="table_cell",
        table=1,
        row=1,
        col=0,
        note="honorific + hyphenated surname, gridSpan",
        once=True,
    )
    h_merge.text = f"Approved by Ms {hon}"
    v_merge = t1.cell(1, 2).merge(t1.cell(2, 2))
    signer = plant(
        f,
        "PERSON",
        "Ilse Marchbank",
        "native",
        kind="table_cell",
        table=1,
        row=1,
        col=2,
        note="vMerge",
        once=True,
    )
    v_merge.text = f"Signed: Dr {signer}"
    t1.cell(2, 0).text = "Pending"
    t1.cell(2, 1).text = "Legal"

    # Text box (Choice + Fallback copy): extracted once.
    tb = plant(f, "PERSON", "Imelda Strand", "native", kind="textbox", once=True)
    p = doc.add_paragraph("See note: ")
    p._p.append(textbox_run(f"Escalation contact: {tb}"))

    # Tracked deletion and its author, field code with a mailto, external hyperlink rel.
    p = doc.add_paragraph("Contact list updated. ")
    old = plant(f, "PERSON", "Quentin Halloway", "native", kind="paragraph", note="w:delText")
    rev = plant(
        f,
        "PERSON",
        "Rainer Vosk",
        "metadata",
        kind="metadata",
        part="word/document.xml",
        note="w:del/@w:author",
    )
    p._p.append(
        parse_xml(
            f'<w:del {NS} w:id="1" w:author="{rev}" w:date="2026-10-01T00:00:00Z"><w:r>'
            f"<w:delText>Old contact {old}</w:delText></w:r></w:del>"
        )
    )
    mail = plant(
        f,
        "EMAIL_ADDRESS",
        "q.halloway@vendor.example",
        "native",
        kind="paragraph",
        note="w:instrText field code",
    )
    p._p.append(
        parse_xml(f'<w:r {NS}><w:instrText> HYPERLINK "mailto:{mail}" </w:instrText></w:r>')
    )
    ext = plant(
        f,
        "EMAIL_ADDRESS",
        "audit.lead@halloran.example",
        "metadata",
        kind="metadata",
        part="word/_rels/document.xml.rels",
        note="external relationship target",
    )
    doc.part.relate_to(f"mailto:{ext}", RT.HYPERLINK, is_external=True)

    # Screenshot with a name and an email; alt text names the person too.
    approver = plant(
        f,
        "PERSON",
        "Marcus Oyelaran",
        "ocr",
        kind="ocr_line",
        part_prefix="word/media/",
        note="image-only",
    )
    shot_mail = plant(
        f,
        "EMAIL_ADDRESS",
        "m.oyelaran@cadence.example",
        "ocr",
        kind="ocr_line",
        part_prefix="word/media/",
    )
    img = text_image([f"Approver: {approver}", f"Email: {shot_mail}", "Status: approved"])
    pic = doc.add_picture(io.BytesIO(png_bytes(img)), width=Inches(5))
    alt = plant(f, "PERSON", "Marcus Oyelaran", "native", kind="alt_text", note="alt text")
    pic._inline.docPr.set("descr", f"Screenshot showing {alt} approving the vendor")
    doc.add_picture(io.BytesIO(png_bytes(face(256))), width=Inches(1.5))
    REGIONS.append({"file": f, "kind": "face", "part_prefix": "word/media/"})

    comment_author = plant(
        f,
        "PERSON",
        "Wendeline Achterberg",
        "metadata",
        kind="metadata",
        part="word/comments.xml",
        note="comment author attribute",
    )
    para = doc.add_paragraph("Final sign-off pending.")
    doc.add_comment(
        para.runs, text="Please confirm the vendor tier.", author=comment_author, initials="WA"
    )
    doc.save(str(out / f))


# ------------------------------------------------------------------ PPTX


def make_pptx(out: Path) -> None:
    f = "planted.pptx"
    prs = Presentation()
    prs.core_properties.author = plant(
        f,
        "PERSON",
        "Ferdinand Klausen",
        "metadata",
        kind="metadata",
        part="docProps/core.xml",
        key="dc:creator",
    )
    prs.core_properties.created = prs.core_properties.modified = FIXED_TIME
    logo = png_bytes(text_image(["NORTHWIND"], size=60, width=600))
    blank = prs.slide_layouts[5]

    # Slide 1: directory with label-anchored mobiles.
    s1 = prs.slides.add_slide(blank)
    s1.shapes.title.text = "Directory"
    people = [
        ("Anika Szabo", "Group CRO", "a.szabo@cadence.example", "+1 (555) 0142"),
        ("Mateo Lindahl", "Head of TPRM", "m.lindahl@cadence.example", "+1 (555) 0157"),
        ("Yusra Chaudry", "Risk analyst", "y.chaudry@cadence.example", "+48 6015550 193"),
    ]
    tbl = s1.shapes.add_table(
        len(people) + 1, 4, PInches(0.5), PInches(1.5), PInches(9), PInches(2)
    ).table
    for c, h in enumerate(("Name", "Role", "Email", "Mobile")):
        tbl.cell(0, c).text = h
    for r, (n, role, mail, mob) in enumerate(people, 1):
        tbl.cell(r, 0).text = plant(
            f, "PERSON", n, "native", kind="table_cell", slide=1, table=0, row=r, col=0
        )
        tbl.cell(r, 1).text = role
        tbl.cell(r, 2).text = plant(
            f, "EMAIL_ADDRESS", mail, "native", kind="table_cell", slide=1, table=0, row=r, col=2
        )
        tbl.cell(r, 3).text = plant(
            f,
            "PHONE_NUMBER",
            mob,
            "native",
            kind="table_cell",
            slide=1,
            table=0,
            row=r,
            col=3,
            note="non-standard format, Mobile header",
        )
    s1.shapes.add_picture(io.BytesIO(logo), PInches(8), PInches(0.2), height=PInches(0.5))

    # Slide 2: RACI with initial + surname headers.
    s2 = prs.slides.add_slide(blank)
    s2.shapes.title.text = "RACI"
    raci = s2.shapes.add_table(2, 3, PInches(0.5), PInches(1.5), PInches(9), PInches(1)).table
    raci.cell(0, 0).text = "Activity"
    raci.cell(0, 1).text = plant(
        f,
        "PERSON",
        "A. Szabo",
        "native",
        kind="table_cell",
        slide=2,
        table=1,
        row=0,
        col=1,
        note="M. Surname header",
    )
    raci.cell(0, 2).text = plant(
        f,
        "PERSON",
        "M. Lindahl",
        "native",
        kind="table_cell",
        slide=2,
        table=1,
        row=0,
        col=2,
        note="M. Surname header",
    )
    raci.cell(1, 0).text = "Approve vendor"
    raci.cell(1, 1).text = "A"
    raci.cell(1, 2).text = "R"
    s2.shapes.add_picture(io.BytesIO(logo), PInches(8), PInches(0.2), height=PInches(0.5))

    # Slide 3: group shape, notes, picture with text, face photo, alt text.
    s3 = prs.slides.add_slide(blank)
    s3.shapes.title.text = "Committee"
    group = s3.shapes.add_group_shape()
    box = group.shapes.add_textbox(PInches(0.5), PInches(1.5), PInches(5), PInches(0.6))
    chair = plant(
        f,
        "PERSON",
        "Anselm Kittredge",
        "native",
        kind="shape_text",
        slide=3,
        note="inside group shape",
    )
    box.text_frame.text = f"Chair: {chair}"
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(20)
    note = plant(f, "PERSON", "Wilma Castellanos", "native", kind="notes", slide=3)
    s3.notes_slide.notes_text_frame.text = f"Speaker notes: confirm with {note}."
    contact = plant(
        f, "PERSON", "Ines Valderrama", "ocr", kind="ocr_line", slide=3, note="text only in picture"
    )
    pic = s3.shapes.add_picture(
        io.BytesIO(png_bytes(text_image([f"Contact {contact}"]))),
        PInches(0.5),
        PInches(2.5),
        width=PInches(5),
    )
    alt = plant(f, "PERSON", "Ines Valderrama", "native", kind="alt_text", slide=3)
    pic._element.nvPicPr.cNvPr.set("descr", f"Business card of {alt}")
    s3.shapes.add_picture(
        io.BytesIO(png_bytes(face(256))), PInches(6), PInches(2.5), height=PInches(2)
    )
    REGIONS.append({"file": f, "kind": "face", "slide": 3})
    s3.shapes.add_picture(io.BytesIO(logo), PInches(8), PInches(0.2), height=PInches(0.5))
    prs.save(str(out / f))


# ------------------------------------------------------------------ PDFs


def make_native_pdf(out: Path) -> None:
    f = "planted_native.pdf"
    doc = pymupdf.open()
    doc.set_metadata(
        {
            "author": plant(
                f,
                "PERSON",
                "Severine Lund",
                "metadata",
                kind="metadata",
                part="pdf:info",
                key="author",
            ),
            "title": "Badge register",
            "creationDate": "D:20261013090000Z",
            "modDate": "D:20261013090000Z",
        }
    )
    p1 = doc.new_page()
    emp = plant(f, "PERSON", "Corvin Ashdown", "native", kind="paragraph", page=1)
    empid = plant(f, "EMPLOYEE_ID", "EMP-48213", "native", kind="paragraph", page=1)
    mail = plant(
        f, "EMAIL_ADDRESS", "c.ashdown@cadence.example", "native", kind="paragraph", page=1
    )
    phone = plant(f, "PHONE_NUMBER", "+44 20 7946 0123", "native", kind="paragraph", page=1)
    y = 72
    for line in (
        f"Employee: {emp} ({empid})",
        f"Email: {mail}",
        f"Phone: {phone}",
        "Policy reference GRP-POL-007 applies.",
    ):
        p1.insert_text((72, y), line, fontsize=11)
        y += 20
    decoy(f, "GRP-POL-007", "policy_id")
    link_mail = plant(
        f,
        "EMAIL_ADDRESS",
        "badge.office@cadence.example",
        "native",
        kind="paragraph",
        page=1,
        part="page-links",
        note="link URI",
    )
    p1.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(72, 140, 300, 160),
            "uri": f"mailto:{link_mail}",
        }
    )
    annot = p1.add_text_annot((400, 80), "Verify against HR record.")
    reviewer = plant(
        f,
        "PERSON",
        "Ulrich Benn",
        "metadata",
        kind="metadata",
        page=1,
        part="page-annots",
        note="annotation author",
    )
    annot.set_info(title=reviewer)
    annot.update()
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Badge photo register (image below).", fontsize=11)
    holder = plant(
        f,
        "PERSON",
        "Nadia Petrossian",
        "ocr",
        kind="ocr_line",
        page=2,
        part="page-image",
        note="embedded image on a native page",
    )
    p2.insert_image(
        pymupdf.Rect(72, 100, 472, 200), stream=png_bytes(text_image([f"Badge holder {holder}"]))
    )
    doc.save(str(out / f), garbage=3, deflate=True)


def make_scanned_pdf(out: Path) -> None:
    f = "planted_scanned.pdf"
    rng = random.Random(SEED)
    doc = pymupdf.open()
    doc.set_metadata(
        {
            "author": plant(
                f,
                "PERSON",
                "Oriel Vantongeren",
                "metadata",
                kind="metadata",
                part="pdf:info",
                key="author",
            ),
            "creationDate": "D:20261013090000Z",
            "modDate": "D:20261013090000Z",
        }
    )
    w, h = 2550, 3300  # US Letter at 300 DPI

    page1 = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(page1)
    f42 = font(42)
    cust = plant(f, "PERSON", "Fenella Marchetti", "ocr", kind="ocr_line", page=1)
    ssn = plant(f, "US_SSN", "900-55-1212", "ocr", kind="ocr_line", page=1)
    dob = plant(f, "DATE_OF_BIRTH", "03/07/1979", "ocr", kind="ocr_line", page=1)
    for i, line in enumerate(
        (
            f"Customer: {cust}",
            f"SSN {ssn}",
            f"DOB {dob}",
            "Case INC-7720 escalated to the privacy office.",
        )
    ):
        d.text((200, 220 + i * 90), line, fill="black", font=f42)
    decoy(f, "INC-7720", "incident_id")
    page1.paste(face(420), (1900, 200))
    REGIONS.append({"file": f, "kind": "face", "page": 1})
    # An illegible "screenshot": tiny text, upscaled and blurred (cf. Architecture D5).
    shot = Image.new("RGB", (330, 110), (236, 240, 245))
    sd = ImageDraw.Draw(shot)
    for i in range(6):
        sd.text(
            (6, 4 + i * 17),
            f"Record {rng.randint(1000, 9999)} holder Quill Amberley",
            fill=(40, 40, 40),
            font=font(7),
        )
    # 7 px text blown up 6x and blurred: whole-page OCR must not recover it (checked by a test).
    shot = shot.resize((1980, 660), Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(6))
    page1.paste(shot, (200, 900))
    REGIONS.append({"file": f, "kind": "unreadable", "page": 1})
    ITEMS.append(
        Item(
            "planted_scanned-region",
            f,
            "UNREADABLE_IMAGE_REGION",
            "Quill Amberley",
            "image-only",
            {"page": 1},
            "inside the illegible region; must be masked, not read",
        )
    )

    page2 = Image.new("RGB", (w, h), "white")
    d2 = ImageDraw.Draw(page2)
    pan = plant(f, "IN_PAN", "BCDPF5678K", "ocr", kind="ocr_line", page=2)
    pesel_value = plant(f, "PL_PESEL", pesel("870214123"), "ocr", kind="ocr_line", page=2)
    card = plant(
        f, "PAYMENT_CARD", luhn_complete("453957812346789"), "ocr", kind="ocr_line", page=2
    )
    roster = plant(f, "PERSON", "Kasimir Ostrowski", "ocr", kind="ocr_line", page=2)
    for i, line in enumerate(
        (
            f"Roster entry: {roster}",
            f"PAN {pan}",
            f"PESEL {pesel_value}",
            f"Card {card}",
            "Company PAN AAACN1234F (business)",
        )
    ):
        d2.text((200, 220 + i * 90), line, fill="black", font=f42)
    decoy(f, "AAACN1234F", "company_pan")
    for raster in (page1, page2):
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=png_bytes(raster))
    doc.save(str(out / f), garbage=3, deflate=True)


# ------------------------------------------------------------------ image


def make_png(out: Path) -> None:
    f = "planted.png"
    raiser = plant(f, "PERSON", "Oskar Brightwater", "ocr", kind="ocr_line", part="image")
    img = text_image([f"Ticket raised by {raiser}", "Priority: high"])
    exif = Image.Exif()
    exif[0x013B] = plant(
        f,
        "PERSON",
        "Thea Morrow",
        "metadata",
        kind="metadata",
        part="image:exif",
        key="exif:Artist",
    )
    img.save(out / f, format="PNG", exif=exif)


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else HERE / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    ITEMS.clear()
    DECOYS.clear()
    REGIONS.clear()
    for make in (make_docx, make_pptx, make_native_pdf, make_scanned_pdf, make_png):
        make(out)
    manifest = {
        "seed": SEED,
        "generator": "tests/fixtures/make_fixtures.py",
        "items": [asdict(i) for i in ITEMS],
        "decoys": DECOYS,
        "regions": REGIONS,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(
        f"wrote {len(ITEMS)} planted items, {len(DECOYS)} decoys, {len(REGIONS)} regions to {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
