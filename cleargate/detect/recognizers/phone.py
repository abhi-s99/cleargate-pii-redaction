"""L1 phone recognizer (TR-DT-10): ``phonenumbers.PhoneNumberMatcher``, leniency VALID.

Regions US, GB, IN, PL, FR, DE, SG, SE; overlapping matches from different regions are
merged to the longest span. Numbers the library rejects (the sample's ``+1 (555) 01xx``
mobiles, Architecture D9) are caught by the label-anchored layer instead.
"""

from __future__ import annotations

import phonenumbers

from cleargate.core.models import EntityType, Segment
from cleargate.detect.base import Candidate, DocContext, candidate, evidence

REGIONS = ("US", "GB", "IN", "PL", "FR", "DE", "SG", "SE")


def phone_valid(value: str) -> bool:
    """True if the library accepts ``value`` as a valid number in any region."""
    for region in REGIONS:
        try:
            if phonenumbers.is_valid_number(phonenumbers.parse(value, region)):
                return True
        except phonenumbers.NumberParseException:
            continue
    return False


class PhoneRecognizer:
    name = "phone"
    version = "0.4.0"
    layer = "L1"

    def analyze(self, seg: Segment, ctx: DocContext) -> list[Candidate]:
        spans: list[tuple[int, int, str]] = []
        for region in REGIONS:
            for m in phonenumbers.PhoneNumberMatcher(
                seg.text, region, leniency=phonenumbers.Leniency.VALID
            ):
                spans.append((m.start, m.end, region))
        merged: list[tuple[int, int, str]] = []
        for start, end, region in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
            if merged and start < merged[-1][1]:
                if end > merged[-1][1]:
                    merged[-1] = (merged[-1][0], end, merged[-1][2])
                continue
            merged.append((start, end, region))
        return [
            candidate(
                seg,
                start,
                end,
                EntityType.PHONE_NUMBER,
                evidence(self.name, "L1", f"phone.matcher_{region}", score=1.0),
            )
            for start, end, region in merged
        ]
