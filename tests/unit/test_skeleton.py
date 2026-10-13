"""The package layout matches TRD section 3 and every module imports."""

from __future__ import annotations

import importlib

import pytest

TRD_MODULES = [
    "cleargate.core.models",
    "cleargate.core.states",
    "cleargate.core.config",
    "cleargate.core.errors",
    "cleargate.ingest.validator",
    *(
        f"cleargate.extract.{m}"
        for m in ("base", "pdf", "docx", "pptx", "image", "ocr", "metadata")
    ),
    "cleargate.detect.engine",
    *(
        f"cleargate.detect.recognizers.{m}"
        for m in ("deterministic", "label_anchored", "context", "phone")
    ),
    *(
        f"cleargate.detect.{m}"
        for m in ("ner", "presplit", "registry", "propagate", "allowlist", "merge")
    ),
    *(f"cleargate.redact.{m}" for m in ("tokens", "vault", "text_renderer")),
    *(f"cleargate.redact.writers.{m}" for m in ("pdf", "docx", "pptx", "image")),
    *(f"cleargate.verify.{m}" for m in ("reextract", "leak", "residual", "coverage", "structure")),
    *(f"cleargate.gate.{m}" for m in ("machine", "rules", "handle", "handoff")),
    "cleargate.report.builder",
    "cleargate.api.main",
    "cleargate.api.auth",
    "cleargate.api.routes",
    "cleargate.ui.app",
    "cleargate.pipeline",
    "eval.run_eval",
    "eval.metrics",
]


@pytest.mark.parametrize("name", TRD_MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(name).__doc__


def test_job_states_match_trd() -> None:
    from cleargate.core.states import TERMINAL_STATES, JobState

    assert {s.value for s in JobState} == {
        "RECEIVED",
        "PROCESSING",
        "FAILED",
        "BLOCKED",
        "REVIEW_REQUIRED",
        "VALIDATED_SAFE",
    }
    assert JobState.REVIEW_REQUIRED not in TERMINAL_STATES
