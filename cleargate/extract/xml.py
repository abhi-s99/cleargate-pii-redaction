"""Safe XML access for OOXML parts plus the generic sweeps every OOXML extractor runs.

* ``parse_part``: lxml with DTDs, entities and network access disabled (TR-SEC-07).
* ``generic_text``: all text nodes of a part, for parts no structured walker handles,
  so no XML part is silently skipped (ADR-26).
* ``author_attributes``: person names held in *attributes* (tracked-change and comment
  authors, initials, user ids, PowerPoint comment authors), which text extraction misses.
"""

from __future__ import annotations

import zipfile

from lxml import etree

from cleargate.core.errors import ErrorCode, ExtractionError

SAFE = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    dtd_validation=False,
    huge_tree=False,
    remove_blank_text=False,
)
AUTHOR_ATTRS = frozenset({"author", "initials", "userId", "providerId", "lastModifiedBy"})
# PowerPoint comment authors and Word 2013 people part carry the name in "name".
NAME_ATTR_ELEMENTS = frozenset({"cmAuthor", "author", "person", "presenceInfo"})
SKIP_GENERIC = (".rels",)


def parse_part(zf: zipfile.ZipFile, name: str) -> etree._Element:
    data = zf.read(name)
    if b"<!DOCTYPE" in data[:4096].upper() or b"<!ENTITY" in data.upper():
        raise ExtractionError(ErrorCode.EXTRACTION_FAILED, part=name)
    try:
        return etree.fromstring(data, parser=SAFE)
    except etree.XMLSyntaxError:
        raise ExtractionError(ErrorCode.EXTRACTION_FAILED, part=name) from None


def local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def generic_text(root: etree._Element) -> list[str]:
    """Stripped text nodes in document order; the writer edits the same nodes (textmap)."""
    from cleargate.extract.textmap import generic_text as _generic

    return _generic(root)


def author_attributes(root: etree._Element) -> list[tuple[str, str]]:
    """``(xpath_of_attribute, value)`` for unique person-like attribute values."""
    tree = root.getroottree()
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr, value in el.attrib.items():
            name = local(attr)
            if name in AUTHOR_ATTRS or (name == "name" and local(el.tag) in NAME_ATTR_ELEMENTS):
                value = value.strip()
                if value and value not in seen:
                    seen.add(value)
                    out.append((f"{tree.getpath(el)}/@{name}", value))
    return out
