"""QualCoder v4 backend — FastAPI application factory.

Run: ``python -m uvicorn qualcoder_api.main:app --port 8765``
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from qualcoder_api.api.v1.router import router as v1_router
from qualcoder_api.services.project_service import ProjectService

service = ProjectService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
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
