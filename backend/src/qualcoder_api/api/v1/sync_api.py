"""Sync API — collaboration toggle, status and manual sync trigger.

Option B: change-log sidecars exchanged via folder-sync tools (Nextcloud,
Sync&Share, Syncthing). The backend exports local changes as JSONL files
under ``<project>/changes/<user>/`` and imports/replays other raters'
files on a 60-second cycle (see ``services/sync``). The cycle only runs
while the per-machine sync switch is enabled.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import ServiceDep
from qualcoder_api.services import sync, user_settings

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncSettingsRequest(BaseModel):
    enabled: bool


@router.get("/settings")
async def get_sync_settings() -> dict:
    """The per-machine sync switch state."""
    return user_settings.get_sync_settings()


@router.put("/settings")
async def put_sync_settings(req: SyncSettingsRequest, svc: ServiceDep) -> dict:
    """Turn the background sync cycle on/off for this machine. Enabling runs
    an immediate cycle when a project is open."""
    saved = user_settings.save_sync_settings(req.enabled)
    if req.enabled and svc.project_path and svc.session_factory:
        import asyncio

        asyncio.get_running_loop().create_task(
            sync.run_sync_cycle(
                svc.session_factory, svc.project_path, user_settings.get_codername()
            )
        )
    return saved


@router.get("/status")
async def sync_status(svc: ServiceDep) -> dict:
    """Pending outbound changes, pending inbound changes, the other raters
    seen in the project's ``changes/`` folder, and the sync switch state."""
    if svc.project_path == "" or svc.session_factory is None:
        return {"ok": False, "reason": "no project open"}
    return await sync.sync_status(
        svc.session_factory, svc.project_path, user_settings.get_codername()
    )


@router.post("/now")
async def sync_now(svc: ServiceDep) -> dict:
    """Run one export + import cycle immediately."""
    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    return await sync.run_sync_cycle(
        svc.session_factory, svc.project_path, user_settings.get_codername()
    )
