"""Pseudonym vault ``vault.db`` and encrypted job state (TR-RD-02, ADR-06, ADR-29).

* ``tokens`` rows: ``(batch_id, token, entity_type, value_hmac, value_ct, created_at)``;
  ``value_ct`` is the Fernet ciphertext of the raw value. The key comes from
  ``CLEARGATE_VAULT_KEY``; ``Vault`` refuses to open without a valid key.
* ``save_state`` / ``load_state``: the per-job detection state a review re-run needs
  (segment texts, finding values, residual hits). It is Fernet-encrypted with the same key
  and stored in the job directory, so it is deleted with the job (TTL, batch delete). This
  is the "encrypted vault" of TR-SEC-02 for job state; nothing raw reaches ``meta.db``.

Batch rows are deleted with the batch (TR-SEC-06).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from cleargate.core.config import check_vault_key
from cleargate.core.errors import ErrorCode, VaultError

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    batch_id    TEXT NOT NULL,
    token       TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    value_hmac  TEXT NOT NULL,
    person_key  TEXT,
    value_ct    BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (batch_id, entity_type, value_hmac)
);
CREATE INDEX IF NOT EXISTS tokens_by_token ON tokens (batch_id, token);
CREATE TABLE IF NOT EXISTS counters (
    batch_id TEXT NOT NULL,
    label    TEXT NOT NULL,
    n        INTEGER NOT NULL,
    PRIMARY KEY (batch_id, label)
);
"""
STATE_FILE = "state.enc"


class Vault:
    def __init__(self, path: Path, key: SecretStr | None) -> None:
        try:
            check_vault_key(key)
        except Exception:
            raise VaultError(ErrorCode.VAULT_UNAVAILABLE) from None
        assert key is not None
        self.fernet = Fernet(key.get_secret_value().encode())
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA busy_timeout = 5000")
            self.conn.executescript(SCHEMA)
        except sqlite3.Error:
            raise VaultError(ErrorCode.VAULT_UNAVAILABLE) from None
        self.lock = threading.Lock()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ tokens

    def get(self, batch_id: str, entity_type: str, value_hmac: str) -> str | None:
        row = self.conn.execute(
            "SELECT token FROM tokens WHERE batch_id = ? AND entity_type = ? AND value_hmac = ?",
            (batch_id, entity_type, value_hmac),
        ).fetchone()
        return str(row[0]) if row else None

    def person_token(self, batch_id: str, person_key: str) -> str | None:
        row = self.conn.execute(
            "SELECT token FROM tokens WHERE batch_id = ? AND person_key = ? LIMIT 1",
            (batch_id, person_key),
        ).fetchone()
        return str(row[0]) if row else None

    def next_number(self, batch_id: str, label: str) -> int:
        row = self.conn.execute(
            "SELECT n FROM counters WHERE batch_id = ? AND label = ?", (batch_id, label)
        ).fetchone()
        n = (row[0] if row else 0) + 1
        self.conn.execute(
            "INSERT INTO counters VALUES (?, ?, ?)"
            " ON CONFLICT(batch_id, label) DO UPDATE SET n = ?",
            (batch_id, label, n, n),
        )
        return n

    def put(
        self,
        batch_id: str,
        token: str,
        entity_type: str,
        value_hmac: str,
        value: str,
        person_key: str | None,
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO tokens VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                token,
                entity_type,
                value_hmac,
                person_key,
                self.fernet.encrypt(value.encode()),
                datetime.now(tz=UTC).isoformat(),
            ),
        )

    def entries(self, batch_id: str) -> dict[str, set[str]]:
        """token -> entity types it was issued for (V5)."""
        out: dict[str, set[str]] = {}
        for token, etype in self.conn.execute(
            "SELECT token, entity_type FROM tokens WHERE batch_id = ?", (batch_id,)
        ):
            out.setdefault(token, set()).add(etype)
        return out

    def person_tokens(self, batch_id: str) -> dict[str, set[str]]:
        """person_key -> tokens (V5: one token per person)."""
        out: dict[str, set[str]] = {}
        for pk, token in self.conn.execute(
            "SELECT person_key, token FROM tokens WHERE batch_id = ? AND person_key IS NOT NULL",
            (batch_id,),
        ):
            out.setdefault(pk, set()).add(token)
        return out

    def delete_batch(self, batch_id: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM tokens WHERE batch_id = ?", (batch_id,))
            self.conn.execute("DELETE FROM counters WHERE batch_id = ?", (batch_id,))

    # ------------------------------------------------------------------ job state

    def save_state(self, job_dir: Path, state: dict[str, Any]) -> None:
        data = self.fernet.encrypt(json.dumps(state, separators=(",", ":")).encode())
        tmp = job_dir / (STATE_FILE + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(job_dir / STATE_FILE)

    def load_state(self, job_dir: Path) -> dict[str, Any]:
        try:
            raw = self.fernet.decrypt((job_dir / STATE_FILE).read_bytes())
        except (OSError, InvalidToken):
            raise VaultError(ErrorCode.VAULT_UNAVAILABLE) from None
        state: dict[str, Any] = json.loads(raw)
        return state
