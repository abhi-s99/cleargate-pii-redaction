"""Worker memory limit (TR-SEC-07, ADR-34)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from cleargate.core.config import load_settings
from cleargate.core.limits import enforced, limit_memory


def test_setting_defaults_and_env_override() -> None:
    assert load_settings({}).worker_mem_mb == 6144
    assert load_settings({"CLEARGATE_WORKER_MEM_MB": "512"}).worker_mem_mb == 512
    assert load_settings({"CLEARGATE_WORKER_MEM_MB": "x"}).worker_mem_mb == 6144


def test_zero_disables_the_limit() -> None:
    assert limit_memory(0) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows behaviour")
def test_windows_is_a_documented_no_op() -> None:
    assert enforced() is False
    assert limit_memory(256) is False


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX only")
def test_allocation_beyond_the_limit_fails_in_the_worker() -> None:
    code = (
        "from cleargate.core.limits import limit_memory\n"
        "assert limit_memory(256)\n"
        "try:\n"
        "    b = bytearray(1024 * 1024 * 1024)\n"
        "except MemoryError:\n"
        "    raise SystemExit(3)\n"
        "raise SystemExit(0)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], check=False)
    assert r.returncode == 3
