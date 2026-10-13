"""Batch-scoped typed tokens (TR-RD-01, ADR-06, FR-08).

``TokenService.lookup_or_create(batch_id, entity_type, value_hmac, person_key, value)``:

* the same ``(batch, type, value_hmac)`` always gets the same token;
* PERSON findings are keyed by ``person_key`` first, so ``P. Halvorsen``, ``Priya
  Halvorsen`` and the OCR-mangled mention share one ``[PERSON_n]``;
* counters are per ``(batch, token label)`` and numbers follow first occurrence: callers
  assign tokens in reading order of the batch (documents in upload order);
* ``token_style``: ``typed_numbered`` (default: MEDIUM-risk types numbered, HIGH-risk
  identifiers un-numbered, TRD 4.1), ``typed`` (never numbered), ``fixed`` (``[REDACTED]``).

Region types (PHOTO, UNREADABLE_IMAGE_REGION) are masked, not tokenised.
"""

from __future__ import annotations

from cleargate.core.models import DEFAULT_RISK, TOKEN_LABEL, EntityType, Finding
from cleargate.redact.vault import Vault

FIXED = "[REDACTED]"


class TokenService:
    def __init__(self, vault: Vault, style: str = "typed_numbered") -> None:
        self.vault = vault
        self.style = style

    def lookup_or_create(
        self,
        batch_id: str,
        entity_type: EntityType,
        value_hmac: str,
        person_key: str | None,
        value: str,
    ) -> str | None:
        label = TOKEN_LABEL[entity_type]
        if label is None:
            return None
        with self.vault.lock:
            existing = self.vault.get(batch_id, entity_type.value, value_hmac)
            if existing is None and entity_type is EntityType.PERSON and person_key:
                existing = self.vault.person_token(batch_id, person_key)
            token = existing or self._new(batch_id, entity_type, label)
            self.vault.put(batch_id, token, entity_type.value, value_hmac, value, person_key)
        return token

    def _new(self, batch_id: str, entity_type: EntityType, label: str) -> str:
        if self.style == "fixed":
            return FIXED
        numbered = self.style == "typed_numbered" and DEFAULT_RISK[entity_type] != "HIGH"
        if not numbered:
            return f"[{label}]"
        return f"[{label}_{self.vault.next_number(batch_id, label)}]"

    def assign(self, batch_id: str, findings: list[Finding]) -> list[Finding]:
        """Tokens for every finding the writers apply, in the given (reading) order."""
        out = []
        for f in findings:
            if f.decision in ("auto_redact", "review") and f.token is None:
                token = self.lookup_or_create(
                    batch_id, f.entity_type, f.value_hmac, f.person_key, f.value
                )
                f = f.model_copy(update={"token": token})  # model_copy keeps the raw value
            out.append(f)
        return out
