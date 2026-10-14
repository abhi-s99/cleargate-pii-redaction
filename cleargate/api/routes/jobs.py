"""Job status, findings, report, artifacts and handoff (TRD 10, FR-11, FR-13, FR-14, TR-SEC-05)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse

from cleargate.api.auth import PrincipalDep, require_reviewer
from cleargate.api.service import ApiError, clean

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, p: PrincipalDep) -> dict[str, Any]:
    return clean(request.app.state.service.job(job_id))


@router.get("/jobs/{job_id}/findings")
def get_findings(
    job_id: str, request: Request, p: PrincipalDep, include_text: bool = False
) -> list[dict[str, Any]]:
    if include_text:
        require_reviewer(p)  # raw segment text: reviewer only (TRD 10)
    return clean(request.app.state.service.findings(job_id, include_text))


@router.get("/jobs/{job_id}/report", response_model=None)
def get_report(job_id: str, request: Request, p: PrincipalDep, format: str = "json") -> Any:
    if format not in ("json", "md"):
        raise ApiError(400, "BAD_FORMAT", "format must be json or md")
    body = request.app.state.service.report(job_id, format)
    if format == "md":
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")
    return body


@router.get("/jobs/{job_id}/artifacts/{name}")
def get_artifact(job_id: str, name: str, request: Request, p: PrincipalDep) -> FileResponse:
    path, download = request.app.state.service.artifact(job_id, name)
    media = "text/plain; charset=utf-8" if name == "sanitized.txt" else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=download)


@router.post("/jobs/{job_id}/handoff")
def handoff(job_id: str, request: Request, p: PrincipalDep) -> dict[str, Any]:
    return clean(request.app.state.service.handoff(job_id))
