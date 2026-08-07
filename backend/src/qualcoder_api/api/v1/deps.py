"""Shared FastAPI dependencies for API v1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.services.project_service import ProjectService


def get_service() -> ProjectService:
    """Return the process-wide ProjectService (set by the app lifespan)."""
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
