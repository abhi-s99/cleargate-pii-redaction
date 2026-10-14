"""AI handoff via SafeHandle, MockAgent by default (TR-GT-04, TR-GT-05, FR-14, ADR-09).

``AIHandoff.send`` accepts only a ``SafeHandle``. It verifies the HMAC, re-hashes the
sanitized text on disk, checks the job is still ``VALIDATED_SAFE`` under the same policy
(``verify_against_store``), and only then reads the sanitized text and passes it to the
agent. No other text, path or vault value has a code path to the agent.

``MockAgent`` is local and deterministic: an extractive summary (headings and the first
sentences) plus counts of each ClearGate token type, so a demo shows the AI reasoning over
sanitized text. A real LLM client is not shipped: ``llm.enabled`` requires an explicit
approval in the policy, and even then this prototype refuses (no network, TR-SEC-01).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr

from cleargate.core.config import Policy
from cleargate.core.db import MetaStore
from cleargate.core.errors import ErrorCode, HandoffRefused
from cleargate.gate.handle import SafeHandle, verify_against_store

TOKEN = re.compile(r"\[([A-Z][A-Z_]*?)(?:_\d+)?\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class AgentResult:
    agent: str
    summary: str
    token_counts: dict[str, int]
    characters: int


class MockAgent:
    name = "mock-agent"
    version = "0.8.0"

    def analyse(self, text: str, max_sentences: int = 6) -> AgentResult:
        headings = [ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")]
        body = " ".join(
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and not ln.startswith(("#", "[", "|"))
        )
        sentences = [s for s in SENTENCE.split(body) if len(s.split()) >= 4][:max_sentences]
        counts = Counter(
            m.group(1) for m in TOKEN.finditer(text) if m.group(1) not in ("Page", "Slide")
        )
        lines = []
        if headings:
            lines.append("Sections: " + "; ".join(headings[:8]))
        if sentences:
            lines.append("Key points: " + " ".join(sentences))
        if counts:
            lines.append(
                "Personal data seen only as tokens: "
                + ", ".join(f"{k} x{v}" for k, v in sorted(counts.items()))
            )
        return AgentResult(self.name, "\n".join(lines) or "No content.", dict(counts), len(text))


class AIHandoff:
    def __init__(self, store: MetaStore, gate_key: SecretStr, policy: Policy) -> None:
        self.store = store
        self.gate_key = gate_key
        self.policy = policy
        self.agent = MockAgent()

    def send(self, handle: SafeHandle, sanitized_path: Path) -> AgentResult:
        verify_against_store(self.store, handle, self.gate_key, sanitized_path)
        if self.policy.llm.enabled:
            # The policy may approve an LLM; this prototype has no client for it.
            raise HandoffRefused(
                ErrorCode.HANDOFF_REFUSED, job_id=handle.job_id, reason="llm_client_not_available"
            )
        return self.agent.analyse(sanitized_path.read_text(encoding="utf-8"))
