"""Sync API — collaboration status and manual sync trigger.

Option B: change-log sidecars exchanged via folder-sync tools (Nextcloud,
Sync&Share, Syncthing). The backend exports local changes as JSONL files
under ``<project>/changes/<user>/`` and imports/replays other raters'
files on a 60-second cycle (see ``services/sync``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from qualcoder_api.api.v1.deps import ServiceDep
from qualcoder_api.services import sync, user_settings

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status")
async def sync_status(svc: ServiceDep) -> dict:
    """Pending outbound changes, pending inbound changes and the other
    raters seen in the project's ``changes/`` folder."""
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
