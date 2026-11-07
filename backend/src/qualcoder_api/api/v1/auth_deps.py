"""Server auth dependencies (SERVER_PLAN.md §6.6).

``get_current_user`` resolves the Bearer token to a live user row.
Server mode only — these dependencies are mounted exclusively on the
server routers.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from qualcoder_api.api.v1.deps import CURRENT_SERVICE
from qualcoder_api.persistence import metadata_db
from qualcoder_api.services import token_service
from qualcoder_api.services.project_service import ProjectService
from qualcoder_api.services.session_manager import manager


async def _user_from_authorization(authorization: str) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    raw = authorization[len("Bearer "):].strip()
    user_id = await token_service.verify_token(raw)
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    user = await metadata_db.get_user_by_id(user_id)
    if user is None or user["disabled"]:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return user


async def get_current_user(
    authorization: str = Header(default=""),
) -> dict:
    return await _user_from_authorization(authorization)


async def require_admin(
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Guard for admin-only endpoints; use as ``Depends(require_admin)``."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


async def gate_project_scoped(
    request: Request,
    authorization: Annotated[str, Header()] = "",
    x_project_id: Annotated[str | None, Header()] = None,
) -> AsyncIterator[ProjectService]:
    """Router-attached gate that decides AT REQUEST TIME (never at import).

    Local mode: no-op — yields the local singleton so endpoints behave
    byte-identically. Server mode (plan §7.2): resolves the bearer token,
    acquires the project session and places the request-scoped
    ProjectService into ``CURRENT_SERVICE`` (read by ``deps.get_service``);
    viewers are limited to GET/HEAD/OPTIONS (§7.5). The import-time variant of
    this gating broke once ANY module imported the router before the env
    was set (pytest collection order).
    """
    from qualcoder_api.core.server_config import is_server_mode

    if not is_server_mode():
        from qualcoder_api.api.v1.deps import get_service

        yield get_service()
        return

    if not x_project_id:
        raise HTTPException(status_code=400, detail="X-Project-Id header required")
    user = await get_current_user_headerless(authorization)
    service, role = await manager.acquire(user, x_project_id)
    if role == "viewer" and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(status_code=403, detail="read-only membership")
    token = CURRENT_SERVICE.set(service)
    try:
        yield service
    finally:
        CURRENT_SERVICE.reset(token)


async def get_current_user_headerless(
    authorization: Annotated[str, Header()] = "",
) -> dict:
    return await _user_from_authorization(authorization)


def parse_bearer_token(authorization: str) -> str:
    """The RAW token from an Authorization header (for revoke/refresh)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization[len("Bearer "):].strip()
