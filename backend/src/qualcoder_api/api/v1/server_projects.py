"""Server project registry, ACL, sessions and transfer (SERVER_PLAN.md §7.4).

Mounted ONLY in server mode. Clients address projects by UUID via the
``X-Project-Id`` header — never by path; ``data_path`` never leaves the
server.
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.auth_deps import get_current_user, require_admin
from qualcoder_api.core.server_config import load_server_config, resolve_under_root
from qualcoder_api.persistence import metadata_db
from qualcoder_api.services.project_service import ProjectService
from qualcoder_api.services.session_manager import manager, new_project_id

router = APIRouter(tags=["server-projects"])


async def _member_role(project_id: str, user: dict) -> str | None:
    """Role lookup with admin-as-owner fallback (plan §7.5)."""
    member = await metadata_db.get_member(project_id, int(user["id"]))
    if member is None and user.get("role") == "admin":
        return "owner"
    return member["role"] if member else None


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberRequest(BaseModel):
    role: str = Field(pattern="^(editor|viewer)$")


@router.get("/server/projects")
async def list_projects(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    is_admin = user.get("role") == "admin"
    rows = await metadata_db.list_projects_for_user(int(user["id"]), is_admin=is_admin)
    return {
        "projects": [
            {
                "id": r["id"],
                "name": r["name"],
                "role": r.get("role") or ("owner" if r["owner_id"] == int(user["id"]) else None),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    }


@router.post("/server/projects")
async def create_project(req: CreateProjectRequest, user: Annotated[dict, Depends(get_current_user)]) -> dict:
    cfg = load_server_config()
    pid = new_project_id()
    root = resolve_under_root(cfg.projects_root, pid) / f"{req.name}.qda"
    if root.exists():
        raise HTTPException(status_code=409, detail="project id collision — retry")
    service = ProjectService()
    created = await service.create_project(str(root), codername=str(user["username"]))
    if not created:
        raise HTTPException(status_code=422, detail="create failed")
    actual_path = service.project_path
    row = await metadata_db.create_project(pid, req.name, int(user["id"]), actual_path)
    return {"id": row["id"], "name": row["name"]}


@router.get("/server/projects/{project_id}")
async def project_detail(project_id: str, user: Annotated[dict, Depends(get_current_user)]) -> dict:
    project = await metadata_db.get_project(project_id)
    if project is None or await _member_role(project_id, user) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {
        "id": project["id"],
        "name": project["name"],
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "size_bytes": project["size_bytes"],
    }


@router.delete("/server/projects/{project_id}")
async def delete_project(project_id: str, user: Annotated[dict, Depends(get_current_user)]) -> dict:
    role = await _member_role(project_id, user)
    if role != "owner":
        raise HTTPException(status_code=403, detail="owner role required")
    project = await metadata_db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    await manager.close(project_id)
    shutil.rmtree(Path(project["data_path"]), ignore_errors=True)
    await metadata_db.delete_project_rows(project_id)
    return {"ok": True}


@router.get("/server/projects/{project_id}/members")
async def list_members(
    project_id: str, user: Annotated[dict, Depends(get_current_user)]
) -> dict:
    if await _member_role(project_id, user) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return {"members": await metadata_db.list_members(project_id)}


@router.put("/server/projects/{project_id}/members/{user_id}")
async def set_member(
    project_id: str,
    user_id: int,
    req: MemberRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    if await _member_role(project_id, user) != "owner":
        raise HTTPException(status_code=403, detail="owner role required")
    target = await metadata_db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    await metadata_db.add_member(project_id, user_id, req.role)
    return {"ok": True}


@router.delete("/server/projects/{project_id}/members/{user_id}")
async def remove_member_route(
    project_id: str, user_id: int, user: Annotated[dict, Depends(get_current_user)]
) -> dict:
    if await _member_role(project_id, user) != "owner":
        raise HTTPException(status_code=403, detail="owner role required")
    if not await metadata_db.remove_member(project_id, user_id):
        raise HTTPException(status_code=404, detail="membership not found (owners cannot be removed)")
    return {"ok": True}


@router.post("/server/projects/{project_id}/open")
async def open_session(project_id: str, user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if await _member_role(project_id, user) is None:
        raise HTTPException(status_code=403, detail="not a member of this project")
    await manager.acquire(dict(user), project_id)
    return {"ok": True}


@router.post("/server/projects/{project_id}/close")
async def close_session(project_id: str, user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if await _member_role(project_id, user) is None:
        raise HTTPException(status_code=403, detail="not a member of this project")
    # The session service is shared by all members of the project: closing
    # it here would evict everyone (DoS). A per-user close is a no-op — the
    # shared session is reaped after QC_SESSION_IDLE_SECS via release_idle.
    # Owners/admins can force-close via DELETE (project delete) or the idle
    # reaper; explicit eviction is intentionally not exposed per-member.
    return {"ok": True}


# ── Upload / download (§7.6) ────────────────────────────────────────────


def _zip_safe_names(zf: zipfile.ZipFile) -> None:
    for name in zf.namelist():
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise HTTPException(status_code=422, detail=f"unsafe zip entry: {name}")


@router.post("/server/projects/upload")
async def upload_project(file: UploadFile, user: Annotated[dict, Depends(require_admin)]) -> dict:
    cfg = load_server_config()
    cfg.uploads_dir.mkdir(parents=True, exist_ok=True)
    staging = cfg.uploads_dir / f"{new_project_id()}.zip"
    size = 0
    try:
        with staging.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > cfg.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="upload too large")
                out.write(chunk)
        with zipfile.ZipFile(staging) as zf:
            _zip_safe_names(zf)
            names = zf.namelist()
            data_members = [n for n in names if n.endswith("data.qda")]
            if len(data_members) != 1:
                raise HTTPException(status_code=422, detail="zip must contain exactly one data.qda")
            pid = new_project_id()
            dest_root = resolve_under_root(cfg.projects_root, pid)
            # Layout A: entries wrapped in "<name>.qda/…" (server download).
            # Layout B: entries at the ROOT (make_archive of a project dir) —
            # derive the name from the uploaded file and take every member.
            base_dir = data_members[0][: -len("data.qda")]
            if base_dir:
                project_name = Path(base_dir.rstrip("/")).name or "imported"
                prefix = base_dir
            else:
                stem = Path(file.filename or "").stem or "imported"
                project_name = stem
                prefix = ""
            extract_to = dest_root / f"{project_name}.qda"
            extract_to.parent.mkdir(parents=True, exist_ok=True)
            for member in names:
                if not member.startswith(prefix):
                    continue
                rel = member[len(prefix):]
                target = extract_to / rel
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
        row = await metadata_db.create_project(
            pid, project_name, int(user["id"]), str(extract_to)
        )
        return {"id": row["id"], "name": row["name"]}
    finally:
        staging.unlink(missing_ok=True)


@router.get("/server/projects/{project_id}/download")
async def download_project(
    project_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    include_backups: int = 0,
):
    from fastapi.responses import FileResponse

    project = await metadata_db.get_project(project_id)
    if project is None or await _member_role(project_id, user) is None:
        raise HTTPException(status_code=404, detail="project not found")
    cfg = load_server_config()
    source = Path(project["data_path"])
    if not source.is_dir():
        raise HTTPException(status_code=404, detail="project data missing")
    cfg.temp_dir.mkdir(parents=True, exist_ok=True)
    archive_base = cfg.temp_dir / f"{project_id}-{project['name']}"
    skip = {"changes", "presence", "backups"} if not include_backups else {"changes", "presence"}
    shutil.make_archive(str(archive_base), "zip", source)
    # make_archive cannot exclude — rebuild the archive without the
    # transport-internal directories.
    final_zip = Path(shutil.make_archive(str(archive_base), "zip", source))
    cleaned = archive_base.with_name(archive_base.name + "-clean.zip")
    with zipfile.ZipFile(final_zip) as zin, zipfile.ZipFile(
        cleaned, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            top = Path(item.filename).parts[0] if item.filename else ""
            if top in skip:
                continue
            zout.writestr(item, zin.read(item.filename))
    final_zip.unlink(missing_ok=True)
    cleaned.rename(final_zip)
    return FileResponse(
        final_zip,
        media_type="application/zip",
        filename=f"{project['name']}.zip",
    )
