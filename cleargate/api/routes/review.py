"""Review queue and decisions (TR-RV-01..04, FR-12). Reviewer role only."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request

from cleargate.api.auth import PrincipalDep, require_reviewer
from cleargate.api.service import ApiError, clean

router = APIRouter()


@router.get("/jobs/{job_id}/review")
def review_items(job_id: str, request: Request, p: PrincipalDep) -> list[dict[str, Any]]:
    require_reviewer(p)
    return clean(request.app.state.service.review_items(job_id))


@router.post("/jobs/{job_id}/review")
def submit_review(
    job_id: str,
    request: Request,
    payload: Annotated[dict[str, Any], Body()],
    p: PrincipalDep,
) -> dict[str, Any]:
    require_reviewer(p)
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not all(isinstance(d, dict) for d in decisions):
        raise ApiError(422, "BAD_PAYLOAD", "Expected {decisions: [...]}")
    return request.app.state.service.apply_review(job_id, decisions, p.subject)
