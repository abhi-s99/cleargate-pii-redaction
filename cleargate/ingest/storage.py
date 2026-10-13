"""Job directories and upload storage (TR-SEC-04, ADR-11, ADR-25).

* Job directories live under ``<data_dir>/jobs/<job_id>`` and are restricted to the
  service user: mode ``0700`` on POSIX; on Windows an ACL with inheritance removed
  and full control for the current user only (``icacls``), because ``chmod`` there
  only toggles the read-only flag.
* The upload is written once, with ``O_CREAT | O_EXCL``, as ``original.<ext>``; the
  user-supplied name is never used as a path.
* ``sanitize_display_name`` keeps a short, printable basename for reports.
"""

from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

from cleargate.core.errors import ClearGateError, ErrorCode

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_DISPLAY_NAME = 120


def sanitize_display_name(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFC", base)
    base = _CONTROL.sub("", base).strip().strip(".")
    base = re.sub(r"\s+", " ", base)
    if len(base) > MAX_DISPLAY_NAME:
        _, dot, ext = base.rpartition(".")
        keep = ("." + ext) if dot and len(ext) <= 8 else ""
        base = base[: MAX_DISPLAY_NAME - len(keep)] + keep
    return base or "upload"


def secure_dir(path: Path) -> None:
    """Restrict ``path`` to the current user."""
    if sys.platform == "win32":
        domain = os.environ.get("USERDOMAIN", "")
        user = f"{domain}\\{getpass.getuser()}" if domain else getpass.getuser()
        result = subprocess.run(  # noqa: S603
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ClearGateError(ErrorCode.INTERNAL, stage="secure_dir")
    else:
        path.chmod(0o700)


def job_dir(data_dir: Path, job_id: str) -> Path:
    if not _JOB_ID.match(job_id):
        raise ClearGateError(ErrorCode.INTERNAL, stage="job_id")
    jobs = data_dir / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    path = jobs / job_id
    path.mkdir(exist_ok=False)
    secure_dir(path)
    return path


def store_upload(src: Path, dest_dir: Path, ext: str) -> Path:
    """Copy ``src`` into ``dest_dir/original<ext>``; refuses to overwrite."""
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", ext):
        ext = ".bin"
    dest = dest_dir / f"original{ext}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(dest, flags, 0o600)
    with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
        shutil.copyfileobj(inp, out, 1 << 20)
    return dest


def remove_job_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
