"""Shared FastAPI dependencies for API v1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.services.project_service import ProjectService

#: Server mode: the request-scoped ProjectService is placed here by
#: ``auth_deps.resolve_project_service`` (SERVER_PLAN.md Phase 2). It stays
#: UNSET in local mode — ``get_service`` then falls back to the global
#: singleton, so desktop behavior is byte-identical.
CURRENT_SERVICE: ContextVar[ProjectService | None] = ContextVar(
    "current_project_service", default=None
)


def get_service() -> ProjectService:
    """Return the active ProjectService.

    Server mode: the request-scoped instance from the ContextVar.
    Local mode: the process-wide singleton set by the app lifespan."""
    scoped = CURRENT_SERVICE.get()
    if scoped is not None:
        return scoped
    from qualcoder_api.main import service

    return service


async def get_db(svc: Annotated[ProjectService, Depends(get_service)]) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession for the open project; 409 when none is open."""
    if svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    async with svc.session_factory() as session:
        yield session


ServiceDep = Annotated[ProjectService, Depends(get_service)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def require_open_project(svc: ServiceDep) -> ProjectService:
    """Raise 409 when no project is open — for HARD routes (mutations and
    user-triggered actions) that previously hand-rolled this guard with the
    same literal string in dozens of places.

    NOT for polling endpoints: those intentionally answer ``{"ok": false,
    "reason": "no project open"}`` so continuous pollers can treat it as
    "sync off" without error handling."""
    if svc.session_factory is None or svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    return svc


OpenProjectDep = Annotated[ProjectService, Depends(require_open_project)]
