"""POST /batches (upload, synchronous validation) and DELETE /batches/{id} (TRD 10, FR-02)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from starlette.datastructures import UploadFile

from cleargate.api.auth import PrincipalDep
from cleargate.api.service import ApiError

router = APIRouter()


@router.post("/batches")
async def create_batch(request: Request, p: PrincipalDep) -> dict[str, Any]:
    form = await request.form()
    files = [
        f for key in ("files[]", "files") for f in form.getlist(key) if isinstance(f, UploadFile)
    ]
    policy = form.get("policy")
    if (
        isinstance(policy, str)
        and policy.strip()
        and policy.strip() != request.app.state.policy.policy_name
    ):
        raise ApiError(400, "CONFIG_NOT_FOUND", "Only the configured policy is available")
    uploads = [(f.filename or "upload", await f.read()) for f in files]
    return request.app.state.service.submit(uploads)


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str, request: Request, p: PrincipalDep) -> dict[str, Any]:
    return request.app.state.service.delete_batch(batch_id)
