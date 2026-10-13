"""Load the planted-PII manifest and match items against an extracted Document.

Shared by every phase's round-trip tests (brief 4.4). Matching rules:

* the segment must satisfy every locator expectation in ``expect`` (``kind``, ``part``,
  ``part_prefix``, ``key`` = locator xpath, and any Locator field such as ``page``,
  ``slide``, ``table``, ``row``, ``col``);
* native and metadata values must appear verbatim (whitespace-normalised, case-folded);
* OCR values may differ slightly: ``rapidfuzz.fuzz.partial_ratio >= 90`` against a
  segment at least as long as the value.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from cleargate.core.models import Document, Segment

SYNTHETIC = Path(__file__).resolve().parent / "synthetic"
LOCATOR_FIELDS = ("page", "slide", "table", "row", "col", "shape_id", "image_ref")
OCR_MIN_RATIO = 90


@dataclass(frozen=True)
class Planted:
    id: str
    file: str
    type: str
    value: str
    channel: str
    expect: dict[str, Any]
    note: str


def load_manifest(root: Path = SYNTHETIC) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return data


def planted_items(root: Path = SYNTHETIC) -> list[Planted]:
    return [Planted(**item) for item in load_manifest(root)["items"]]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def locator_ok(seg: Segment, expect: dict[str, Any]) -> bool:
    loc = seg.locator
    if "kind" in expect and seg.kind != expect["kind"]:
        return False
    if "part" in expect and loc.part != expect["part"]:
        return False
    if "part_prefix" in expect and not loc.part.startswith(expect["part_prefix"]):
        return False
    if "key" in expect and loc.xpath != expect["key"]:
        return False
    return all(getattr(loc, f) == expect[f] for f in LOCATOR_FIELDS if f in expect)


def value_ok(seg: Segment, item: Planted) -> bool:
    if norm(item.value) in norm(seg.text):
        return True
    if item.channel == "ocr" and len(norm(seg.text)) >= len(norm(item.value)):
        # partial_ratio aligns the shorter string inside the longer one; a segment shorter
        # than the value must never "contain" it.
        return fuzz.partial_ratio(norm(item.value), norm(seg.text)) >= OCR_MIN_RATIO
    return False


def matches(doc: Document, item: Planted) -> list[Segment]:
    return [s for s in doc.segments if locator_ok(s, item.expect) and value_ok(s, item)]
