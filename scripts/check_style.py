"""Project style rule: no emoji and no em dashes in any tracked text file.

python scripts/check_style.py [paths...]   (default: all git-tracked + staged files)

Exits 1 and lists file:line for each violation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
    ".json",
    ".jsonl",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".cjs",
    ".mjs",
    ".sh",
    ".ps1",
    ".gitignore",
    ".baseline",
    "",
}
SKIP_PARTS = {".venv", ".git", "node_modules", "synthetic", "dist"}

EM_DASH = "\u2014"


def is_banned(ch: str) -> bool:
    cp = ord(ch)
    return (
        ch == EM_DASH
        or 0x1F000 <= cp <= 0x1FAFF  # emoji and pictographs
        or 0x2600 <= cp <= 0x27BF  # misc symbols and dingbats
        or 0x2B00 <= cp <= 0x2BFF  # arrows/shapes block holding large squares/stars
        or cp in (0xFE0F, 0x200D, 0x23F3, 0x231B, 0x23F0, 0x25B6, 0x25C0)
    )


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [root / line for line in out.splitlines() if line]


def violations(path: Path) -> list[str]:
    if path.suffix not in TEXT_SUFFIXES or SKIP_PARTS & set(path.parts):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        bad = sorted({f"U+{ord(c):04X}" for c in line if is_banned(c)})
        if bad:
            found.append(f"{path}:{lineno}: {', '.join(bad)}")
    return found


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    paths = [Path(p) for p in argv[1:]] or tracked_files(root)
    problems = [v for p in paths if p.is_file() for v in violations(p)]
    for problem in problems:
        print(problem)
    print(f"check_style: {len(problems)} violation(s) in {len(paths)} file(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
