"""API v1 router — health and project lifecycle endpoints."""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.ai import router as ai_router
from qualcoder_api.api.v1.audit import router as audit_router
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
from qualcoder_api.api.v1.importers import router as importers_router
from qualcoder_api.api.v1.interchange import router as interchange_router
from qualcoder_api.api.v1.links import router as links_router
from qualcoder_api.api.v1.publish import router as publish_router
from qualcoder_api.api.v1.qtt import router as qtt_router
from qualcoder_api.api.v1.r import router as r_router
from qualcoder_api.api.v1.r_scripts import router as r_scripts_router
from qualcoder_api.api.v1.reports import router as reports_router
from qualcoder_api.api.v1.scrape import router as scrape_router
from qualcoder_api.api.v1.sentiment import router as sentiment_router
from qualcoder_api.api.v1.sources import router as sources_router
from qualcoder_api.api.v1.sql_reports import router as sql_router
from qualcoder_api.api.v1.sync_api import router as sync_router
from qualcoder_api.api.v1.tools import router as tools_router
from qualcoder_api.api.v1.transcribe import router as transcribe_router
from qualcoder_api.core import APP_VERSION
from qualcoder_api.persistence import tables
from qualcoder_api.services.project_service import OpenResult

logger = logging.getLogger(__name__)

router = APIRouter()

# tools_router first: its literal GET /sources/bad-links and
# GET /sources/filters paths must win over the dynamic GET /sources/{source_id}.
router.include_router(tools_router)
router.include_router(sources_router)
router.include_router(codes_router)
router.include_router(codings_router)
router.include_router(case_router)
router.include_router(attr_router)
router.include_router(journal_router)
router.include_router(annotation_router)
router.include_router(reports_router)
router.include_router(interchange_router)
router.include_router(importers_router)
router.include_router(sql_router)
router.include_router(ai_router)
router.include_router(coders_router)
router.include_router(audit_router)
router.include_router(transcribe_router)
router.include_router(graphs_router)
router.include_router(sync_router)
router.include_router(dictionaries_router)
router.include_router(links_router)
router.include_router(sentiment_router)
router.include_router(compare_router)
router.include_router(scrape_router)
router.include_router(creative_router)
router.include_router(publish_router)
router.include_router(qtt_router)
router.include_router(comments_router)
router.include_router(code_sets_router)
router.include_router(r_router)
router.include_router(r_scripts_router)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = APP_VERSION


class CreateProjectRequest(BaseModel):
    project_path: str
    codername: str | None = None


class OpenProjectRequest(BaseModel):
    project_path: str
    codername: str | None = None
    backup_on_open: bool = False


class ProjectResponse(BaseModel):
    ok: bool
    project_path: str = ""
    project_name: str = ""
    migrations_applied: list[str] = Field(default_factory=list)
    error: str = ""
    lock_user: str = ""
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
    from qualcoder_api.services.user_settings import resolve_owner

    ok = await svc.create_project(req.project_path, codername=resolve_owner(req.codername))
    if not ok:
        raise HTTPException(status_code=500, detail="project creation failed")
    return ProjectResponse(ok=True, project_path=svc.project_path, project_name=svc.project_name)


@router.post("/projects/open", response_model=ProjectResponse)
async def open_project(req: OpenProjectRequest, svc: ServiceDep) -> ProjectResponse:
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
        sync_auto_enabled=decision["sync_auto_enabled"],
        sync_auto_reason=decision["reason"],
    )


@router.post("/projects/close", response_model=ProjectResponse)
async def close_project(svc: ServiceDep) -> ProjectResponse:
    name = svc.project_name
    await svc.close_project()
    return ProjectResponse(ok=True, project_name=name)


@router.post("/projects/compact", response_model=CompactResponse)
async def compact_project(svc: ServiceDep) -> CompactResponse:
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
