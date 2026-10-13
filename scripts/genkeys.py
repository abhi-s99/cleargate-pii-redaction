"""Create a local .env with fresh development keys: python scripts/genkeys.py [path]

Refuses to overwrite an existing file. .env is git-ignored. Key values are not
printed.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(".env")
    if path.exists():
        print(f"{path} already exists, not overwriting")
        return 0
    lines = [
        "# Local development secrets. Never commit.",
        f"CLEARGATE_VAULT_KEY={Fernet.generate_key().decode()}",
        f"CLEARGATE_GATE_KEY={secrets.token_urlsafe(32)}",
        f"CLEARGATE_SUBMITTER_TOKEN={secrets.token_urlsafe(24)}",
        f"CLEARGATE_REVIEWER_TOKEN={secrets.token_urlsafe(24)}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {path} with 4 keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
