"""Context-aware detection (TR-DT-01, 02, 13, 14, 15, 16; FR-05, FR-06).

Synthetic analogues of every spaCy failure recorded in brief section 1, plus allowlist,
registry and propagation behaviour. Uses the real ``en_core_web_lg`` model.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from cleargate.core.config import Settings, load_policy
from cleargate.core.models import Document, EntityType, Finding, Locator, Region
from cleargate.detect.allowlist import Allowlist
from cleargate.detect.base import Candidate, evidence
from cleargate.detect.engine import DetectionEngine
from cleargate.detect.presplit import map_span, normalise_with_map, sub_spans
from cleargate.detect.propagate import Propagator
from cleargate.detect.registry import PersonRegistry, canonical_key
from tests.unit.detect_support import doc_of, seg, table

E = EntityType
KEY = b"k" * 32


@pytest.fixture(scope="module")
def engine() -> DetectionEngine:
    return DetectionEngine(load_policy())


def detect(engine: DetectionEngine, *docs: Document) -> list[list[Finding]]:
    return engine.detect_batch(list(docs), key=KEY)


def spans(
    findings: list[Finding], doc: Document, etype: EntityType = E.PERSON
) -> dict[str, Finding]:
    texts = {s.segment_id: s.text for s in doc.segments}
    return {
        texts[f.segment_id][f.start : f.end]: f
        for f in findings
        if f.entity_type is etype and f.decision in ("auto_redact", "review")
    }


# ------------------------------------------------------------------ presplit (TR-DT-01/02)


def test_presplit_cell_offsets() -> None:
    s = seg("Ottoline Brandt / Cyrus Mbeki / Jun Arakawa", kind="table_cell")
    assert [s.text[a:b] for a, b in sub_spans(s)] == [
        "Ottoline Brandt",
        "Cyrus Mbeki",
        "Jun Arakawa",
    ]
    s2 = seg("Ana Ruiz; Bo Li | Cai Wen\nDev Rao", kind="table_cell")
    assert [s2.text[a:b] for a, b in sub_spans(s2)] == ["Ana Ruiz", "Bo Li", "Cai Wen", "Dev Rao"]


def test_ocr_normalisation_maps_back() -> None:
    lig, dash, quote = chr(0xFB01), chr(0x2013), chr(0x2019)  # ligature, en dash, quote
    text = f"Signed {lig}nal{dash}copy  by{quote}s"
    norm, index = normalise_with_map(text)
    assert norm == "Signed final-copy by's"
    s, e = map_span(index, norm.index("final"), norm.index("final") + 5, len(text))
    assert text[s:e] == f"{lig}nal"


# ------------------------------------------------------------------ spaCy failure analogues


def test_three_names_in_one_cell_give_three_person_findings(engine: DetectionEngine) -> None:
    cells = table(
        [
            ["Workstream", "Users"],
            ["Contract review", "Ottoline Brandt / Cyrus Mbeki / Jun Arakawa"],
        ]
    )
    d = doc_of(*cells)
    found = spans(detect(engine, d)[0], d)
    assert {"Ottoline Brandt", "Cyrus Mbeki", "Jun Arakawa"} <= set(found)


def test_three_names_without_header_still_split(engine: DetectionEngine) -> None:
    d = doc_of(
        seg("Ottoline Brandt / Cyrus Mbeki / Jun Arakawa", kind="table_cell", table=0, row=1, col=0)
    )
    assert {"Ottoline Brandt", "Cyrus Mbeki", "Jun Arakawa"} <= set(spans(detect(engine, d)[0], d))


def test_two_common_word_name_under_created_by_is_corroborated(engine: DetectionEngine) -> None:
    d = doc_of(*table([["Item", "Created by"], ["Policy draft", "Grace Hunter"]]))
    f = spans(detect(engine, d)[0], d)["Grace Hunter"]
    assert f.tier == "CORROBORATED"
    assert f.decision == "auto_redact"


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Approved by Ms Delacroix-Navarro yesterday.", "Delacroix-Navarro"),
        ("Led by Tobiah Wrenfield, the review closed on time.", "Tobiah Wrenfield"),
        ("Signed: Dr Ilse Marchbank", "Ilse Marchbank"),
    ],
)
def test_honorific_led_by_and_label_names_are_caught(
    engine: DetectionEngine, text: str, name: str
) -> None:
    d = doc_of(seg(text))
    found = spans(detect(engine, d)[0], d)
    assert any(name in k for k in found), found.keys()


def test_initial_surname_header_is_linked_to_registered_person(engine: DetectionEngine) -> None:
    directory = table([["Name", "Role"], ["Mateo Lindahl", "Head of TPRM"]], doc_id="a")
    raci = table([["Activity", "M. Lindahl"], ["Approve vendor", "A"]], table_no=1, doc_id="b")
    da, db = doc_of(*directory, doc_id="a"), doc_of(*raci, doc_id="b")
    fa, fb = detect(engine, da, db)
    full, short = spans(fa, da)["Mateo Lindahl"], spans(fb, db)["M. Lindahl"]
    assert short.tier == "CORROBORATED"
    assert short.person_key == full.person_key  # same token across documents (TR-DT-15.5)


def test_products_kept_while_people_in_same_sentence_are_redacted(engine: DetectionEngine) -> None:
    text = (
        "Torii access was granted by Priya Halvorsen; "
        "OneTrust and Ironclad hold the contract Cyrus Mbeki signed."
    )
    d = doc_of(seg(text))
    findings = detect(engine, d)[0]
    redacted = spans(findings, d)
    assert "Priya Halvorsen" in redacted
    assert "Cyrus Mbeki" in redacted
    for product in ("Torii", "OneTrust", "Ironclad"):
        assert not any(product in k for k in redacted), product


def test_incident_ids_are_not_people(engine: DetectionEngine) -> None:
    d = doc_of(seg("Led by Tobiah Wrenfield, the review closed RSK-2024-118 and INC-5531 on time."))
    found = spans(detect(engine, d)[0], d)
    assert not any("INC" in k or "RSK" in k for k in found)


# ------------------------------------------------------------------ allowlist


def ner_only(value: str) -> Candidate:
    return Candidate(
        "s:0",
        0,
        len(value),
        E.PERSON,
        (evidence("ner", "L3", "ner.person", score=0.6),),
        value=value,
    )


def test_allowlist_suppresses_only_ner_only_exact_terms() -> None:
    allow = Allowlist.build(load_policy().allowlist)
    assert allow.suppresses(ner_only("Torii"), PersonRegistry(KEY)) == "Torii"
    assert allow.suppresses(ner_only("torii"), PersonRegistry(KEY)) == "Torii"
    assert allow.suppresses(ner_only("Torii Admin"), PersonRegistry(KEY)) is None
    corroborated = Candidate(
        "s:0",
        0,
        5,
        E.PERSON,
        (evidence("ner", "L3", "ner.person"), evidence("context", "L4", "label:owner")),
        value="Torii",
    )
    assert allow.suppresses(corroborated, PersonRegistry(KEY)) is None


def test_allowlist_never_suppresses_email_or_labelled_values() -> None:
    allow = Allowlist({"cadence": "Cadence"})
    email = Candidate(
        "s:0", 0, 7, E.EMAIL_ADDRESS, (evidence("email", "L1", "email.rfc_lite"),), value="Cadence"
    )
    assert allow.suppresses(email, None) is None


def test_allowlist_term_that_is_a_registered_person_is_redacted() -> None:
    allow = Allowlist({"morgan stone": "Morgan Stone"})
    reg = PersonRegistry(KEY)
    reg.add("Morgan Stone")
    assert allow.suppresses(ner_only("Morgan Stone"), reg) is None
    assert allow.suppresses(ner_only("Morgan Stone"), PersonRegistry(KEY)) == "Morgan Stone"


def test_auto_learned_vendor_org_is_allowlisted(engine: DetectionEngine) -> None:
    from cleargate.detect.ner import OrgSpan

    s = seg("Integration with Brightline Analytics LLP went live.")
    org = OrgSpan(s.segment_id, 17, 42, s.text[17:42])
    allow = Allowlist.build(load_policy().allowlist, [org], {s.segment_id: s})
    assert (
        allow.suppresses(ner_only("Brightline Analytics LLP"), None) == "Brightline Analytics LLP"
    )


# ------------------------------------------------------------------ registry and propagation


def test_canonical_key_and_variants() -> None:
    assert canonical_key("Dr. Priya K. Halvorsen") == "priya halvorsen"
    reg = PersonRegistry(KEY)
    key = reg.add("Priya Halvorsen")
    assert key == "priya halvorsen"
    v = reg.variants(key)
    assert {"Priya Halvorsen", "P. Halvorsen", "Halvorsen, P.", "Ms Halvorsen"} <= set(v)
    assert {"p.halvorsen", "priya.halvorsen", "phalvorsen"} <= set(reg.email_locals(key))
    assert reg.resolve("P. Halvorsen") == key
    assert reg.resolve("Q. Halvorsen") is None


def test_person_key_is_opaque() -> None:
    reg = PersonRegistry(KEY)
    key = reg.add("Priya Halvorsen")
    pk = reg.person_key(key)
    assert pk.startswith("p:")
    assert "halvorsen" not in pk.casefold()


def prop(*names: str) -> Propagator:
    reg = PersonRegistry(KEY)
    for n in names:
        reg.add(n)
    return Propagator(reg)


def test_full_name_match_allows_middle_initials() -> None:
    hits = prop("Robert Thornfield").sweep(seg("Owner: Robert J. Thornfield signed."))
    assert [h.value for h in hits] == ["Robert J. Thornfield"]
    assert hits[0].evidence[0].rule_id == "registry.exact_full"


def test_fuzzy_ocr_match_and_native_exactness() -> None:
    p = prop("Kasimir Ostrowski")
    ocr = p.sweep(seg("Roster entry: Kasimlr Ostrowski", kind="ocr_line", method="ocr"))
    assert [h.evidence[0].rule_id for h in ocr] == ["registry.fuzzy_ocr"]
    assert p.sweep(seg("Roster entry: Kasimlr Ostrowsky")) == []  # native: exact only


def test_surname_only_rules() -> None:
    p = prop("Kasimir Ostrowski", "Grace Hunter")
    hits = p.sweep(seg("Ostrowski approved it; Hunter did not."))
    assert [(h.value, h.evidence[0].rule_id) for h in hits] == [
        ("Ostrowski", "registry.surname_only")
    ]
    assert prop("Ana Lee").sweep(seg("Lee approved")) == []  # under 5 characters
    shared = prop("Ana Kowalska", "Bea Kowalska")
    assert shared.sweep(seg("Kowalska approved")) == []  # not unique in the registry


# ------------------------------------------------------------------ engine behaviour


def test_metadata_person_fields_are_deterministic(engine: DetectionEngine) -> None:
    d = doc_of(
        seg("Benedikt Saarinen", kind="metadata", part="docProps/core.xml", xpath="dc:creator")
    )
    (f,) = detect(engine, d)[0]
    assert (f.entity_type, f.tier, f.decision) == (E.PERSON, "DETERMINISTIC", "auto_redact")


def test_region_findings(engine: DetectionEngine) -> None:
    d = doc_of(seg("Badge register"))
    loc = Locator(part="page", page=1, bbox=(10.0, 10.0, 50.0, 60.0))
    d.regions.append(Region(kind="face", locator=loc, area_ratio=0.01))
    d.regions.append(Region(kind="unreadable", locator=loc, area_ratio=0.2, mean_conf=40.0))
    found = [f for f in detect(engine, d)[0] if f.segment_id.endswith(("region0", "region1"))]
    assert [f.entity_type for f in found] == [E.PHOTO, E.UNREADABLE_IMAGE_REGION]
    assert all(f.locator == loc and f.risk == "HIGH" for f in found)


def test_findings_never_serialise_values(engine: DetectionEngine) -> None:
    d = doc_of(seg("Contact Priya Halvorsen at p.halvorsen@vendor.example, SSN 900-12-3456."))
    for f in detect(engine, d)[0]:
        dumped = f.model_dump_json()
        assert "Halvorsen" not in dumped
        assert "900-12-3456" not in dumped


def test_verify_profile_ignores_cleargate_tokens() -> None:
    eng = DetectionEngine(load_policy(), profile="verify")
    d = doc_of(seg("[PERSON_1] met [PERSON_2] (SSN [SSN], mobile [PHONE_3]) at [HOME_ADDRESS]."))
    assert eng.detect_batch([d], key=KEY)[0] == []


def test_verify_profile_halves_threshold_and_disables_allowlist() -> None:
    policy = load_policy()
    v = DetectionEngine(policy, profile="verify")
    assert v.threshold == pytest.approx(policy.detection.review_threshold / 2)
    d = doc_of(seg("Escalate to Priya Halvorsen."))
    assert spans(v.detect_batch([d], key=KEY)[0], d)


def test_model_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from cleargate.core.errors import ClearGateError, ErrorCode
    from cleargate.detect import lexicon, ner

    monkeypatch.setattr(lexicon, "_NLP", {})
    monkeypatch.setattr(ner, "_ENGINES", {})
    eng = DetectionEngine(
        load_policy().model_copy(
            update={
                "detection": load_policy().detection.model_copy(
                    update={"ner_model": "no_such_model"}
                )
            }
        )
    )
    with pytest.raises(ClearGateError) as err:
        eng.detect_batch([doc_of(seg("Priya Halvorsen"))], key=KEY)
    assert err.value.code is ErrorCode.MODEL_UNAVAILABLE


def test_settings_unused() -> None:
    # keep the import meaningful: engines take the HMAC key from settings in the pipeline
    s = Settings(data_dir="x", vault_key=SecretStr(Fernet.generate_key().decode()))  # type: ignore[arg-type]
    assert s.vault_key is not None


def test_header_row_cells_are_not_values_of_the_first_header(engine: DetectionEngine) -> None:
    """Regression: row labels must not turn a wide table's header row into PERSON values."""
    d = doc_of(
        *table(
            [
                ["Name", "Role", "Email", "Mobile"],
                ["Anika Szabo", "CRO", "a.szabo@x.example", "+1 (555) 0142"],
            ]
        )
    )
    redacted = spans(detect(engine, d)[0], d)
    assert not {"Role", "Email", "Mobile"} & set(redacted)


def test_spacy_model_loaded_once_per_process() -> None:
    """TR-PF-05: NER and the common-word list share one loaded model."""
    from cleargate.detect.lexicon import get_nlp
    from cleargate.detect.ner import analyzer

    _, engine = analyzer()
    assert get_nlp() is get_nlp()
    assert engine.nlp["en"] is get_nlp()
