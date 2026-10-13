"""SafeHandle mint and verify (TR-GT-03, TR-GT-04 checks, ADR-09).

A SafeHandle is ``{job_id, sanitized_sha256, policy_hash, verification_sha256,
issued_at}`` plus ``HMAC-SHA256(gate_key, canonical_json(fields))``. It is minted
only by ``gate.machine.decide`` on the transition into ``VALIDATED_SAFE``.

``verify_handle`` checks the MAC and re-hashes the sanitized file on disk, so
neither a field nor the content can change after validation.
``verify_against_store`` adds the state checks the handoff needs: the job is
still ``VALIDATED_SAFE``, under the same policy, and this exact handle was the
one issued. Every failure raises ``HandleError`` with a content-free reason.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

from cleargate.core.config import canonical_json, check_gate_key
from cleargate.core.db import MetaStore
from cleargate.core.errors import ErrorCode, HandleError
from cleargate.core.models import VerificationReport
from cleargate.core.states import JobState

_CHUNK = 1 << 20


class SafeHandle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str
    sanitized_sha256: str
    policy_hash: str
    verification_sha256: str
    issued_at: str
    mac: str

    def signed_fields(self) -> dict[str, str]:
        return self.model_dump(exclude={"mac"})

    def to_json(self) -> str:
        return canonical_json(self.model_dump())

    @classmethod
    def from_json(cls, text: str) -> SafeHandle:
        return cls.model_validate_json(text)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verification_sha256(report: VerificationReport) -> str:
    return hashlib.sha256(canonical_json(report.model_dump(mode="json")).encode()).hexdigest()


def _mac(gate_key: SecretStr, fields: dict[str, str]) -> str:
    check_gate_key(gate_key)
    return hmac.new(
        gate_key.get_secret_value().encode(), canonical_json(fields).encode(), hashlib.sha256
    ).hexdigest()


def mint(
    gate_key: SecretStr,
    *,
    job_id: str,
    sanitized_path: Path,
    policy_hash: str,
    verification: VerificationReport,
    issued_at: str,
) -> SafeHandle:
    if not sanitized_path.is_file():
        raise HandleError(ErrorCode.HANDLE_INVALID, job_id=job_id, reason="sanitized_missing")
    fields = {
        "job_id": job_id,
        "sanitized_sha256": file_sha256(sanitized_path),
        "policy_hash": policy_hash,
        "verification_sha256": verification_sha256(verification),
        "issued_at": issued_at,
    }
    return SafeHandle(**fields, mac=_mac(gate_key, fields))


def verify_handle(handle: SafeHandle, gate_key: SecretStr, sanitized_path: Path) -> None:
    """MAC and content check. Raises ``HandleError``; returns None when valid."""
    expected = _mac(gate_key, handle.signed_fields())
    if not hmac.compare_digest(expected, handle.mac):
        raise HandleError(job_id=handle.job_id, reason="mac_mismatch")
    if not sanitized_path.is_file():
        raise HandleError(job_id=handle.job_id, reason="sanitized_missing")
    if not hmac.compare_digest(file_sha256(sanitized_path), handle.sanitized_sha256):
        raise HandleError(job_id=handle.job_id, reason="sanitized_changed")


def verify_against_store(
    store: MetaStore, handle: SafeHandle, gate_key: SecretStr, sanitized_path: Path
) -> None:
    """TR-GT-04 preconditions for a handoff (the AI call itself is Phase 8)."""
    verify_handle(handle, gate_key, sanitized_path)
    job = store.get_job(handle.job_id)
    if job is None:
        raise HandleError(job_id=handle.job_id, reason="job_unknown")
    if job["state"] != JobState.VALIDATED_SAFE.value:
        raise HandleError(job_id=handle.job_id, reason="job_not_safe")
    if job["policy_hash"] != handle.policy_hash:
        raise HandleError(job_id=handle.job_id, reason="policy_changed")
    issued = store.handle_json(handle.job_id)
    if issued is None or not hmac.compare_digest(issued, handle.to_json()):
        raise HandleError(job_id=handle.job_id, reason="not_issued")
