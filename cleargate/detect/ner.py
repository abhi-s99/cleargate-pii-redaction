"""L3 statistical NER (TR-DT-13): Presidio ``AnalyzerEngine`` over spaCy ``en_core_web_lg``.

Input is pre-split into sub-spans (TR-DT-01) and processed in one batch per document
(``nlp.pipe`` through Presidio's ``process_batch``). Only ``SpacyRecognizer`` is
registered, so no Presidio recognizer can reach the network (TR-SEC-01).

* PERSON spans become L3 candidates. Spans containing digits are dropped (the model tags
  incident IDs such as ``INC-5531`` as PERSON); a trailing possessive is trimmed. Presidio
  scores every NER hit 0.85 (Architecture D13), so the candidate carries the ADR-28
  pre-calibration score instead.
* ORGANIZATION spans are returned separately, for allowlist auto-learning.
* LOCATION is used only as an address feature by context rules, never redacted alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cleargate.core.models import EntityType, Segment
from cleargate.detect.base import Candidate, candidate, evidence, overlaps_token
from cleargate.detect.lexicon import get_nlp, is_common_word
from cleargate.detect.presplit import sub_spans

_ENGINES: dict[str, tuple[Any, Any]] = {}
POSSESSIVE = re.compile(r"(?:'s|\u2019s|')$")
PARTICLES = frozenset(
    {"van", "von", "de", "da", "del", "della", "di", "du", "la", "le", "bin", "al", "ten", "ter"}
)
HONORIFIC = re.compile(r"^(?:Mr|Ms|Mrs|Miss|Mx|Dr|Prof)\.?\s+")


@dataclass(frozen=True)
class OrgSpan:
    segment_id: str
    start: int
    end: int
    text: str


def analyzer(model: str = "en_core_web_lg") -> tuple[Any, Any]:
    """``(AnalyzerEngine, SpacyNlpEngine)`` sharing the process-wide spaCy model."""
    if model not in _ENGINES:
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import SpacyNlpEngine
        from presidio_analyzer.predefined_recognizers import SpacyRecognizer

        nlp = get_nlp(model)
        engine = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": model}])
        engine.nlp = {"en": nlp}  # type: ignore[assignment]  # reuse the loaded model instead of loading a second copy
        registry = RecognizerRegistry(supported_languages=["en"])
        registry.add_recognizer(
            SpacyRecognizer(supported_entities=["PERSON", "LOCATION", "ORGANIZATION"])
        )
        _ENGINES[model] = (
            AnalyzerEngine(registry=registry, nlp_engine=engine, supported_languages=["en"]),
            engine,
        )
    return _ENGINES[model]


def ner_score(name: str) -> float:
    """Pre-calibration score of an NER-only PERSON (ADR-28)."""
    core = HONORIFIC.sub("", name).strip()
    tokens = [t for t in re.split(r"[\s]+", core) if t]
    if not tokens or not core[0].isupper():
        return 0.2
    if all(t.isupper() and len(t) > 1 for t in tokens):
        return 0.2  # acronyms
    long_tokens = [t for t in tokens if len(t.strip(".")) > 1]
    if any(t[0].islower() and t not in PARTICLES for t in long_tokens):
        return 0.3  # "Smith said", "Jones team": a lowercase word inside the span
    common = bool(long_tokens) and all(is_common_word(t) for t in long_tokens)
    if len(long_tokens) >= 2:
        return 0.45 if common else 0.6
    return 0.25 if common else 0.45


class NerRecognizer:
    name = "presidio_spacy"
    version = "0.5.0"
    layer = "L3"

    def __init__(self, model: str = "en_core_web_lg", *, skip_tokens: bool = False) -> None:
        self.model = model
        self.skip_tokens = skip_tokens

    def analyze_batch(self, segments: list[Segment]) -> tuple[list[Candidate], list[OrgSpan]]:
        an, engine = analyzer(self.model)
        pieces: list[tuple[Segment, int, int]] = []
        for seg in segments:
            if seg.kind == "metadata":
                continue
            pieces.extend(
                (seg, s, e) for s, e in sub_spans(seg) if any(c.isalpha() for c in seg.text[s:e])
            )
        texts = [seg.text[s:e] for seg, s, e in pieces]
        people: list[Candidate] = []
        orgs: list[OrgSpan] = []
        for (seg, s, _e), (text, artifacts) in zip(
            pieces, engine.process_batch(texts, language="en"), strict=True
        ):
            for r in an.analyze(text=text, language="en", nlp_artifacts=artifacts):
                start, end = s + r.start, s + r.end
                span = seg.text[start:end]
                if r.entity_type == "ORGANIZATION":
                    orgs.append(OrgSpan(seg.segment_id, start, end, span))
                    continue
                if r.entity_type != "PERSON" or any(c.isdigit() for c in span):
                    continue
                trimmed = POSSESSIVE.sub("", span).rstrip()
                end = start + len(trimmed)
                if end <= start or (self.skip_tokens and overlaps_token(seg.text, start, end)):
                    continue
                score = ner_score(trimmed)
                people.append(
                    candidate(
                        seg,
                        start,
                        end,
                        EntityType.PERSON,
                        evidence(self.name, "L3", "ner.person", score=score),
                        score=score,
                    )
                )
        return people, orgs
