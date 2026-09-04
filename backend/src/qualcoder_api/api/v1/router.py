"""API v1 router — health and project lifecycle endpoints."""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.ai import router as ai_router
from qualcoder_api.api.v1.audit import router as audit_router
from qualcoder_api.api.v1.auth_deps import gate_project_scoped
from qualcoder_api.api.v1.code_sets import router as code_sets_router
from qualcoder_api.api.v1.coders import router as coders_router
from qualcoder_api.api.v1.codes import router as codes_router
from qualcoder_api.api.v1.codings import router as codings_router
from qualcoder_api.api.v1.comments import router as comments_router
from qualcoder_api.api.v1.compare import router as compare_router
from qualcoder_api.api.v1.creative import router as creative_router
from qualcoder_api.api.v1.deps import ServiceDep
from qualcoder_api.api.v1.dictionaries import router as dictionaries_router
from qualcoder_api.api.v1.entities import (
    annotation_router,
    attr_router,
    case_router,
    journal_router,
)
from qualcoder_api.api.v1.graphs import router as graphs_router
from qualcoder_api.api.v1.help import router as help_router
from qualcoder_api.api.v1.importers import router as importers_router
from qualcoder_api.api.v1.interchange import router as interchange_router
from qualcoder_api.api.v1.links import router as links_router
from qualcoder_api.api.v1.publish import router as publish_router
from qualcoder_api.api.v1.qtt import router as qtt_router
from qualcoder_api.api.v1.r import router as r_router
from qualcoder_api.api.v1.r_scripts import router as r_scripts_router
from qualcoder_api.api.v1.reports import router as reports_router
from qualcoder_api.api.v1.scrape import router as scrape_router
from qualcoder_api.api.v1.search import router as search_router
from qualcoder_api.api.v1.sentiment import router as sentiment_router
from qualcoder_api.api.v1.sources import router as sources_router
from qualcoder_api.api.v1.sql_reports import router as sql_router
from qualcoder_api.api.v1.sync_api import router as sync_router
from qualcoder_api.api.v1.tools import router as tools_router
from qualcoder_api.api.v1.transcribe import router as transcribe_router
from qualcoder_api.core import APP_VERSION
from qualcoder_api.core.server_config import is_server_mode
from qualcoder_api.persistence import tables
from qualcoder_api.services.project_service import OpenResult

logger = logging.getLogger(__name__)

router = APIRouter()

# Server mode (SERVER_PLAN.md §7.3): every project-scoped router is gated by
# bearer auth + X-Project-Id session resolution WITHOUT touching endpoint
# functions — deps.get_service reads the ContextVar this dependency sets.
# Local mode: no gating, byte-identical behavior.


_PROJECT_GATE = [Depends(gate_project_scoped)]


def _include(r: APIRouter) -> None:
    # Always attached; the gate no-ops in local mode (runtime check) and
    # performs bearer + X-Project-Id session resolution in server mode.
    router.include_router(r, dependencies=_PROJECT_GATE)

# tools_router first: its literal GET /sources/bad-links and
# GET /sources/filters paths must win over the dynamic GET /sources/{source_id}.
_include(tools_router)
_include(sources_router)
_include(codes_router)
_include(codings_router)
_include(case_router)
_include(attr_router)
_include(journal_router)
_include(annotation_router)
_include(reports_router)
_include(interchange_router)
_include(importers_router)
_include(sql_router)
_include(ai_router)
_include(coders_router)
_include(audit_router)
_include(transcribe_router)
_include(graphs_router)
_include(sync_router)
_include(dictionaries_router)
_include(links_router)
_include(sentiment_router)
_include(compare_router)
_include(scrape_router)
_include(creative_router)
_include(publish_router)
_include(qtt_router)
_include(comments_router)
_include(code_sets_router)
_include(r_router)
_include(r_scripts_router)
_include(search_router)
_include(help_router)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = APP_VERSION


class CreateProjectRequest(BaseModel):
    project_path: str = Field(min_length=1, max_length=4096)
    codername: str | None = Field(default=None, max_length=64)


class OpenProjectRequest(BaseModel):
    project_path: str = Field(min_length=1, max_length=4096)
    codername: str | None = Field(default=None, max_length=64)
    backup_on_open: bool = False


class ProjectResponse(BaseModel):
    ok: bool
    project_path: str = ""
    project_name: str = ""
    migrations_applied: list[str] = Field(default_factory=list)
    error: str = ""
    lock_user: str = ""
    #: Another live instance already open as the same coder (open only) —
    #: the UI warns before this is allowed to corrupt sync.
    duplicate_coder: str = ""
    #: Shared-folder detection result (open only): the frontend enables the
    #: collaboration sync cycle when this is true (respects the per-project
    #: override).
    sync_auto_enabled: bool = False
    sync_auto_reason: str = ""


class SummaryResponse(BaseModel):
    summary: dict


class RecentProjectsResponse(BaseModel):
    recent: list[str] = Field(default_factory=list)


class MemoItem(BaseModel):
    kind: str  # "file" | "code"
    id: int
    name: str
    memo: str
    date: str = ""
    owner: str = ""


class MemosResponse(BaseModel):
    memos: list[MemoItem] = Field(default_factory=list)


class UpdatesSettingsRequest(BaseModel):
    check_interval: str = "daily"
    auto_update: bool = True


class AppSettingsRequest(BaseModel):
    auto_open_project: bool = True


class MaintenanceSettingsRequest(BaseModel):
    compact_on_close: bool = False


class MaintenanceSettingsResponse(BaseModel):
    compact_on_close: bool = False
    last_compact: str = ""


class CompactResponse(BaseModel):
    ok: bool = True
    before_bytes: int = 0
    after_bytes: int = 0
    freed_bytes: int = 0
    indexes_dropped: int = 0
    indexes_recreated: int = 0


@router.get("/app/settings", response_model=AppSettingsRequest)
async def get_app_settings() -> AppSettingsRequest:
    """App-level preferences (auto-load project on start)."""
    from qualcoder_api.services.user_settings import get_auto_open_project

    return AppSettingsRequest(auto_open_project=get_auto_open_project())


@router.put("/app/settings", response_model=AppSettingsRequest)
async def put_app_settings(req: AppSettingsRequest) -> AppSettingsRequest:
    from qualcoder_api.services.user_settings import save_auto_open_project

    return AppSettingsRequest(auto_open_project=save_auto_open_project(req.auto_open_project))


@router.get("/updates/settings", response_model=UpdatesSettingsRequest)
async def get_updates_settings() -> UpdatesSettingsRequest:
    """App-update preferences (check cadence, auto-install)."""
    from qualcoder_api.services.user_settings import get_updates_settings

    return UpdatesSettingsRequest(**get_updates_settings())


@router.put("/updates/settings", response_model=UpdatesSettingsRequest)
async def put_updates_settings(req: UpdatesSettingsRequest) -> UpdatesSettingsRequest:
    from qualcoder_api.services.user_settings import save_updates_settings

    return UpdatesSettingsRequest(**save_updates_settings(req.model_dump()))


@router.get("/maintenance/settings", response_model=MaintenanceSettingsResponse)
async def get_maintenance_settings() -> MaintenanceSettingsResponse:
    """Project-maintenance preferences (compact on close, last compact time)."""
    from qualcoder_api.services.user_settings import get_maintenance_settings

    return MaintenanceSettingsResponse(**get_maintenance_settings())


@router.put("/maintenance/settings", response_model=MaintenanceSettingsResponse)
async def put_maintenance_settings(
    req: MaintenanceSettingsRequest,
) -> MaintenanceSettingsResponse:
    from qualcoder_api.services.user_settings import save_maintenance_settings

    return MaintenanceSettingsResponse(
        **save_maintenance_settings({"compact_on_close": req.compact_on_close})
    )


@router.get("/memos", response_model=MemosResponse)
async def list_memos(svc: ServiceDep) -> MemosResponse:
    """File and code memos (Notes workspace)."""
    if svc.engine is None:
        return MemosResponse()
    from sqlalchemy import select

    _, factory = svc._ensure_engine()
    items: list[MemoItem] = []
    async with factory() as session:
        file_rows = await session.execute(
            select(
                tables.source.c.id,
                tables.source.c.name,
                tables.source.c.memo,
                tables.source.c.owner,
                tables.source.c.date,
            ).where(tables.source.c.memo.is_not(None))
        )
        for sid, name, memo, owner, date in file_rows:
            if memo and str(memo).strip():
                items.append(
                    MemoItem(kind="file", id=sid, name=name or "", memo=str(memo), date=date or "", owner=owner or "")
                )
        code_rows = await session.execute(
            select(
                tables.code_name.c.cid,
                tables.code_name.c.name,
                tables.code_name.c.memo,
                tables.code_name.c.owner,
                tables.code_name.c.date,
            ).where(tables.code_name.c.memo.is_not(None))
        )
        for cid, name, memo, owner, date in code_rows:
            if memo and str(memo).strip():
                items.append(
                    MemoItem(kind="code", id=cid, name=name or "", memo=str(memo), date=date or "", owner=owner or "")
                )
    items.sort(key=lambda m: (m.memo or "").lower())
    return MemosResponse(memos=items)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/projects", response_model=RecentProjectsResponse)
async def recent_projects() -> RecentProjectsResponse:
    from qualcoder_api.services.user_settings import get_recent_projects

    return RecentProjectsResponse(recent=get_recent_projects())


@router.post("/projects", response_model=ProjectResponse)
async def create_project(req: CreateProjectRequest, svc: ServiceDep) -> ProjectResponse:
    if is_server_mode():
        raise HTTPException(
            status_code=410, detail='projects are managed by the server project API'
        )
    from qualcoder_api.services.user_settings import resolve_owner

    ok = await svc.create_project(req.project_path, codername=resolve_owner(req.codername))
    if not ok:
        raise HTTPException(status_code=500, detail="project creation failed")
    return ProjectResponse(ok=True, project_path=svc.project_path, project_name=svc.project_name)


@router.post("/projects/open", response_model=ProjectResponse)
async def open_project(req: OpenProjectRequest, svc: ServiceDep) -> ProjectResponse:
    if is_server_mode():
        raise HTTPException(
            status_code=410, detail='projects are managed by the server project API'
        )
    from qualcoder_api.services.user_settings import resolve_owner

    result: OpenResult = await svc.open_project(
        req.project_path,
        codername=resolve_owner(req.codername),
        backup_on_open=req.backup_on_open,
    )
    if not result.ok:
        return ProjectResponse(
            ok=False, project_path=result.project_path, error=result.error, lock_user=result.lock_user
        )
    # Transcripts finished while the app was closed were persisted by the
    # worker; finalize them now so they appear in the project.
    from qualcoder_api.services.transcription import sweep_pending_transcripts

    if svc.session_factory is not None:
        with contextlib.suppress(Exception):  # pragma: no cover - best effort
            await sweep_pending_transcripts(
                project_path=svc.project_path,
                session_factory=svc.session_factory,
            )
    # Shared-folder detection: tells the frontend whether the collaboration
    # sync cycle should be switched on (per-project override wins).
    from qualcoder_api.services import sync as sync_service

    decision = sync_service.auto_enable_decision(
        result.project_path, user=resolve_owner(req.codername)
    )
    return ProjectResponse(
        ok=True,
        project_path=result.project_path,
        project_name=result.project_name,
        migrations_applied=result.migrations_applied,
        lock_user=result.lock_user,
        duplicate_coder=result.duplicate_coder,
        sync_auto_enabled=decision["sync_auto_enabled"],
        sync_auto_reason=decision["reason"],
    )


@router.post("/projects/close", response_model=ProjectResponse)
async def close_project(svc: ServiceDep) -> ProjectResponse:
    if is_server_mode():
        raise HTTPException(
            status_code=410, detail='projects are managed by the server project API'
        )
    name = svc.project_name
    await svc.close_project()
    return ProjectResponse(ok=True, project_name=name)


@router.post("/projects/compact", response_model=CompactResponse)
async def compact_project(svc: ServiceDep) -> CompactResponse:
    if is_server_mode():
        raise HTTPException(
            status_code=410, detail='projects are managed by the server project API'
        )
    """Maintenance pass on the open project: flush the WAL, drop the
    rebuildable ``idx_*`` indexes, VACUUM, recreate the indexes.

    Safe while the project stays open: the compaction uses its own raw
    autocommit connection and the engine pool is idle (no open transaction),
    so the VACUUM is never blocked by this process (see
    ``services.cleanup_service`` for the full connection reasoning).
    """
    if svc.engine is None or not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    from qualcoder_api.services.cleanup_service import compact_project as run_compact

    try:
        stats = await run_compact(svc.db_path())
    except Exception as err:  # pragma: no cover - depends on the environment
        logger.exception("project compaction failed")
        raise HTTPException(status_code=500, detail=f"compaction failed: {err}") from err

    _, factory = svc._ensure_engine()
    async with factory() as session:
        from qualcoder_api.services import audit
        from qualcoder_api.services.user_settings import get_codername

        await audit.record(
            session,
            user=get_codername(),
            action="project.compact",
            entity="project",
            detail=stats,
        )
    from qualcoder_api.services.user_settings import set_last_compact

    set_last_compact()
    return CompactResponse(ok=True, **stats)


@router.get("/projects/current/summary", response_model=SummaryResponse)
async def current_project_summary(svc: ServiceDep) -> SummaryResponse:
    if svc.engine is None:
        raise HTTPException(status_code=409, detail="no project is open")
    from qualcoder_api.persistence.repositories import ProjectRepository

    _, factory = svc._ensure_engine()
    async with factory() as session:
        summary = await ProjectRepository(session).get_summary()
    return SummaryResponse(summary=summary)


class OpenersResponse(BaseModel):
    openers: list[dict] = Field(default_factory=list)


@router.get("/projects/openers", response_model=OpenersResponse)
async def project_openers(svc: ServiceDep) -> OpenersResponse:
    """Other live instances currently holding the project open."""
    return OpenersResponse(openers=svc.openers())


class ProjectModeResponse(BaseModel):
    mode: str = "single"  # "single" | "collaboration"
    uuid: str = ""


class CollaborationResponse(BaseModel):
    ok: bool
    reason: str = ""
    uuid: str = ""


@router.get("/projects/mode", response_model=ProjectModeResponse)
async def project_mode(svc: ServiceDep) -> ProjectModeResponse:
    """Whether the open project runs in collaboration (sandbox) mode."""
    if svc.collaboration_mode():
        return ProjectModeResponse(mode="collaboration", uuid=svc.uuid)
    return ProjectModeResponse(mode="single")


@router.post("/projects/activate-collaboration", response_model=CollaborationResponse)
async def activate_collaboration(svc: ServiceDep) -> CollaborationResponse:
    """Switch the open project to collaboration (sandbox) mode.

    Gated on sync being enabled and ≥2 real coders.  Idempotent.
    """
    if svc.engine is None or not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    from qualcoder_api.services.user_settings import get_codername

    result = await svc.activate_collaboration(codername=get_codername())
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "cannot activate"))
    return CollaborationResponse(
        ok=True, reason=result.get("reason", ""), uuid=result.get("uuid", "")
    )


@router.post("/projects/revert-collaboration", response_model=CollaborationResponse)
async def revert_collaboration(svc: ServiceDep) -> CollaborationResponse:
    """Consolidate to ``data.qda`` and return to single-coder mode.

    Destructive: removes the marker, sandbox, sidecars and disables sync.
    """
    if svc.engine is None or not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    result = await svc.revert_collaboration()
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "cannot revert"))
    return CollaborationResponse(ok=True, reason=result.get("reason", ""))


@router.post("/projects/consolidate", response_model=CollaborationResponse)
async def consolidate_project(svc: ServiceDep) -> CollaborationResponse:
    """Refresh the cold ``data.qda`` archive from the live sandbox."""
    if svc.engine is None or not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    result = await svc.consolidate()
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "cannot consolidate"))
    return CollaborationResponse(ok=True, reason=result.get("reason", ""))
