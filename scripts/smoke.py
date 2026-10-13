"""Sample smoke run: python scripts/smoke.py

Runs the pipeline as far as it exists on the three real sample files and writes
a table (file, stage reached, state, counts by type, time, warnings) to
out/smoke.md. No document values are printed or written.

Phase 0: no pipeline stages exist yet, so this only records which sample files
are present and their sizes.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.conftest import SAMPLE_FILES, find_samples_dir  # noqa: E402


def main() -> int:
    samples = find_samples_dir()
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    rows = ["| File | Size (bytes) | Stage reached | State |", "|---|---:|---|---|"]
    if samples is None:
        print("smoke: sample files not present (samples/ or Data/); nothing to run")
        return 0
    for name in SAMPLE_FILES:
        rows.append(f"| {name} | {(samples / name).stat().st_size} | none (Phase 0) | n/a |")
    stamp = datetime.now(tz=UTC).isoformat(timespec="seconds")
    text = f"# Sample smoke\n\nGenerated {stamp}. No pipeline stages yet.\n\n" + "\n".join(rows)
    (out / "smoke.md").write_text(text + "\n", encoding="utf-8")
    print("\n".join(rows))
    print("smoke: wrote out/smoke.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
