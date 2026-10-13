"""Environment check: python scripts/doctor.py [--env-file .env]

Checks Python version, Tesseract >= 5 with eng, the configured spaCy model,
OpenCV face cascades, a writable data dir, and the vault/gate keys. Prints one
line per check and exits 1 if any required check fails. Key values are never
printed.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cleargate.core.config import (
    check_gate_key,
    check_vault_key,
    load_policy,
    load_settings,
)
from cleargate.core.errors import ClearGateError

Check = tuple[str, bool, str]


def load_env_file(path: Path) -> None:
    """Minimal KEY=VALUE reader. Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def check_python() -> Check:
    v = sys.version_info
    return ("python>=3.12", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}")


def check_tesseract(cmd: str | None) -> Check:
    if not cmd:
        return ("tesseract>=5 with eng", False, "not found (set CLEARGATE_TESSERACT_CMD)")
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=30)
        langs = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ("tesseract>=5 with eng", False, type(exc).__name__)
    match = re.search(r"tesseract v?(\d+)\.(\d+)\.(\d+)", out.stdout + out.stderr)
    if not match:
        return ("tesseract>=5 with eng", False, "version not recognised")
    version = ".".join(match.groups())
    has_eng = "eng" in (langs.stdout + langs.stderr).split()
    ok = int(match.group(1)) >= 5 and has_eng
    return ("tesseract>=5 with eng", ok, f"{version}, eng={'yes' if has_eng else 'no'}")


def check_spacy_model(name: str) -> Check:
    try:
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return (f"spacy model {name}", False, "not installed (python -m spacy download)")
    spacy_version = importlib.metadata.version("spacy")
    return (f"spacy model {name}", True, f"{version} (spacy {spacy_version})")


def check_face_cascades() -> Check:
    try:
        import cv2
    except ImportError:
        return ("opencv face cascades", False, "opencv not installed")
    base = Path(cv2.data.haarcascades)
    wanted = ["haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"]
    missing = [w for w in wanted if not (base / w).is_file()]
    return ("opencv face cascades", not missing, f"opencv {cv2.__version__}, missing={missing}")


def check_data_dir(path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, delete=True) as fh:
            fh.write(b"ok")
    except OSError as exc:
        return ("data dir writable", False, f"{path} ({type(exc).__name__})")
    return ("data dir writable", True, str(path))


def check_key(name: str, fn: Callable[[], None]) -> Check:
    try:
        fn()
    except ClearGateError as exc:
        return (name, False, exc.code.value)
    return (name, True, "set, valid")


def run_checks() -> list[Check]:
    settings = load_settings()
    policy = load_policy(settings.policy_path)
    return [
        check_python(),
        check_tesseract(settings.tesseract_cmd),
        check_spacy_model(policy.detection.ner_model),
        check_face_cascades(),
        check_data_dir(settings.data_dir),
        check_key("CLEARGATE_VAULT_KEY", lambda: check_vault_key(settings.vault_key)),
        check_key("CLEARGATE_GATE_KEY", lambda: check_gate_key(settings.gate_key)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", type=Path)
    args = parser.parse_args(argv)
    load_env_file(args.env_file)
    checks = run_checks()
    width = max(len(c[0]) for c in checks)
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    failed = sum(1 for c in checks if not c[1])
    print(f"doctor: {len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
