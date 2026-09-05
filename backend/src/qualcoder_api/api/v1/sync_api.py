"""Sync API — collaboration toggle, status and manual sync trigger.

Versioned sidecars with in-app conflict resolution (Option C).  The backend
exports local changes as JSONL files under ``<project>/changes/<instance_id>/``
and imports/replays other instances' files on a 60-second cycle (see
``services.sync_engine``).  The cycle only runs while the per-machine sync
switch is enabled.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import OpenProjectDep, ServiceDep
from qualcoder_api.services import sync, sync_engine, user_settings

router = APIRouter(prefix="/sync", tags=["sync"])


def _sync_id(svc) -> str:
    """The active sync identity: the per-session id in collaboration mode
    (each open gets a fresh replay), falling back to the per-machine
    instance id for legacy/offline projects.  Every sync operation must use
    the SAME identity — mixing session and instance ids splits a machine's
    changes across two replay files with separate watermarks."""
    return getattr(svc, "current_session_id", "") or user_settings.get_instance_id()


class SyncSettingsRequest(BaseModel):
    enabled: bool
    interval_secs: int | None = None


class SyncOverrideRequest(BaseModel):
    project_path: str
    mode: str = "auto"


class PresenceActivityRequest(BaseModel):
    """The source this instance is currently working on (null = none)."""
    file_id: int | None = None
    file_name: str = ""


class ConflictResolutionRequest(BaseModel):
    conflict_id: int
    resolution: str  # "local" | "remote" | "merged"
    merged_row: dict | None = None


class ConflictResolveAllRequest(BaseModel):
    resolution: str  # "local" | "remote"


@router.get("/settings")
async def get_sync_settings() -> dict:
    """The per-machine sync switch state."""
    return user_settings.get_sync_settings()


@router.put("/settings")
async def put_sync_settings(req: SyncSettingsRequest, svc: ServiceDep) -> dict:
    """Turn the background sync cycle on/off for this machine (and/or change
    its cadence). Enabling runs an immediate cycle when a project is open."""
    import asyncio
    import logging as _logging

    before = user_settings.get_sync_settings().get("enabled", False)
    saved = user_settings.save_sync_settings(
        req.enabled, interval_secs=req.interval_secs
    )
    if req.enabled and svc.project_path and svc.session_factory:
        # First-sync baseline for NEW collaborators: a fresh instance must
        # adopt the shared project's current state as already-seen instead
        # of replaying the entire sidecar backlog (offline-backup freeze).
        # Keyed by the STABLE instance id — a per-session key would be a new
        # watermark on every enable and would wrongly suppress local changes
        # made between open and enable.
        _, factory = svc._ensure_engine()
        async with factory() as session:
            await sync_engine.baseline_first_sync(
                session, svc.project_path, user_settings.get_instance_id()
            )
        # Tracked background cycle: exceptions are logged (not silently
        # dropped) and overlap with the periodic loop is serialized by
        # SYNC_LOCK inside run_sync_cycle.
        async def _immediate() -> None:
            try:
                await sync_engine.run_sync_cycle(
                    svc.session_factory, svc.project_path,
                    _sync_id(svc),
                )
            except Exception as err:
                _logging.getLogger(__name__).exception("immediate sync cycle failed: %s", err)

        asyncio.get_running_loop().create_task(_immediate())
    # Record the toggle in the open project's history (best effort).
    if svc.engine is not None:
        from qualcoder_api.services import audit

        _, factory = svc._ensure_engine()
        async with factory() as session:
            await audit.record(
                session, user=user_settings.get_codername(), action="sync.toggle",
                entity="project", detail={"enabled": req.enabled, "before": before},
            )
    return saved


@router.get("/status")
async def sync_status(svc: ServiceDep) -> dict:
    """Pending outbound changes, pending inbound changes, the other instances
    seen in the project's ``changes/`` folder, and the sync switch state."""
    if svc.project_path == "" or svc.session_factory is None:
        return {"ok": False, "reason": "no project open"}
    return await sync_engine.sync_status(
        svc.session_factory, svc.project_path, _sync_id(svc)
    )


@router.get("/presence")
async def sync_presence(svc: ServiceDep) -> dict:
    """Live presence entries of OTHER instances on the open project — who is
    actively working and on which file (per-instance presence files)."""
    if svc.project_path == "":
        return {"ok": False, "reason": "no project open"}
    try:
        from qualcoder_api.services import presence_service

        # Return ALL entries (including this backend's own). The frontend
        # excludes the current coder by name so each instance sees "other
        # active coders" — this also provides file-indicator data for ALL
        # active coders (including self, used for the Sidebar highlight).
        presence = presence_service.read(svc.project_path, exclude_pid=None)
    except Exception as err:  # pragma: no cover - defensive
        return {"ok": False, "reason": str(err)}
    return {"ok": True, "presence": presence}


@router.post("/presence/activity")
async def sync_presence_activity(req: PresenceActivityRequest, svc: ServiceDep) -> dict:
    """Report the source this instance is currently working on (or that it
    left the coder view, ``file_id=null``). Broadcast to other instances via
    the presence files."""
    if svc.project_path == "":
        return {"ok": False, "reason": "no project open"}
    svc.set_current_source(req.file_id, req.file_name)
    try:
        from qualcoder_api.services import presence_service

        presence_service.touch(
            svc.project_path,
            user_settings.get_codername(),
            file_id=req.file_id,
            file_name=req.file_name,
            instance_id=user_settings.get_instance_id(),
        )
    except Exception as err:  # pragma: no cover - defensive
        return {"ok": False, "reason": str(err)}
    return {"ok": True}


@router.get("/auto-detect")
async def sync_auto_detect(project_path: str) -> dict:
    """Report whether a project path looks like a shared/synced folder
    (marker file, UNC path or change sidecars from other instances)."""
    from qualcoder_api.core.server_config import is_server_mode

    if is_server_mode():
        return {"shared": False, "reason": "local-folder detection disabled on server"}
    if not project_path or len(project_path) > 4096 or "\x00" in project_path:
        return {"shared": False, "reason": "invalid path"}
    return sync.detect_shared(
        project_path,
        user=user_settings.get_codername(),
        instance_id=user_settings.get_instance_id(),
    )


@router.put("/override")
async def put_sync_override(req: SyncOverrideRequest) -> dict:
    """Remember a per-project sync decision. A manual toggle ("on"/"off")
    wins over the auto-detection on the next project open; "auto" restores
    the re-detecting behaviour."""
    try:
        saved = user_settings.set_sync_override(req.project_path, req.mode)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"ok": True, "project_path": req.project_path, "mode": saved}


@router.post("/now")
async def sync_now(svc: OpenProjectDep) -> dict:
    """Run one export + import cycle immediately."""
    return await sync_engine.run_sync_cycle(
        svc.session_factory, svc.project_path, _sync_id(svc)
    )


@router.post("/repair")
async def sync_repair(svc: OpenProjectDep) -> dict:
    """Full repair sync: export pending, forget import watermarks, replay
    every sidecar, then publish a full-state snapshot.

    Idempotent (natural-key converge): heals rows missed by incremental
    cycles and publishes genuinely local-only rows, without duplicating
    anything.  Use when instances show different counts, or automatically
    after opening a collaboration project.
    """
    return await sync_engine.run_repair_cycle(
        svc.session_factory, svc.project_path, _sync_id(svc)
    )


@router.get("/conflicts")
async def list_conflicts(svc: ServiceDep) -> dict:
    """Unresolved conflicts with local + remote row snapshots."""
    if svc.project_path == "" or svc.session_factory is None:
        return {"ok": False, "reason": "no project open"}
    conflicts = await sync_engine.list_conflicts(svc.session_factory)
    return {"ok": True, "conflicts": conflicts}


@router.post("/conflicts/resolve")
async def resolve_conflict_endpoint(req: ConflictResolutionRequest, svc: OpenProjectDep) -> dict:
    """Resolve a conflict by choosing local, remote, or a merged version."""
    result = await sync_engine.resolve_conflict(
        svc.session_factory, svc.project_path,
        req.conflict_id, req.resolution, req.merged_row,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("reason", "resolution failed"))
    return result


@router.post("/conflicts/resolve-all")
async def resolve_all_conflicts_endpoint(req: ConflictResolveAllRequest, svc: OpenProjectDep) -> dict:
    """Resolve every pending conflict with one strategy ("local" or "remote")."""
    result = await sync_engine.resolve_all_conflicts(
        svc.session_factory, svc.project_path, req.resolution,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("reason", "resolution failed"))
    return result
