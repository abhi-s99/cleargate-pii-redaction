"""Registry propagation sweep (TR-DT-15 points 3 and 4).

Every segment is swept for registry variants:

* exact, case-insensitive, word-bounded matches in every segment: full names, allowing up
  to two middle initials (``registry.exact_full``, CORROBORATED: the person was already
  confirmed elsewhere, ADR-28), and abbreviated variants such as ``F. Last``
  (``registry.exact_abbrev``);
* OCR segments additionally: ``rapidfuzz.fuzz.ratio >= fuzzy_ocr_ratio`` between a token
  window (variant token count +-1) and the multi-token variants (``registry.fuzzy_ocr``);
* surname only: when the surname is unique in the registry, has at least 5 characters, is
  not a common English word and is capitalised in the text (``registry.surname_only``,
  SINGLE_SIGNAL score 0.5, review band).

Candidates carry the person's ``person_key`` so tokens stay consistent across the batch.
"""

from __future__ import annotations

import re
from dataclasses import replace

from rapidfuzz import fuzz, process

from cleargate.core.models import EntityType, Segment
from cleargate.detect.base import Candidate, candidate, evidence, overlaps_token
from cleargate.detect.lexicon import is_common_word
from cleargate.detect.registry import PersonRegistry

DETECTOR = "registry"
VERSION = "0.5.0"


class Propagator:
    def __init__(
        self,
        registry: PersonRegistry,
        *,
        fuzzy_ratio: int = 90,
        surname_only: bool = True,
        skip_tokens: bool = False,
    ) -> None:
        self.registry = registry
        self.fuzzy_ratio = fuzzy_ratio
        self.skip_tokens = skip_tokens
        self.variant_of: dict[str, str] = {}
        full_alts: list[str] = []
        for key, person in registry.people.items():
            for v in registry.variants(key):
                self.variant_of.setdefault(v.casefold(), key)
            if person.full:
                last = re.escape(person.last).replace(r"\-", r"[\-\s]?")
                full_alts.append(re.escape(person.first) + r"\s+(?:[a-z]\.?\s+){0,2}" + last)
                full_alts.append(last + r",\s*" + re.escape(person.first))
        alts = sorted(self.variant_of, key=lambda v: (-len(v), v))
        # Full names (first + optional middle initials + last): a confirmed person (ADR-28).
        self.full_re = (
            re.compile(
                r"(?<![\w])(" + "|".join(sorted(full_alts, key=len, reverse=True)) + r")(?![\w])",
                re.I,
            )
            if full_alts
            else None
        )
        abbrev = [v for v in alts if not self._is_full(v)]
        self.exact = (
            re.compile(r"(?<![\w])(" + "|".join(re.escape(v) for v in abbrev) + r")(?![\w])", re.I)
            if abbrev
            else None
        )
        self.fuzzy_choices = [v for v in alts if " " in v and len(v) >= 6]
        self.surnames: dict[str, str] = {}
        if surname_only:
            for last, key in registry.unique_surnames().items():
                if len(last) >= 5 and not is_common_word(last):
                    self.surnames[last] = key
        self.surname_re = (
            re.compile(
                r"(?<![\w.])("
                + "|".join(
                    re.escape("-".join(x.title() for x in s.split("-"))) for s in self.surnames
                )
                + r")(?![\w])"
            )
            if self.surnames
            else None
        )

    def _is_full(self, variant: str) -> bool:
        key = self.variant_of.get(variant.casefold())
        person = self.registry.people.get(key) if key else None
        return bool(person and person.full and person.first in variant.casefold())

    def _emit(
        self, seg: Segment, s: int, e: int, key: str, rule: str, score: float
    ) -> Candidate | None:
        if self.skip_tokens and overlaps_token(seg.text, s, e):
            return None
        c = candidate(
            seg, s, e, EntityType.PERSON, evidence(DETECTOR, "L5", rule, score=score), score=score
        )
        return replace(c, person_key=self.registry.person_key(key))

    def sweep(self, seg: Segment) -> list[Candidate]:
        if seg.kind == "metadata" or not self.registry.people:
            return []
        out: list[Candidate] = []
        text = seg.text
        taken: list[tuple[int, int]] = []
        if self.full_re:
            for m in self.full_re.finditer(text):
                name = m.group(1)
                if "," in name:  # "Last, First"
                    last, first = name.split(",", 1)
                    name = f"{first} {last}"
                key = self.registry.resolve(name)
                if key is None:
                    continue
                c = self._emit(seg, m.start(1), m.end(1), key, "registry.exact_full", 0.6)
                if c:
                    out.append(c)
                    taken.append((m.start(1), m.end(1)))
        if self.exact:
            for m in self.exact.finditer(text):
                if any(s < m.end(1) and m.start(1) < e for s, e in taken):
                    continue
                key = self.variant_of[m.group(1).casefold()]
                c = self._emit(seg, m.start(1), m.end(1), key, "registry.exact_abbrev", 0.6)
                if c:
                    out.append(c)
                    taken.append((m.start(1), m.end(1)))
        if seg.method == "ocr" and self.fuzzy_choices:
            fuzzy = self._fuzzy(seg, taken)
            out.extend(fuzzy)
            taken.extend((c.start, c.end) for c in fuzzy)
        if self.surname_re:
            for m in self.surname_re.finditer(text):
                if any(s <= m.start(1) < e for s, e in taken):
                    continue
                key = self.surnames[m.group(1).casefold()]
                c = self._emit(seg, m.start(1), m.end(1), key, "registry.surname_only", 0.5)
                if c:
                    out.append(c)
        return out

    def _fuzzy(self, seg: Segment, taken: list[tuple[int, int]]) -> list[Candidate]:
        text = seg.text
        toks = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        out: list[Candidate] = []
        used: list[tuple[int, int]] = list(taken)
        for size in (3, 2, 4):
            for i in range(len(toks) - size + 1):
                s, e = toks[i][0], toks[i + size - 1][1]
                while e > s and not text[e - 1].isalnum():
                    e -= 1
                if any(s < ue and us < e for us, ue in used):
                    continue
                if not text[s].isupper():
                    continue  # names start with a capital; lowercase or digit windows are noise
                window = text[s:e].casefold()
                if len(window) < 6 or not any(c.isalpha() for c in window):
                    continue
                hit = process.extractOne(
                    window, self.fuzzy_choices, scorer=fuzz.ratio, score_cutoff=self.fuzzy_ratio
                )
                if hit is None:
                    continue
                c = self._emit(seg, s, e, self.variant_of[hit[0]], "registry.fuzzy_ocr", 0.6)
                if c:
                    out.append(c)
                    used.append((s, e))
        return out
