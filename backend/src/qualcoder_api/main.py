"""QualCoder v4 backend — FastAPI application factory.

Run: ``python -m uvicorn qualcoder_api.main:app --port 8765``
"""

from __future__ import annotations

import asyncio
import contextlib as _contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from qualcoder_api.api.v1.router import router as v1_router
from qualcoder_api.services import sync, user_settings
from qualcoder_api.services.project_service import ProjectService

logger = logging.getLogger(__name__)

service = ProjectService()

#: Origins the CORSMiddleware allows. The catch-all 500 handler mirrors
#: this list so its responses carry the same CORS headers.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    # Tauri 2 serves the bundled frontend from http://tauri.localhost
    # (Tauri 1 used tauri://localhost) — both must be allowed or every
    # API call from the packaged app is CORS-blocked.
    "http://tauri.localhost",
    "tauri://localhost",
]


def _cors_headers(request: Request) -> dict[str, str]:
    """Echo the CORS headers CORSMiddleware would add on a normal response.

    Starlette's ServerErrorMiddleware sits OUTSIDE the CORSMiddleware, so
    the 500 it produces for an unhandled exception never flows through the
    CORS middleware's header injection. The browser then cannot read the
    JSON error body and reports a bare "Failed to fetch" — which looks like
    a network failure instead of the real backend error.
    """
    origin = request.headers.get("origin")
    if origin in ALLOWED_ORIGINS:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}


def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for any unhandled exception: a readable JSON 500 instead
    of the plain-text default — with CORS headers so the packaged webview
    can actually read it (see ``_cors_headers``). The exception type and a
    sanitized (truncated, single-line) message keep the body debuggable
    without leaking full tracebacks to the client."""
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    message = str(exc).strip().replace("\n", " ")[:500]
    detail = f"internal error: {type(exc).__name__}"
    if message:
        detail += f": {message}"
    return JSONResponse(status_code=500, content={"detail": detail}, headers=_cors_headers(request))


async def _sync_loop() -> None:
    """Collaboration sync: while the per-machine switch is on, export local
    changes and import other raters' sidecar files every ``SYNC_INTERVAL_SECS``."""
    while True:
        await asyncio.sleep(sync.SYNC_INTERVAL_SECS)
        if not sync.sync_enabled():
            continue
        if service.project_path and service.session_factory:
            try:
                await sync.run_sync_cycle(
                    service.session_factory, service.project_path,
                    user_settings.get_codername(),
                )
            except Exception as err:  # pragma: no cover - defensive
                logger.exception("background sync cycle failed: %s", err)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_sync_loop())
    try:
        yield
    finally:
        task.cancel()
        with _contextlib.suppress(asyncio.CancelledError):
            await task
        await service.close_project()


def create_app() -> FastAPI:
    app = FastAPI(
        title="QualCoder v4 API",
        version="4.0.0",
        description="Backend for the QualCoder qualitative data analysis app.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
