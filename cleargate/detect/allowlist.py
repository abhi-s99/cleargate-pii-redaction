"""Business-entity allowlist (TRD 6.3 point 3, ADR-04 "the vendor problem", FR-06).

Terms come from the policy (``allowlist.organisations`` and ``allowlist.products``) and,
with ``auto_learn_orgs``, from NER ORGANIZATION spans that carry a corporate suffix or sit
in vendor context. The allowlist can only suppress a finding whose evidence is **all** L3
NER, whose normalised span equals a term, and whose person is not in the registry. It never
suppresses L1/L2/L4/L5 evidence (an email, a labelled value, a registered person).
"""

from __future__ import annotations

import re

from cleargate.core.config import AllowlistPolicy
from cleargate.core.models import Segment
from cleargate.detect.base import Candidate, normalise_text
from cleargate.detect.ner import OrgSpan
from cleargate.detect.registry import PersonRegistry, canonical_key

CORPORATE_SUFFIX = re.compile(
    r"\b(?:Inc|Incorporated|LLP|LLC|Ltd|Limited|GmbH|SA|S\.A\.|AG|Pte|plc|PLC|Corp|"
    r"Corporation|Co|NV|BV|SAS|SpA|Pty)\.?$"
)
VENDOR_CONTEXT = re.compile(
    r"\b(?:integration\s+with|vendor|provider|supplier|platform|tool|software|"
    r"subscription|licen[cs]e[sd]?|SaaS)\b",
    re.I,
)


def norm(term: str) -> str:
    return normalise_text(term).casefold().strip(" .,'\u2019")


class Allowlist:
    def __init__(self, terms: dict[str, str]) -> None:
        self.terms = terms  # normalised -> configured spelling

    @classmethod
    def build(
        cls,
        policy: AllowlistPolicy,
        orgs: list[OrgSpan] = (),  # type: ignore[assignment]
        segments: dict[str, Segment] | None = None,
    ) -> Allowlist:
        terms = {norm(t): t for t in [*policy.organisations, *policy.products]}
        if policy.auto_learn_orgs:
            for org in orgs:
                text = org.text.strip()
                seg = (segments or {}).get(org.segment_id)
                around = seg.text[max(0, org.start - 40) : org.end + 40] if seg else ""
                if CORPORATE_SUFFIX.search(text) or VENDOR_CONTEXT.search(around):
                    terms.setdefault(norm(text), text)
        return cls(terms)

    def suppresses(self, c: Candidate, registry: PersonRegistry | None) -> str | None:
        """The allowlist term that suppresses ``c``, or None."""
        layers = {e.layer for e in c.evidence if not e.rule_id.startswith("merged:")}
        if layers != {"L3"}:
            return None
        term = self.terms.get(norm(c.value))
        if term is None:
            return None
        if registry is not None and (
            canonical_key(c.value) in registry.people or registry.resolve(c.value)
        ):
            return None
        return term
