"""QualCoder v4 backend — FastAPI application factory.

Run: ``python -m uvicorn qualcoder_api.main:app --port 8765``
"""

from __future__ import annotations

import asyncio
import contextlib as _contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from qualcoder_api.api.v1.router import router as v1_router
from qualcoder_api.services import sync, user_settings
from qualcoder_api.services.project_service import ProjectService

logger = logging.getLogger(__name__)

service = ProjectService()


async def _sync_loop() -> None:
    """Collaboration sync: export local changes and import other raters'
    sidecar files every ``SYNC_INTERVAL_SECS`` while a project is open."""
    while True:
        await asyncio.sleep(sync.SYNC_INTERVAL_SECS)
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
        allow_origins=[
            "http://localhost:5173",
            # Tauri 2 serves the bundled frontend from http://tauri.localhost
            # (Tauri 1 used tauri://localhost) — both must be allowed or every
            # API call from the packaged app is CORS-blocked.
            "http://tauri.localhost",
            "tauri://localhost",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
