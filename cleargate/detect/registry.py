"""Batch person registry (TR-DT-15 points 1, 2 and 5; ADR-04 layer 5).

Seeded with PERSON findings of tier CORROBORATED or better (and reviewer-added spans). Each
person has a canonical key: NFKC, case-folded, honorifics and middle initials removed. An
abbreviated mention (``A. Szabo``) resolves to the one registered person with that surname
and first initial. Variants feed propagation and the V2 leak needles: ``First Last``,
``F. Last``, ``F Last``, ``Last, F.``, ``Hon. Last``, and email local parts ``f.last``,
``flast``, ``first.last``, ``firstlast`` (hyphens removed).

Keys and variants hold names and therefore live in memory only. What leaves the registry is
``person_key``: an HMAC of the canonical key, safe to store in ``meta.db``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass, field

HONORIFICS = frozenset({"mr", "ms", "mrs", "miss", "mx", "dr", "prof", "sir", "dame", "hon"})
HON_TITLES = ("Mr", "Ms", "Mrs", "Dr", "Prof")


def name_tokens(name: str) -> list[str]:
    t = unicodedata.normalize("NFKC", name).replace("\u2019", "'")
    return [tok for tok in re.split(r"[\s,]+", t.strip()) if tok]


def canonical_key(name: str) -> str:
    toks = [t.strip(".").casefold() for t in name_tokens(name)]
    toks = [t for t in toks if t and t not in HONORIFICS]
    if len(toks) > 2:
        toks = [toks[0], *[t for t in toks[1:-1] if len(t) > 1], toks[-1]]
    return " ".join(toks)


@dataclass
class Person:
    key: str
    first: str
    last: str
    middles: list[str] = field(default_factory=list)

    @property
    def full(self) -> bool:
        return len(self.first) > 1


class PersonRegistry:
    def __init__(self, hmac_key: bytes = b"") -> None:
        self.hmac_key = hmac_key
        self.people: dict[str, Person] = {}

    def __len__(self) -> int:
        return len(self.people)

    def add(self, name: str) -> str | None:
        """Register ``name``; returns its canonical key (None if not name-like)."""
        key = canonical_key(name)
        parts = key.split()
        if len(parts) < 2 or any(len(p) < 1 for p in parts):
            return None
        existing = self.resolve(name)
        if existing:
            person = self.people[existing]
            if not person.full and len(parts[0]) > 1:  # upgrade "a szabo" to "anika szabo"
                del self.people[existing]
                self.people[key] = Person(key, parts[0], parts[-1], parts[1:-1])
                return key
            return existing
        self.people[key] = Person(key, parts[0], parts[-1], parts[1:-1])
        return key

    def resolve(self, name: str) -> str | None:
        key = canonical_key(name)
        if key in self.people:
            return key
        parts = key.split()
        if len(parts) < 2:
            return None
        first, last = parts[0], parts[-1]
        same_last = [p for p in self.people.values() if p.last == last]
        if len(first) == 1:
            hits = [p for p in same_last if p.first.startswith(first)]
            return hits[0].key if len(hits) == 1 else None
        hits = [p for p in same_last if not p.full and first.startswith(p.first)]
        return hits[0].key if len(hits) == 1 else None

    def has_surname(self, surname: str) -> bool:
        s = surname.casefold()
        return any(p.last == s for p in self.people.values())

    def unique_surnames(self) -> dict[str, str]:
        counts: dict[str, list[str]] = {}
        for p in self.people.values():
            counts.setdefault(p.last, []).append(p.key)
        return {last: keys[0] for last, keys in counts.items() if len(keys) == 1}

    def person_key(self, key: str) -> str:
        digest = hmac.new(self.hmac_key, key.encode(), hashlib.sha256).hexdigest()
        return f"p:{digest[:20]}"

    def variants(self, key: str) -> list[str]:
        p = self.people[key]
        first, last = p.first.title(), p.last.title()
        last = "-".join(x.title() for x in p.last.split("-"))
        fi = p.first[0].upper()
        out = {f"{fi}. {last}", f"{fi} {last}", f"{last}, {fi}."}
        if p.full:
            out.add(f"{first} {last}")
            out.add(f"{last}, {first}")
            if p.middles:
                mi = " ".join(f"{m[0].upper()}." for m in p.middles)
                out.add(f"{fi}. {mi} {last}")
                out.add(f"{first} {mi} {last}")
        out.update(f"{h} {last}" for h in HON_TITLES)
        return sorted(out, key=lambda v: (-len(v), v))

    def email_locals(self, key: str) -> list[str]:
        p = self.people[key]
        last = p.last.replace("-", "")
        out = {f"{p.first[0]}.{last}", f"{p.first[0]}{last}"}
        if p.full:
            first = p.first.replace("-", "")
            out |= {f"{first}.{last}", f"{first}{last}"}
        return sorted(out)
