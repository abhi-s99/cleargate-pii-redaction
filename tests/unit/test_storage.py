"""Job directories and upload storage (TR-SEC-04)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cleargate.core.errors import ClearGateError
from cleargate.ingest.storage import job_dir, sanitize_display_name, store_upload


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\Windows\\win.ini", "win.ini"),
        ("C:\\Users\\x\\Quarterly.docx", "Quarterly.docx"),
        ("a\x00b\x1fc.pdf", "abc.pdf"),
        ("  spaced   name.pptx ", "spaced name.pptx"),
        ("", "upload"),
        ("...", "upload"),
    ],
)
def test_display_names_are_sanitised(raw: str, expected: str) -> None:
    assert sanitize_display_name(raw) == expected


def test_long_names_keep_their_extension() -> None:
    name = sanitize_display_name("x" * 300 + ".docx")
    assert len(name) == 120
    assert name.endswith(".docx")


def test_upload_is_stored_as_original_with_o_excl(tmp_path: Path) -> None:
    src = tmp_path / "Board pack (final).docx"
    src.write_bytes(b"content")
    dest_dir = tmp_path / "job"
    dest_dir.mkdir()
    stored = store_upload(src, dest_dir, ".docx")
    assert stored.name == "original.docx"
    assert stored.read_bytes() == b"content"
    with pytest.raises(FileExistsError):
        store_upload(src, dest_dir, ".docx")


def test_weird_extension_falls_back_to_bin(tmp_path: Path) -> None:
    src = tmp_path / "x"
    src.write_bytes(b"1")
    assert store_upload(src, tmp_path, "./../evil").name == "original.bin"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "x" * 65, "job 1"])
def test_job_ids_cannot_escape_the_data_dir(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ClearGateError):
        job_dir(tmp_path, bad)


def test_job_dir_is_created_once_and_restricted(tmp_path: Path) -> None:
    path = job_dir(tmp_path, "job-abc")
    assert path == tmp_path / "jobs" / "job-abc"
    with pytest.raises(FileExistsError):
        job_dir(tmp_path, "job-abc")
    if sys.platform == "win32":
        acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True).stdout
        entries = [line for line in acl.splitlines() if ":(" in line]
        assert len(entries) == 1, acl  # only the current user, inheritance removed
        assert "(F)" in entries[0]
    else:
        assert path.stat().st_mode & 0o777 == 0o700
