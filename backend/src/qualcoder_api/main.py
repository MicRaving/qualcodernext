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
from qualcoder_api.services import sync, sync_engine, user_settings
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
    can actually read it (see ``_cors_headers``). Only the exception type is
    returned; the message (which may contain paths/SQL) stays server-side."""
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    detail = f"internal error: {type(exc).__name__}"
    return JSONResponse(status_code=500, content={"detail": detail}, headers=_cors_headers(request))


async def _sync_loop() -> None:
    """Collaboration sync: while the per-machine switch is on, export local
    changes and import other instances' sidecar files on a configurable
    cadence (default 60s; see Settings → the sync interval dropdown). The
    interval is re-read each tick so a settings change takes effect without
    restarting the loop."""

    while True:
        await asyncio.sleep(user_settings.get_sync_interval_secs())
        if not sync.sync_enabled():
            continue
        if service.project_path and service.session_factory:
            try:
                # Prefer per-session replay files when in a session (new spec 2a),
                # fall back to legacy per-instance sidecars for old projects.
                sync_id = getattr(service, "current_session_id", "") or user_settings.get_instance_id()
                cycle_result = await sync_engine.run_sync_cycle(
                    service.session_factory, service.project_path,
                    sync_id,
                )
                # The admin merge below must only run on a clean cycle: with
                # failed imports it would snapshot an incomplete sandbox while
                # deleting the unimported replays (unrecoverable shared loss).
                cycle_clean = bool(cycle_result.get("ok")) and not cycle_result.get("deferred")
                if cycle_clean:
                    for report in (cycle_result.get("imported") or {}).values():
                        if isinstance(report, dict) and report.get("retries"):
                            cycle_clean = False
                            break
                # After a successful sync, ack any newly imported replays (spec 2e)
                # and heartbeat the session.
                if getattr(service, "current_session_id", ""):
                    try:
                        from qualcoder_api.services import replay_service

                        # Ack per-session replays that are not our own and not yet
                        # acked (import_pending already acks on a real import; this
                        # covers replays that existed with no new entries).  Legacy
                        # changes/<instance> sidecars are acked by import_pending
                        # with the instance id — their file stem ("changes") is not
                        # a replay id, so they are skipped here.
                        for rp in replay_service.list_session_replays(service.project_path):
                            if rp.stem == sync_id:
                                continue
                            if not replay_service.has_acked(service.project_path, rp.stem, sync_id):
                                replay_service.write_ack(service.project_path, rp.stem, sync_id)
                    except Exception:
                        pass
                    # Admin merge (spec 2c): when every other session is closed or
                    # stale, snapshot the sandbox into the master archive so a
                    # crashed instance's changes still land.  No-op while another
                    # session is active or the cycle above did not complete.
                    with _contextlib.suppress(Exception):
                        await service._maybe_merge_master(
                            service.current_session_id, cycle_clean
                        )
                    with _contextlib.suppress(Exception):
                        service.heartbeat_session()
            except Exception as err:  # pragma: no cover - defensive
                logger.exception("background sync cycle failed: %s", err)


async def _presence_loop() -> None:
    """Live coder presence: while a project is open, refresh this instance's
    presence file so other instances see it as active (independent of the sync
    switch). The frontend reports the current file via the activity endpoint."""
    from qualcoder_api.services import presence_service

    while True:
        await asyncio.sleep(presence_service.PRESENCE_HEARTBEAT_SECS)
        if not service.project_path:
            continue
        try:
            presence_service.touch(
                service.project_path,
                user_settings.get_codername(),
                file_id=service.current_source_id,
                file_name=service.current_source_name,
                instance_id=user_settings.get_instance_id(),
            )
            # Per-session heartbeat (spec 2b)
            with _contextlib.suppress(Exception):
                service.heartbeat_session()
        except Exception as err:  # pragma: no cover - defensive
            logger.exception("presence heartbeat failed: %s", err)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Server mode (SERVER_PLAN.md Phase 0): no local-project singleton loops.
    # The sync/presence loops manage the LOCAL app's open project and are
    # meaningless on a multi-tenant server; server sessions get their own
    # lifecycle in later phases.
    from qualcoder_api.core.server_config import (
        is_server_mode,
        load_server_config,
        validate_server_config,
    )

    server_mode = is_server_mode()
    tasks: list[asyncio.Task] = []
    if server_mode:
        validate_server_config(load_server_config())
        from qualcoder_api.persistence import metadata_db

        await metadata_db.migrate_metadata(load_server_config().metadata_db)

        async def _idle_session_reaper() -> None:
            while True:
                await asyncio.sleep(60)
                from qualcoder_api.services.session_manager import manager

                await manager.release_idle()

        async def _backup_sweep() -> None:
            # Hourly: snapshot projects lacking a fresh (<24h) backup, then
            # prune per QC_BACKUP_RETENTION.
            while True:
                await asyncio.sleep(3600)
                from qualcoder_api.services import backup_service

                try:
                    await backup_service.run_all_scheduled()
                    await backup_service.apply_retention()
                except Exception:
                    logger.exception("backup sweep failed")

        tasks.append(asyncio.create_task(_idle_session_reaper()))
        tasks.append(asyncio.create_task(_backup_sweep()))
    else:
        tasks.append(asyncio.create_task(_sync_loop()))
        tasks.append(asyncio.create_task(_presence_loop()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with _contextlib.suppress(asyncio.CancelledError):
                await task
        if not server_mode:
            await service.close_project()
        else:
            await metadata_db.dispose_metadata_engine()


def create_app() -> FastAPI:
    from qualcoder_api.core import APP_VERSION

    app = FastAPI(
        title="QualCoder v4 API",
        version=APP_VERSION,
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
    from qualcoder_api.core.server_config import is_server_mode

    if is_server_mode():
        from fastapi import Depends

        from qualcoder_api.api.v1.auth import router as auth_router
        from qualcoder_api.api.v1.auth_deps import gate_project_scoped
        from qualcoder_api.api.v1.server_backups import router as server_backups_router
        from qualcoder_api.api.v1.server_projects import router as server_projects_router
        from qualcoder_api.api.v1.server_sync import router as server_sync_router

        app.include_router(auth_router, prefix="/api/v1")
        app.include_router(server_projects_router, prefix="/api/v1")
        app.include_router(server_backups_router, prefix="/api/v1")
        # Sync hub: project-scoped (X-Project-Id gate; viewers read-only).
        app.include_router(
            server_sync_router,
            prefix="/api/v1",
            dependencies=[Depends(gate_project_scoped)],
        )
    return app


app = create_app()
