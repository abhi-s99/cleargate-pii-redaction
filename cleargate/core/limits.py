"""Worker memory limit (TR-SEC-07, ADR-34).

``limit_memory(mb)`` sets ``RLIMIT_AS`` for the calling process on POSIX, so a parser or
OCR bomb in an OCR worker ends in ``MemoryError`` (or the worker dying) instead of
exhausting the host; Tesseract child processes inherit the limit. A broken worker pool
fails the job (``FAILED``), never a silent pass. On Windows ``resource`` does not exist:
the call is a no-op that returns ``False`` and the Docker image provides the limit.
"""

from __future__ import annotations

import sys


def limit_memory(mb: int) -> bool:
    """Apply an address-space limit of ``mb`` MiB; ``False`` when unsupported or off."""
    if mb <= 0 or sys.platform == "win32":
        return False
    import resource  # POSIX only

    limit = mb * 1024 * 1024
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    return True


def enforced() -> bool:
    """Whether this platform can enforce the worker memory limit."""
    return sys.platform != "win32"
