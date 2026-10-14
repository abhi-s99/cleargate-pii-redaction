"""FastAPI application (TRD 10, ADR-12, ADR-31).

``create_app`` refuses to start without the vault and gate keys (TR-RD-02, TR-GT-03),
mounts the API under ``/api/v1``, maps every error to the single TRD 10 error schema with
content-free messages, warms the NER model in the background (``/health`` reports it),
runs the TTL sweeper (TR-SEC-06) and, when the React build exists (``cleargate-ui/dist``),
serves it on the same origin so the browser talks only to this process.

Run: ``python -m cleargate.cli serve`` (or ``make run``).
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from cleargate.api.routes import batches, health, jobs, review
from cleargate.api.service import ApiError, ClearGateService
from cleargate.core.config import (
    REPO_ROOT,
    Policy,
    Settings,
    check_gate_key,
    check_vault_key,
    load_env_file,
    load_policy,
    load_settings,
)
from cleargate.core.errors import ClearGateError, ErrorCode
from cleargate.core.logging import get_logger

log = get_logger(__name__)
API = "/api/v1"
UI_DIST = REPO_ROOT / "cleargate-ui" / "dist"
SWEEP_SECONDS = 600


def _error(status: int, code: str, message: str, job_id: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if job_id:
        body["job_id"] = job_id
    return JSONResponse({"error": body}, status_code=status)


def create_app(
    settings: Settings | None = None,
    policy: Policy | None = None,
    *,
    background: bool = True,
    ui_dir: Path | None = UI_DIST,
) -> FastAPI:
    if settings is None:
        load_env_file(REPO_ROOT / ".env")
        settings = load_settings()
    check_vault_key(settings.vault_key)
    check_gate_key(settings.gate_key)
    policy = policy or load_policy(settings.policy_path)
    service = ClearGateService(settings, policy)
    stop = threading.Event()

    def warm() -> None:
        try:
            from cleargate.detect.lexicon import common_words
            from cleargate.detect.ner import analyzer

            analyzer(policy.detection.ner_model)
            common_words(policy.detection.ner_model)
        except ClearGateError:
            log.error("NER model could not be loaded")

    def sweeper() -> None:
        while not stop.wait(SWEEP_SECONDS):
            try:
                service.sweep()
            except Exception:
                log.warning("TTL sweep failed", exc_info=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if background:
            threading.Thread(target=warm, name="ner-warmup", daemon=True).start()
            threading.Thread(target=sweeper, name="ttl-sweeper", daemon=True).start()
        yield
        stop.set()
        service.shutdown()

    app = FastAPI(
        title="ClearGate",
        version="0.8.0",
        lifespan=lifespan,
        docs_url=f"{API}/docs",
        openapi_url=f"{API}/openapi.json",
    )
    app.state.settings = settings
    app.state.policy = policy
    app.state.service = service

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message, exc.job_id)

    @app.exception_handler(ClearGateError)
    async def domain_error(_: Request, exc: ClearGateError) -> JSONResponse:
        status = (
            409 if exc.code in (ErrorCode.ILLEGAL_TRANSITION, ErrorCode.HANDOFF_REFUSED) else 400
        )
        return _error(status, exc.code.value, exc.message, exc.job_id)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "BAD_REQUEST", "The request is not valid")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, f"HTTP_{exc.status_code}", "Request failed")

    @app.exception_handler(Exception)
    async def internal(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled API error", exc_info=True)
        return _error(500, "INTERNAL", "Internal error")

    for module in (health, batches, jobs, review):
        app.include_router(module.router, prefix=API)

    if ui_dir is not None and (ui_dir / "index.html").is_file():
        assets = ui_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")
        index = ui_dir / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise ApiError(404, "NOT_FOUND", "Unknown API route")
            candidate = (ui_dir / path).resolve()
            if path and candidate.is_file() and ui_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app
