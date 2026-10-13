"""V5 consistency and V6 structure (TRD 8.1, TRD 9).

* ``consistency``: tokens in the outputs are well formed (no token inside a token), each
  maps to a vault entry of the same type, every person key has one token and every person
  token one person key.
* ``srs``: Structure Retention Score = matched units / source units, over pages or slides,
  headings (with level), paragraphs, list items, tables, table cells and images. A unit
  matches when the re-extracted output has a unit of the same kind at the same position.
* ``crs``: Context Retention Score = sum over rendered segments of LCS(non-PII source
  tokens, sanitized tokens) / non-PII source tokens.
"""

from __future__ import annotations

import re
from collections import Counter

from cleargate.core.models import TOKEN_LABEL, Document, EntityType, Finding
from cleargate.redact.text_renderer import rendered, sanitized_segment, span_plan

TOKEN_RE = re.compile(r"\[([A-Z][A-Z_]*?)(?:_(\d+))?\]")
NESTED = re.compile(r"\[[A-Z_0-9]*\[")
LABEL_TYPES: dict[str, set[str]] = {}
for _t, _label in TOKEN_LABEL.items():
    if _label:
        LABEL_TYPES.setdefault(_label, set()).add(_t.value)
UNIT_KINDS = ("heading", "paragraph", "list_item", "table_cell")
# Annotation texts, link URIs, form values and outline titles are not body structure.
NON_BODY = frozenset({"page-annots", "page-links", "page-widgets", "pdf:outline"})


def consistency(
    texts: list[str],
    vault_entries: dict[str, set[str]],
    person_tokens: dict[str, set[str]],
    findings: list[Finding],
) -> bool:
    for text in texts:
        if NESTED.search(text):
            return False
        for m in TOKEN_RE.finditer(text):
            token, label = m.group(0), m.group(1)
            if token == "[REDACTED]" or label not in LABEL_TYPES:  # noqa: S105 (scrub marker)
                continue  # fixed scrub marker, or bracketed text that is not a token
            types = vault_entries.get(token)
            if types is None or not types <= LABEL_TYPES[label]:
                return False
    if any(len(tokens) != 1 for tokens in person_tokens.values()):
        return False
    owners: dict[str, set[str]] = {}
    for f in findings:
        if f.entity_type is EntityType.PERSON and f.token and f.person_key:
            owners.setdefault(f.token, set()).add(f.person_key)
    return all(len(keys) == 1 for keys in owners.values())


def _units(doc: Document) -> Counter[tuple[object, ...]]:
    c: Counter[tuple[object, ...]] = Counter()
    for key in ("pages", "slides"):
        for i in range(doc.units.get(key, 0)):
            c[(key, i)] += 1
    for i in range(doc.units.get("images", 0)):
        c[("image", i)] += 1
    tables = set()
    for s in doc.segments:
        loc = s.locator
        if s.kind in UNIT_KINDS and loc.part not in NON_BODY:
            c[
                (
                    s.kind,
                    loc.part,
                    loc.page,
                    loc.slide,
                    loc.paragraph_index,
                    loc.table,
                    loc.row,
                    loc.col,
                    s.heading_level,
                )
            ] += 1
        if s.kind == "table_cell":
            tables.add((loc.part, loc.slide, loc.table))
    for t in tables:
        c[("table", *t)] += 1
    return c


def srs(src: Document, out: Document) -> float:
    a, b = _units(src), _units(out)
    total = sum(a.values())
    if total == 0:
        return 1.0
    return round(sum((a & b).values()) / total, 4)


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def _lcs(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def crs(src: Document, findings: list[Finding]) -> float:
    plan = span_plan(findings)
    kept = matched = 0
    for seg in src.segments:
        if not rendered(seg):
            continue
        spans = plan.get(seg.segment_id, [])
        text = seg.text
        non_pii = text
        for s, e, _tok in sorted(spans, reverse=True):
            non_pii = non_pii[:s] + " " + non_pii[e:]
        src_tokens = _tokens(non_pii)
        if not src_tokens:
            continue
        kept += len(src_tokens)
        out_tokens = _tokens(TOKEN_RE.sub(" ", sanitized_segment(seg, plan)))
        if len(src_tokens) * len(out_tokens) > 250_000:  # very long segment: bounded cost
            matched += sum((Counter(src_tokens) & Counter(out_tokens)).values())
        else:
            matched += _lcs(src_tokens, out_tokens)
    return round(matched / kept, 4) if kept else 1.0
