"""Server auth dependencies (SERVER_PLAN.md §6.6).

``get_current_user`` resolves the Bearer token to a live user row.
Server mode only — these dependencies are mounted exclusively on the
server routers.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from qualcoder_api.persistence import metadata_db
from qualcoder_api.services import token_service


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


def parse_bearer_token(authorization: str) -> str:
    """The RAW token from an Authorization header (for revoke/refresh)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization[len("Bearer "):].strip()
