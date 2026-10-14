"""GET /health: liveness, model loaded, Tesseract version, keys present (TRD 10)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    from cleargate.core.config import policy_hash
    from cleargate.detect import lexicon
    from cleargate.extract.ocr import OcrEngine

    s = request.app.state.settings
    engine = OcrEngine(s.tesseract_cmd)
    from cleargate.api.service import clean

    return clean(
        {
            "status": "ok",
            "service": "cleargate",
            "model_loaded": bool(lexicon._NLP),
            "tesseract_version": engine.version if engine.available() else None,
            "vault_key_present": s.vault_key is not None,
            "gate_key_present": s.gate_key is not None,
            "policy": request.app.state.policy.policy_name,
            "policy_hash": policy_hash(request.app.state.policy),
            "llm_enabled": request.app.state.policy.llm.enabled,
        }
    )
