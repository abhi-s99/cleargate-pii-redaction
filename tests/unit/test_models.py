"""TRD section 4 models: raw fields never serialise (TR-SEC-02)."""

from __future__ import annotations

import json
import pickle

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cleargate.core.models import (
    DEFAULT_RISK,
    RAW_FIELDS,
    TOKEN_LABEL,
    Coverage,
    Document,
    EntityType,
    Evidence,
    FileFormat,
    Finding,
    Locator,
    RedactionAction,
    Segment,
)

RAW_VALUE = "Zephyrine Quillbrook 900-12-3456"  # invented


def make_segment(text: str = RAW_VALUE, idx: int = 0) -> Segment:
    return Segment(
        segment_id=f"doc1:{idx}",
        kind="table_cell",
        text=text,
        order_index=idx,
        locator=Locator(part="word/document.xml", table=1, row=2, col=3),
        method="native",
    )


def make_finding(value: str = RAW_VALUE) -> Finding:
    return Finding(
        finding_id="f1",
        segment_id="doc1:0",
        start=0,
        end=len(value),
        entity_type=EntityType.PERSON,
        risk="MEDIUM",
        tier="CORROBORATED",
        evidence=[Evidence(detector="ner", layer="L3", rule_id="spacy.PERSON", raw_score=0.85)],
        value=value,
        value_hmac="ab" * 32,
        preview="Ze****ok",
        decision="auto_redact",
        token="[PERSON_1]",
    )


def make_document(*segments: Segment) -> Document:
    return Document(
        doc_id="doc1",
        filename="original.docx",
        sha256="00" * 32,
        fmt=FileFormat.DOCX,
        size_bytes=123,
        units={"paragraphs": 1},
        segments=list(segments),
        coverage=Coverage(parts_total=1, parts_inspected=1),
    )


def all_renderings(model: object) -> list[str]:
    assert hasattr(model, "model_dump")
    return [
        json.dumps(model.model_dump(), default=str),  # type: ignore[attr-defined]
        json.dumps(model.model_dump(mode="json")),  # type: ignore[attr-defined]
        model.model_dump_json(),  # type: ignore[attr-defined]
        repr(model),
        str(model),
    ]


def test_raw_fields_declared_for_every_raw_model() -> None:
    assert {Segment: ("text",), Finding: ("value",)} == RAW_FIELDS
    for model, fields in RAW_FIELDS.items():
        for name in fields:
            info = model.model_fields[name]
            assert info.exclude is True, f"{model.__name__}.{name} must be excluded"
            assert info.repr is False, f"{model.__name__}.{name} must be hidden from repr"


def test_segment_text_never_serialises() -> None:
    seg = make_segment()
    assert seg.text == RAW_VALUE  # usable in memory
    for rendering in all_renderings(seg):
        assert RAW_VALUE not in rendering
        assert "Zephyrine" not in rendering
    assert "text" not in seg.model_dump()


def test_finding_value_never_serialises() -> None:
    finding = make_finding()
    assert finding.value == RAW_VALUE
    for rendering in all_renderings(finding):
        assert "Zephyrine" not in rendering
        assert "3456" not in rendering
    assert "value" not in finding.model_dump()


def test_nested_document_never_serialises_segment_text() -> None:
    doc = make_document(make_segment(), make_segment("Second invented value Q7", 1))
    for rendering in all_renderings(doc):
        assert "Zephyrine" not in rendering
        assert "Second invented value" not in rendering


def test_explicit_include_does_not_leak_raw_field() -> None:
    seg = make_segment()
    assert "text" not in seg.model_dump(include={"text", "segment_id"})
    assert "Zephyrine" not in seg.model_dump_json(include={"text"})


def test_pickle_keeps_raw_field_for_worker_transfer() -> None:
    # Process-pool workers receive segments by pickling, which is in-memory transfer.
    seg = pickle.loads(pickle.dumps(make_segment()))  # noqa: S301
    assert seg.text == RAW_VALUE


@given(st.text(min_size=4, alphabet=st.characters(categories=["L", "N"])))
def test_property_any_text_is_absent_from_dumps(text: str) -> None:
    marker = f"QZX{text}QZX"
    seg = make_segment(marker)
    finding = make_finding(marker)
    for rendering in all_renderings(seg) + all_renderings(finding):
        assert marker not in rendering


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Locator(part="page", nonsense=1)  # type: ignore[call-arg]


def test_locator_is_hashable_and_frozen() -> None:
    loc = Locator(part="page", page=3, bbox=(0.0, 0.0, 10.0, 10.0))
    assert hash(loc) == hash(Locator(part="page", page=3, bbox=(0.0, 0.0, 10.0, 10.0)))
    with pytest.raises(ValidationError):
        loc.page = 4  # type: ignore[misc]


def test_redaction_action_defaults_to_unapplied() -> None:
    action = RedactionAction(
        finding_ids=["f1"], locator=Locator(part="page", page=1), method="pixel_mask"
    )
    assert action.applied is False  # fail-closed default (TR-RD-40)


def test_entity_tables_cover_every_type() -> None:
    assert set(DEFAULT_RISK) == set(EntityType)
    assert set(TOKEN_LABEL) == set(EntityType)
    assert TOKEN_LABEL[EntityType.US_SSN] == "SSN"
    assert DEFAULT_RISK[EntityType.PERSON] == "MEDIUM"
