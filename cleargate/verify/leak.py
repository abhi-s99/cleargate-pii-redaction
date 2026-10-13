"""V2 known-value leak check (TRD 8.1, ADR-08).

Needles come from every redacted finding (``auto_redact`` and ``review``): the value and its
normal forms (case-folded, whitespace collapsed, digits only for numeric types, the email
local part) plus registry name variants of every redacted person (``F. Last``, ``Last, F.``,
``Dr Last`` ...). Haystacks are the outputs read back by ``reextract`` and the sanitized text.
Both sides are normalised the same way (NFKC, unified dashes, case-folded, whitespace
collapsed; a second copy with separators inside digit runs removed). Matching is one
Aho-Corasick pass with word boundaries.

Short values: a needle needs 4+ characters. A number of fewer than 6 digits (a card
ending, an SSN last four) would match unrelated numbers (years, page numbers), so it is
searched together with the word that preceded it in the source (``ending 4417``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import ahocorasick

from cleargate.core.models import EntityType, Finding, Segment
from cleargate.detect.base import NUMERIC_TYPES, normalise_text
from cleargate.detect.registry import PersonRegistry

REDACTING = ("auto_redact", "review")
REGION_TYPES = (EntityType.PHOTO, EntityType.UNREADABLE_IMAGE_REGION)
MIN_NEEDLE = 4
CASED = "\x00cased:"  # needle-map key prefix for case-sensitive one-word needles
DIGIT_SEP = re.compile(r"(?<=\d)[\s\-./]+(?=\d)")


def norm(text: str) -> str:
    return normalise_text(text).casefold()


def compact_digits(text: str) -> str:
    return DIGIT_SEP.sub("", text)


def needles(findings: list[Finding], segments: dict[str, Segment]) -> dict[str, str]:
    """Normalised needle -> entity type (for counting by type; never logged)."""
    out: dict[str, str] = {}
    reg = PersonRegistry()
    for f in findings:
        if f.decision not in REDACTING or f.entity_type in REGION_TYPES:
            continue
        value = f.value.strip()
        forms = {norm(value)}
        digits = re.sub(r"\D", "", value)
        if f.entity_type in NUMERIC_TYPES and digits:
            if len(digits) < 6:
                seg = segments.get(f.segment_id)
                before = re.findall(r"[\w#]+", seg.text[: f.start])[-1:] if seg else []
                forms = {norm(f"{before[0]} {value}")} if before else set()
            else:
                forms.add(digits)
        if f.entity_type is EntityType.EMAIL_ADDRESS and "@" in value:
            local = value.split("@", 1)[0]
            if len(local) >= 6 and not local.isdigit():
                forms.add(norm(local))
        if f.entity_type is EntityType.PERSON and f.tier in ("DETERMINISTIC", "CORROBORATED"):
            key = reg.add(value)  # registry variants exist for registered persons only
            if key:
                forms.update(norm(v) for v in reg.variants(key) if len(v) >= 6)
        if " " not in value and value.isalpha():
            # One word: matched with its case, like value propagation (``Grace`` is a name,
            # ``grace`` is not).
            forms = {CASED + normalise_text(value)}
        for form in forms:
            if len(form.removeprefix(CASED)) >= MIN_NEEDLE:
                out.setdefault(form, f.entity_type.value)
    return out


def _automaton(words: dict[str, str]) -> ahocorasick.Automaton | None:
    if not words:
        return None
    auto = ahocorasick.Automaton()
    for needle, etype in words.items():
        auto.add_word(needle, (needle, etype))
    auto.make_automaton()
    return auto


def leak_hits(needle_map: dict[str, str], texts: Iterable[str]) -> dict[str, int]:
    """Count of hits by entity type (never the values)."""
    folded = _automaton({k: v for k, v in needle_map.items() if not k.startswith(CASED)})
    cased = _automaton(
        {k.removeprefix(CASED): v for k, v in needle_map.items() if k.startswith(CASED)}
    )
    hits: dict[str, int] = {}
    for raw in texts:
        n = norm(raw)
        plain = normalise_text(raw)
        for auto, hays in ((folded, {n, compact_digits(n)}), (cased, {plain})):
            if auto is None:
                continue
            for hay in hays:
                _scan(auto, hay, hits)
    return hits


def _scan(auto: ahocorasick.Automaton, hay: str, hits: dict[str, int]) -> None:
    """Count word-bounded matches by entity type into ``hits``."""
    for end, (needle, etype) in auto.iter(hay):
        start = end - len(needle) + 1
        before = hay[start - 1] if start > 0 else " "
        after = hay[end + 1] if end + 1 < len(hay) else " "
        if before.isalnum() or after.isalnum():
            continue
        hits[etype] = hits.get(etype, 0) + 1


def locate(
    needle_map: dict[str, str], rasters: list[Any]
) -> dict[tuple[str, str | int], list[tuple[float, float, float, float]]]:
    """Source-pixel boxes of V2 hits inside OCR'd output rasters (repair pass, ADR-30).

    Words of a raster are joined in reading order (lines included), so a value broken over
    two lines is found too; each hit becomes one box per line it touches.
    """
    out: dict[tuple[str, str | int], list[tuple[float, float, float, float]]] = {}
    folded = {k for k in needle_map if not k.startswith(CASED)}
    cased = {k.removeprefix(CASED) for k in needle_map if k.startswith(CASED)}
    for raster in rasters:
        words = [
            (w, line_no) for line_no, line in enumerate(raster.result.lines) for w in line.words
        ]
        if not words:
            continue
        for fold, needles_set in ((True, folded), (False, cased)):
            if not needles_set:
                continue
            parts, starts = [], []
            pos = 0
            for w, _ in words:
                t = norm(w.text) if fold else normalise_text(w.text)
                starts.append(pos)
                parts.append(t)
                pos += len(t) + 1
            hay = " ".join(parts)
            for needle in needles_set:
                for m in re.finditer(re.escape(needle), hay):
                    a, b = m.start(), m.end()
                    if (a > 0 and hay[a - 1].isalnum()) or (b < len(hay) and hay[b].isalnum()):
                        continue
                    hit = [i for i, s in enumerate(starts) if s < b and a < s + len(parts[i])]
                    by_line: dict[int, list[Any]] = {}
                    for i in hit:
                        by_line.setdefault(words[i][1], []).append(words[i][0])
                    for ws in by_line.values():
                        sc = raster.scale or 1.0
                        out.setdefault(raster.key, []).append(
                            (
                                min(w.box[0] for w in ws) / sc,
                                min(w.box[1] for w in ws) / sc,
                                max(w.box[2] for w in ws) / sc,
                                max(w.box[3] for w in ws) / sc,
                            )
                        )
    return out
