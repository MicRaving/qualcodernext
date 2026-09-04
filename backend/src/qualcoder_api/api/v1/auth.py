"""Server auth endpoints (SERVER_PLAN.md §6.5).

Mounted ONLY in server mode (see main.create_app). Passkey endpoints are
Phase 1b — password + opaque-token auth is the complete Phase 1 core.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.auth_deps import (
    get_current_user,
    parse_bearer_token,
    require_admin,
)
from qualcoder_api.core.server_config import load_server_config
from qualcoder_api.persistence import metadata_db
from qualcoder_api.services import password as password_svc
from qualcoder_api.services import token_service

router = APIRouter(prefix="/auth", tags=["server-auth"])
logger = logging.getLogger(__name__)

_USERNAME_RE = r"^[a-zA-Z0-9_.-]{3,32}$"

# Simple in-memory login rate limiter: (failures, window_start) per key.
_LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECS = 60.0


def _rate_limit_key(username: str) -> str:
    return (username or "").strip().lower() or "unknown"


def _check_rate_limit(key: str) -> None:
    import time

    now = time.monotonic()
    failures, start = _LOGIN_ATTEMPTS.get(key, (0, now))
    if now - start > _LOGIN_WINDOW_SECS:
        _LOGIN_ATTEMPTS.pop(key, None)
        return
    if failures >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="too many login attempts — try again later")


def _record_login_failure(key: str) -> None:
    import time

    now = time.monotonic()
    failures, start = _LOGIN_ATTEMPTS.get(key, (0, now))
    if now - start > _LOGIN_WINDOW_SECS:
        _LOGIN_ATTEMPTS[key] = (1, now)
    else:
        _LOGIN_ATTEMPTS[key] = (failures + 1, start)


def _record_login_success(key: str) -> None:
    _LOGIN_ATTEMPTS.pop(key, None)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=_USERNAME_RE)
    display_name: str = ""
    email: str = ""
    password: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name", ""),
        "email": user.get("email", ""),
        "role": user["role"],
    }


async def _issue(user: dict) -> dict:
    raw, expires_at = await token_service.issue_token(user["id"], name="login")
    return {"token": raw, "expires_at": expires_at, "user": _public_user(user)}


@router.post("/register")
async def register(
    req: RegisterRequest,
    authorization: str = Header(default=""),
) -> dict:
    """Create a user. Bootstrap: the FIRST registered user becomes admin;
    afterwards registration is admin-only."""
    from sqlalchemy.exc import IntegrityError

    if not req.password or len(req.password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    users_exist = await metadata_db.count_users() > 0
    role = "user"
    if users_exist:
        user = await get_current_user(authorization)
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin role required")
        role = "user"
    else:
        role = "admin"
    if await metadata_db.get_user_by_username(req.username) is not None:
        raise HTTPException(status_code=409, detail="username already taken")
    try:
        created = await metadata_db.insert_user(
            req.username,
            password_svc.hash_password(req.password),
            role=role,
            display_name=req.display_name,
            email=req.email,
        )
    except IntegrityError as err:
        # Concurrent bootstrap: two first-registers raced past count_users().
        # Only the lowest user id keeps admin; the loser becomes a plain user
        # (or 409 when the username itself collided).
        existing = await metadata_db.get_user_by_username(req.username)
        if existing is not None:
            raise HTTPException(status_code=409, detail="username already taken") from err
        raise HTTPException(status_code=409, detail="registration conflict — retry") from err
    if role == "admin" and int(created.get("id", 1)) != 1:
        # A second concurrent bootstrap slipped through: demote to user.
        try:
            from sqlalchemy import text as _text

            factory = metadata_db.metadata_factory()
            async with factory() as session:
                await session.execute(
                    _text("UPDATE users SET role = 'user' WHERE id = :id AND id != 1"),
                    {"id": created["id"]},
                )
                await session.commit()
            created["role"] = "user"
        except Exception:
            pass
    return {"user": _public_user(created)}


@router.post("/login")
async def login(req: LoginRequest) -> dict:
    key = _rate_limit_key(req.username)
    _check_rate_limit(key)
    user = await metadata_db.get_user_by_username(req.username)
    # Constant-time-ish: always run a verify to avoid trivially timing
    # account existence.
    stored = user["password_hash"] if user else ""
    ok = password_svc.verify_password(req.password, stored)
    if user is None or not ok:
        _record_login_failure(key)
        raise HTTPException(status_code=401, detail="invalid credentials")
    if user["disabled"]:
        _record_login_failure(key)
        raise HTTPException(status_code=401, detail="account disabled")
    _record_login_success(key)
    return await _issue(user)


@router.post("/logout")
async def logout(authorization: str = Header(default="")) -> dict:
    raw = parse_bearer_token(authorization)
    user_id = await token_service.verify_token(raw)
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    await token_service.revoke_token(raw)
    return {"ok": True}


@router.post("/refresh")
async def refresh(authorization: str = Header(default="")) -> dict:
    raw = parse_bearer_token(authorization)
    user_id = await token_service.verify_token(raw)
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    await token_service.revoke_token(raw)
    user = await metadata_db.get_user_by_id(user_id)
    if user is None or user["disabled"]:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return await _issue(user)


@router.get("/me")
async def me(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    return {"user": _public_user(user)}


@router.post("/users/{user_id}/disable")
async def disable_user(user_id: int, user: Annotated[dict, Depends(require_admin)]) -> dict:
    target = await metadata_db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    await metadata_db.set_user_disabled(user_id, True)
    await token_service.revoke_all_for_user(user_id)
    return {"ok": True}


# ── Passkeys (Phase 1b) ─────────────────────────────────────────────────


class PasskeyCompleteRequest(BaseModel):
    response: str = Field(description="PublicKeyCredential JSON from the browser")


class PasskeyLoginBeginRequest(BaseModel):
    username: str = ""


class PasskeyLoginCompleteRequest(BaseModel):
    username: str
    response: str


def _require_rp() -> None:
    if not load_server_config().rp_id:
        raise HTTPException(status_code=503, detail="passkeys not configured (QC_RP_ID missing)")


@router.post("/passkey/register/begin")
async def passkey_register_begin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    _require_rp()
    import json

    from qualcoder_api.services import passkey_service

    return json.loads(await passkey_service.begin_registration(user))


@router.post("/passkey/register/complete")
async def passkey_register_complete(
    req: PasskeyCompleteRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    _require_rp()

    from webauthn.helpers.exceptions import InvalidRegistrationResponse

    from qualcoder_api.services import passkey_service

    try:
        result = await passkey_service.complete_registration(user, req.response)
    except InvalidRegistrationResponse as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {"ok": True, **result}


@router.get("/passkeys")
async def list_passkeys(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    rows = await metadata_db.list_passkeys(user["id"])
    return {
        "passkeys": [
            {"id": r["id"], "name": r["name"], "created_at": r["created_at"]} for r in rows
        ]
    }


@router.delete("/passkeys/{passkey_id}")
async def delete_passkey(
    passkey_id: int, user: Annotated[dict, Depends(get_current_user)]
) -> dict:
    removed = await metadata_db.delete_passkey(passkey_id, user["id"])
    if not removed:
        raise HTTPException(status_code=404, detail="passkey not found")
    return {"ok": True}


@router.post("/passkey/login/begin")
async def passkey_login_begin(req: PasskeyLoginBeginRequest) -> dict:
    _require_rp()
    import json

    from qualcoder_api.services import passkey_service

    options = await passkey_service.begin_login(req.username or None)
    return {"options": json.loads(options)}


@router.post("/passkey/login/complete")
async def passkey_login_complete(req: PasskeyLoginCompleteRequest) -> dict:
    _require_rp()
    from webauthn.helpers.exceptions import (
        InvalidAuthenticationResponse,
        InvalidRegistrationResponse,
    )

    from qualcoder_api.services import passkey_service

    try:
        user = await passkey_service.complete_login(req.username, req.response)
    except (InvalidAuthenticationResponse, InvalidRegistrationResponse) as err:
        logger.warning("passkey assertion failed for %s: %s", req.username, err)
        raise HTTPException(status_code=401, detail="passkey assertion failed") from err
    if user["disabled"]:
        raise HTTPException(status_code=401, detail="account disabled")
    return await _issue(user)
