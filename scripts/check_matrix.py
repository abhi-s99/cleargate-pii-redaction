"""Verification-matrix completeness check (brief section 4.6).

python scripts/check_matrix.py

1. Every requirement ID in docs/TRD.md and docs/PRD.md (TR-xx-nn, FR-nn), plus
   gate rules G0..G7 and verification checks V1..V6, has a row in
   docs/VERIFICATION.md.
2. Each row's status is one of PASS, PARTIAL, XFAIL, TODO.
3. Rows marked PASS, PARTIAL or XFAIL cite at least one test, and every cited
   test (``tests/...py::test_name``) exists as a function in that file.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"\b(TR-[A-Z]{2,3}-\d{2}|FR-\d{2})\b")
TEST_RE = re.compile(r"(tests/[\w/]+\.py)::(\w+)")
STATUSES = {"PASS", "PARTIAL", "XFAIL", "TODO"}
EXTRA_IDS = [f"G{i}" for i in range(8)] + [f"V{i}" for i in range(1, 7)]


def required_ids() -> list[str]:
    ids: set[str] = set(EXTRA_IDS)
    for doc in ("docs/TRD.md", "docs/PRD.md"):
        ids |= set(ID_RE.findall((ROOT / doc).read_text(encoding="utf-8")))
    return sorted(ids)


def matrix_rows() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for line in (ROOT / "docs/VERIFICATION.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not (ID_RE.fullmatch(cells[0]) or cells[0] in EXTRA_IDS):
            continue
        rows[cells[0]] = (cells[-2], cells[-1].split()[0] if cells[-1] else "")
    return rows


def test_exists(path: str, name: str) -> bool:
    file = ROOT / path
    return (
        file.is_file()
        and re.search(rf"^\s*(async\s+)?def {name}\(", file.read_text(encoding="utf-8"), re.M)
        is not None
    )


def main() -> int:
    rows = matrix_rows()
    problems: list[str] = []
    for req in required_ids():
        if req not in rows:
            problems.append(f"{req}: missing from docs/VERIFICATION.md")
    for req, (tests, status) in rows.items():
        if status not in STATUSES:
            problems.append(f"{req}: unknown status {status!r}")
            continue
        refs = TEST_RE.findall(tests)
        if status != "TODO" and not refs:
            problems.append(f"{req}: status {status} but no test cited")
        problems.extend(
            f"{req}: cited test not found {p}::{n}" for p, n in refs if not test_exists(p, n)
        )
    counts = {s: sum(1 for _, st in rows.values() if st == s) for s in sorted(STATUSES)}
    for problem in problems:
        print(problem)
    print(f"check_matrix: {len(rows)} rows {counts}, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
