"""Shared spaCy model and the common-English-word list (TR-PF-05, TR-DT-15 point 4).

``get_nlp`` loads ``en_core_web_lg`` once per process; NER (Presidio) and the word list
share it. A load failure raises ``MODEL_UNAVAILABLE`` (Architecture 6: running without NER
would silently drop all name detection, so the job fails instead).

The TRD's "50k common-English-word list" is approximated by the 50 000 most frequent
lowercase alphabetic entries of the model's vector table, which is stored in frequency
order (ADR-28). Common surnames such as ``hunter`` or ``smith`` are in it on purpose: a
surname that is also a common word must not be propagated on its own.
"""

from __future__ import annotations

import threading
from typing import Any

from cleargate.core.errors import ClearGateError, ErrorCode

COMMON_WORDS_N = 50_000
_LOCK = threading.Lock()
_NLP: dict[str, Any] = {}
_COMMON: dict[str, frozenset[str]] = {}


def get_nlp(model: str = "en_core_web_lg") -> Any:
    with _LOCK:
        if model not in _NLP:
            try:
                import spacy

                _NLP[model] = spacy.load(model)
            except (OSError, ImportError):
                raise ClearGateError(ErrorCode.MODEL_UNAVAILABLE, model=model) from None
        return _NLP[model]


def common_words(model: str = "en_core_web_lg") -> frozenset[str]:
    if model not in _COMMON:
        nlp = get_nlp(model)
        strings = nlp.vocab.strings
        words: list[str] = []
        for key in nlp.vocab.vectors:
            s = strings[key]
            if s.isalpha() and s.islower():
                words.append(s)
                if len(words) >= COMMON_WORDS_N:
                    break
        _COMMON[model] = frozenset(words)
    return _COMMON[model]


def is_common_word(token: str) -> bool:
    return token.casefold().strip(".'\u2019") in common_words()
