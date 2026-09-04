"""Server sync hub (SERVER_PLAN.md §8.3) — server mode only.

The server session holds the CANONICAL project database; clients push
their change entries and pull everyone else's. Replay/natural-key/
conflict machinery is the shared engine's, reused untouched:

- PUSH(instance_id, entries): entries are appended to the client's OWN
  sidecar under ``changes/<instance_id>/``, then imported into the
  canonical DB as instance ``__server__``; server-side API edits are
  flushed to the ``__server__`` sidecar so other clients can pull them.
- PULL(instance_id, since): every other sidecar's entries with
  ``seq > since`` — the client replays them through its own engine.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.auth_deps import get_current_user
from qualcoder_api.api.v1.deps import ServiceDep
from qualcoder_api.services.sync_replay import export_pending, import_pending
from qualcoder_api.services.sync_sidecar import (
    _append_sidecar,
    _max_sidecar_seq,
    _parse_sidecar,
    _sidecar_path,
)

router = APIRouter(tags=["server-sync"])

#: The canonical DB's own identity. It never pushes; it only imports what
#: clients push and exports server-side API edits for others to pull.
SERVER_INSTANCE = "__server__"

MAX_PULL_ENTRIES = 20_000


class SyncPushRequest(BaseModel):
    instance_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    entries: list[dict] = Field(max_length=20000)


class SyncPresenceRequest(BaseModel):
    instance_id: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_.-]*$")
    file_id: int | None = None
    file_name: str = Field(default="", max_length=512)


def _project_path(svc: ServiceDep) -> str:
    if not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    return svc.project_path


def _factory(svc: ServiceDep):
    if svc.session_factory is None:  # narrowed for mypy; gate guarantees a session
        raise HTTPException(status_code=409, detail="no project is open")
    return svc.session_factory


@router.post("/sync/push")
async def sync_push(
    req: SyncPushRequest,
    user: Annotated[dict, Depends(get_current_user)],
    svc: ServiceDep,
) -> dict:
    """Apply a client's change entries to the canonical DB.

    Returns the per-instance replay report ({applied, conflicts, retries})
    plus how many server-side edits were flushed for other clients."""
    from qualcoder_api.core.security import validate_instance_id
    from qualcoder_api.services.sync_schema import SYNC_LOCK

    _ = user  # membership + viewer gating handled by the router dependency
    try:
        validate_instance_id(req.instance_id)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if req.instance_id == SERVER_INSTANCE:
        raise HTTPException(status_code=422, detail="reserved instance id")
    path = _project_path(svc)
    applied: dict = {}
    async with SYNC_LOCK:
        if req.entries:
            lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in req.entries) + "\n"
            sidecar = _sidecar_path(path, req.instance_id)
            # The engine's append helper expects an existing instance dir
            # (shared-folder semantics); the hub creates it on first push.
            Path(sidecar).parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(_append_sidecar, sidecar, lines)
            async with _factory(svc)() as session:
                applied = await import_pending(session, path, SERVER_INSTANCE)
                await session.commit()

        # Flush SERVER-side API edits (sync_log rows) so other clients can
        # pull them. No-op when everything is already exported.
        async with _factory(svc)() as session:
            exported = await export_pending(session, path, SERVER_INSTANCE)
            await session.commit()

    total_applied = sum(int(v.get("applied", 0)) for v in applied.values())
    return {"ok": True, "applied": applied, "total_applied": total_applied, "exported": exported}


@router.get("/sync/pull")
async def sync_pull(
    svc: ServiceDep,
    user: Annotated[dict, Depends(get_current_user)],
    instance_id: str = "",
    since: int = 0,
) -> dict:
    """Every OTHER sidecar's entries past ``since``, seq-ascending."""
    _ = user
    path = _project_path(svc)
    root = Path(path) / "changes"
    entries: list[dict] = []
    if root.is_dir():
        for sidecar_dir in sorted(root.iterdir()):
            if not sidecar_dir.is_dir() or sidecar_dir.name == instance_id:
                continue
            sidecar = sidecar_dir / "changes.jsonl"
            if not sidecar.exists():
                continue
            parsed = await asyncio.to_thread(_parse_sidecar, sidecar)
            for e in parsed:
                try:
                    if int(e.get("seq", 0)) <= since:
                        continue
                except (TypeError, ValueError):
                    continue
                e.setdefault("instance", sidecar_dir.name)
                entries.append(e)
    entries.sort(key=lambda e: int(e.get("seq", 0)))
    truncated = len(entries) > MAX_PULL_ENTRIES
    server_seq = await asyncio.to_thread(_max_sidecar_seq, path)
    return {
        "ok": True,
        "entries": entries[:MAX_PULL_ENTRIES],
        "truncated": truncated,
        "server_seq": server_seq,
    }


@router.get("/sync/state")
async def sync_state(svc: ServiceDep, user: Annotated[dict, Depends(get_current_user)]) -> dict:
    from sqlalchemy import text

    from qualcoder_api.services.presence_service import read as presence_read

    _ = user
    path = _project_path(svc)
    async with _factory(svc)() as session:
        row = (
            await session.execute(
                text("SELECT COUNT(*) FROM sync_conflict WHERE resolved_at IS NULL")
            )
        ).first()
    conflicts = int(row[0]) if row else 0
    # exclude_pid -1: hub heartbeats are written BY this process on behalf
    # of remote coders, so the default self-exclusion would hide them all.
    return {
        "ok": True,
        "server_seq": await asyncio.to_thread(_max_sidecar_seq, path),
        "conflicts": conflicts,
        "presence": presence_read(path, exclude_pid=-1),
    }


@router.post("/sync/presence")
async def sync_presence(
    req: SyncPresenceRequest,
    user: Annotated[dict, Depends(get_current_user)],
    svc: ServiceDep,
) -> dict:
    from qualcoder_api.services.presence_service import touch

    path = _project_path(svc)
    written = touch(
        path,
        str(user["username"]),
        file_id=req.file_id,
        file_name=req.file_name or "",
        instance_id=req.instance_id or f"srv-{user['id']}",
    )
    return {"ok": True, "written": bool(written)}
