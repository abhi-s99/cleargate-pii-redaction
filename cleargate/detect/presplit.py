"""Pre-processing before NER and context rules (TR-DT-01, TR-DT-02, Architecture D8).

* ``sub_spans``: split segment text into sub-spans on `` / ``, ``;``, ``|``, ``\u00b7``, tabs and
  (inside table cells and OCR lines) line breaks, so a cell listing four names gives four
  NER inputs. Offsets are kept, so findings map straight back onto the segment.
* ``normalise_with_map``: NFKC, ligatures, dash and quote unification, whitespace collapse,
  plus an index map from each normalised character back to the original string. Used for
  matching only; spans are always reported on the original text.
"""

from __future__ import annotations

import re
import unicodedata

from cleargate.core.models import Segment
from cleargate.detect.base import DASHES, QUOTES

SPLIT_ALWAYS = re.compile(r"\s+/\s+|;|\||\u00b7|\t")
SPLIT_CELL = re.compile(r"\s+/\s+|;|\||\u00b7|\t|\n|\r|\x0b")
CELL_KINDS = frozenset({"table_cell", "ocr_line"})


def sub_spans(seg: Segment) -> list[tuple[int, int]]:
    """Non-empty ``(start, end)`` pieces of ``seg.text`` after delimiter splitting."""
    rx = SPLIT_CELL if seg.kind in CELL_KINDS else SPLIT_ALWAYS
    text = seg.text
    out: list[tuple[int, int]] = []
    pos = 0
    for m in rx.finditer(text):
        out.append((pos, m.start()))
        pos = m.end()
    out.append((pos, len(text)))
    trimmed = []
    for start, end in out:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            trimmed.append((start, end))
    return trimmed


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Normalised text and ``index[i]`` = offset in ``text`` of normalised char ``i``."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        piece = unicodedata.normalize("NFKC", ch).translate(DASHES).translate(QUOTES)
        for c in piece:
            if c.isspace():
                if prev_space:
                    continue
                c = " "
                prev_space = True
            else:
                prev_space = False
            out.append(c)
            index.append(i)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def map_span(index: list[int], start: int, end: int, original_len: int) -> tuple[int, int]:
    """Map a normalised ``[start, end)`` back to the original string."""
    if not index:
        return (0, 0)
    s = index[min(start, len(index) - 1)]
    e = index[end - 1] + 1 if end - 1 < len(index) else original_len
    return (s, e)
