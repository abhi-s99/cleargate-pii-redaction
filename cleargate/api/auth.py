"""Bearer-token roles: submitter and reviewer (TR-SEC-05, ADR-12).

Static tokens from ``CLEARGATE_SUBMITTER_TOKEN`` and ``CLEARGATE_REVIEWER_TOKEN`` (a
documented prototype limit, TR-SEC-09). The reviewer token also has submitter rights.
Comparison is constant-time. Without configured tokens every protected call is refused.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, Request

from cleargate.api.service import ApiError

Role = Literal["submitter", "reviewer"]


@dataclass(frozen=True)
class Principal:
    role: Role
    subject: str  # a non-secret label for the audit trail


def _match(given: str, expected: object) -> bool:
    if expected is None:
        return False
    secret = expected.get_secret_value()  # type: ignore[attr-defined]
    return bool(secret) and hmac.compare_digest(given.encode(), secret.encode())


def principal(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    settings = request.app.state.settings
    if settings.submitter_token is None and settings.reviewer_token is None:
        raise ApiError(503, "AUTH_NOT_CONFIGURED", "No API tokens are configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "UNAUTHORIZED", "Bearer token is missing or invalid")
    token = authorization.removeprefix("Bearer ").strip()
    if _match(token, settings.reviewer_token):
        return Principal("reviewer", "reviewer")
    if _match(token, settings.submitter_token):
        return Principal("submitter", "submitter")
    raise ApiError(401, "UNAUTHORIZED", "Bearer token is missing or invalid")


def require_reviewer(p: Principal) -> Principal:
    if p.role != "reviewer":
        raise ApiError(403, "FORBIDDEN_REVIEWER_REQUIRED", "This action requires the reviewer role")
    return p


PrincipalDep = Annotated[Principal, Depends(principal)]
