"""Gold labels resolved against an extracted Document (TRD section 9, FR-15).

Two sources, one shape:

* **synthetic**: the planted-PII manifest of ``tests/fixtures/synthetic`` (items, decoys,
  regions), invented values only. Used by ``make eval`` and the tests.
* **annotated**: ``eval/gold/<file>.jsonl`` in the TRD section 9 format, written by the
  annotators for the real samples (git-ignored, never committed). One line per item::

    {"doc": "...", "locator": {"part": "...", "table": 2, "row": 1, "col": 3},
     "text_sha256": "<sha256 of the segment text>", "start": 0, "end": 16,
     "type": "PERSON", "note": "..."}

  Optional line kinds: ``{"keep": true, ...}`` marks a business term that must stay
  (decoy), ``{"region": "face" | "unreadable", "locator": {"page": 3, "bbox": [...]}}``
  marks a region.

Values live in memory only; nothing here is written anywhere.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from cleargate.core.models import Document, Segment
from eval.metrics import Span, norm

LOCATOR_KEYS = ("part", "page", "slide", "table", "row", "col", "shape_id", "image_ref")
REGION_ENTITY = {"face": "PHOTO", "unreadable": "UNREADABLE_IMAGE_REGION"}


@dataclass
class GoldItem:
    id: str
    file: str
    entity_type: str
    value: str = field(repr=False)  # [RAW], memory only
    channel: str = "native"
    spans: list[Span] = field(default_factory=list)


@dataclass
class GoldRegion:
    file: str
    kind: str
    locator: dict[str, Any]


@dataclass
class GoldKeep:
    file: str
    value: str = field(repr=False)  # [RAW], memory only
    kind: str = "keep"


@dataclass
class GoldSet:
    items: list[GoldItem] = field(default_factory=list)
    regions: list[GoldRegion] = field(default_factory=list)
    keeps: list[GoldKeep] = field(default_factory=list)
    excluded: int = 0  # items with no text channel (image-only), not span-evaluable
    source: str = ""


def locate(seg: Segment, value: str, fuzzy: bool) -> Span | None:
    """Span of ``value`` inside ``seg`` (whitespace-tolerant, case-insensitive)."""
    pattern = r"\s+".join(re.escape(part) for part in value.split())
    m = re.search(pattern, seg.text, flags=re.IGNORECASE)
    if m:
        return Span(seg.segment_id, m.start(), m.end(), "", seg.text[m.start() : m.end()])
    if fuzzy and len(seg.text) >= len(value):
        al = fuzz.partial_ratio_alignment(norm(value), seg.text.casefold())
        if al is not None and al.score >= 90:
            s, e = al.dest_start, al.dest_end
            return Span(seg.segment_id, s, e, "", seg.text[s:e])
    return None


def from_manifest(docs: dict[str, Document], root: Path) -> GoldSet:
    from tests.fixtures.manifest import load_manifest, matches, planted_items

    gold = GoldSet(source=f"synthetic manifest ({root.name})")
    for item in planted_items(root):
        if item.file not in docs:
            continue
        if item.channel == "image-only":
            gold.excluded += 1
            continue
        spans = []
        for seg in matches(docs[item.file], item):
            sp = locate(seg, item.value, fuzzy=item.channel == "ocr")
            if sp is not None:
                spans.append(Span(sp.segment_id, sp.start, sp.end, item.type, sp.text))
        gold.items.append(GoldItem(item.id, item.file, item.type, item.value, item.channel, spans))
    manifest = load_manifest(root)
    for d in manifest.get("decoys", []):
        if d["file"] in docs:
            gold.keeps.append(GoldKeep(d["file"], d["value"], d["kind"]))
    for r in manifest.get("regions", []):
        if r["file"] in docs:
            loc = {k: v for k, v in r.items() if k not in ("file", "kind")}
            gold.regions.append(GoldRegion(r["file"], r["kind"], loc))
    return gold


def _seg_ok(seg: Segment, locator: dict[str, Any]) -> bool:
    loc = seg.locator
    return all(getattr(loc, k) == locator[k] for k in LOCATOR_KEYS if k in locator)


def from_jsonl(docs: dict[str, Document], gold_dir: Path) -> GoldSet:
    gold = GoldSet(source=f"annotated ({gold_dir.name}/)")
    for path in sorted(gold_dir.glob("*.jsonl")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            rec = json.loads(line)
            doc = docs.get(rec["doc"])
            if doc is None:
                continue
            locator = rec.get("locator", {})
            if "region" in rec:
                gold.regions.append(GoldRegion(rec["doc"], rec["region"], locator))
                continue
            segs = [
                s
                for s in doc.segments
                if hashlib.sha256(s.text.encode("utf-8")).hexdigest() == rec["text_sha256"]
                and _seg_ok(s, locator)
            ]
            value = segs[0].text[rec["start"] : rec["end"]] if segs else ""
            if rec.get("keep"):
                if value:
                    gold.keeps.append(GoldKeep(rec["doc"], value))
                continue
            spans = [Span(s.segment_id, rec["start"], rec["end"], rec["type"], value) for s in segs]
            channel = segs[0].method if segs else "native"
            gold.items.append(
                GoldItem(f"{path.stem}:{n + 1}", rec["doc"], rec["type"], value, channel, spans)
            )
    return gold
