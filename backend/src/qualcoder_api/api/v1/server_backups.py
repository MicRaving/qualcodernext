"""Server backup endpoints (SERVER_PLAN.md §9.3). Server mode only."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from qualcoder_api.api.v1.auth_deps import get_current_user, require_admin
from qualcoder_api.api.v1.server_projects import _member_role
from qualcoder_api.persistence import metadata_db
from qualcoder_api.services import backup_service

router = APIRouter(tags=["server-backups"])


async def _require_owner(project_id: str, user: dict) -> None:
    if await _member_role(project_id, user) != "owner":
        raise HTTPException(status_code=403, detail="owner role required")


@router.get("/server/projects/{project_id}/backups")
async def list_backups(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    return {"backups": await metadata_db.list_backup_records(project_id)}


@router.post("/server/projects/{project_id}/backups")
async def create_backup(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    record = await backup_service.create_backup(project_id, kind="manual")
    return {
        "backup": {
            "id": record["id"],
            "kind": record["kind"],
            "size_bytes": record["size_bytes"],
            "checksum": record["checksum"],
            "cloud_status": record["cloud_status"],
            "created_at": record["created_at"],
        }
    }


@router.post("/server/projects/{project_id}/backups/{backup_id}/restore")
async def restore_backup(
    project_id: str,
    backup_id: int,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    await _require_owner(project_id, user)
    return await backup_service.restore_backup(project_id, backup_id)


@router.post("/admin/backup/run-all")
async def run_all(user: Annotated[dict, Depends(require_admin)]) -> dict:
    ran = await backup_service.run_all_scheduled()
    return {"ok": True, "ran": ran}


@router.get("/admin/backup/status")
async def status(user: Annotated[dict, Depends(require_admin)]) -> dict:
    from sqlalchemy import text

    factory = metadata_db.metadata_factory()
    async with factory() as session:
        total = (
            await session.execute(text("SELECT COUNT(*) FROM backup_records"))
        ).scalar_one()
        active = (
            await session.execute(
                text("SELECT COUNT(*) FROM projects WHERE status = 'active'")
            )
        ).scalar_one()
    return {"ok": True, "total_backups": int(total), "active_projects": int(active)}
