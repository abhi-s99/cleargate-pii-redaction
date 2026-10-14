"""Documented prototype limits stay documented (TR-SEC-09)."""

from __future__ import annotations

from cleargate.core.config import REPO_ROOT

LIMITS = (
    "static bearer tokens",
    "single tenant",
    "SQLite metadata (no raw PII)",
    "OS-permission protection for uploads",
    "mock AI client by default",
    "Worker memory limit is POSIX only",
)


def test_readme_lists_every_prototype_limit() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## Limitations", 1)[1].split("\n## ", 1)[0]
    for phrase in LIMITS:
        assert phrase in section, phrase
