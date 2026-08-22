"""SERVER_PLAN.md Phase 1 core — metadata DB, passwords, tokens, auth API.

Passkey endpoints are Phase 1b; everything here is password + opaque
token auth against a per-test tmp metadata DB.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qualcoder_api.persistence import metadata_db


@pytest.fixture()
async def meta_db(tmp_path):
    """A fresh metadata DB per test."""
    await metadata_db.migrate_metadata(tmp_path / "meta.db")
    yield tmp_path / "meta.db"
    # engine is global state — dispose so the next test re-inits cleanly
    await metadata_db.dispose_metadata_engine()


@pytest.fixture()
async def client(meta_db):
    from qualcoder_api.api.v1.auth import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _bootstrap_admin(client: AsyncClient) -> tuple[str, dict]:
    r = await client.post(
        "/api/v1/auth/register",
        json={"username": "admin", "password": "admin-pw-123"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"
    r = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin-pw-123"}
    )
    assert r.status_code == 200
    body = r.json()
    return body["token"], body["user"]


# ── metadata db / migrations ────────────────────────────────────────────


async def test_migrations_idempotent(tmp_path):
    v1 = await metadata_db.migrate_metadata(tmp_path / "m.db")
    v2 = await metadata_db.migrate_metadata(tmp_path / "m.db")
    assert v1 == v2 == 1


async def test_user_crud_roundtrip(meta_db):
    created = await metadata_db.insert_user("anna", "hash", role="admin", display_name="Anna")
    fetched = await metadata_db.get_user_by_username("ANNA")  # NOCASE lookup
    assert fetched is not None and fetched["id"] == created["id"]
    assert await metadata_db.count_users() == 1
    await metadata_db.set_user_disabled(created["id"], True)
    assert (await metadata_db.get_user_by_id(created["id"]))["disabled"] == 1


# ── passwords ───────────────────────────────────────────────────────────


def test_password_hash_verify():
    from qualcoder_api.services.password import hash_password, needs_rehash, verify_password

    h = hash_password("s3cret!")
    assert h != "s3cret!" and h.startswith("$argon2")
    assert verify_password("s3cret!", h) is True
    assert verify_password("wrong", h) is False
    assert verify_password("x", "") is False  # passkey-only account
    assert needs_rehash(h) is False


def test_password_rejects_empty():
    from qualcoder_api.services.password import hash_password

    with pytest.raises(ValueError):
        hash_password("")


# ── tokens ──────────────────────────────────────────────────────────────


async def test_token_issue_verify_revoke(meta_db):
    from qualcoder_api.services import token_service

    user = await metadata_db.insert_user("bob", "h")
    raw, expires_at = await token_service.issue_token(user["id"])
    assert expires_at
    assert await token_service.verify_token(raw) == user["id"]
    await token_service.revoke_token(raw)
    assert await token_service.verify_token(raw) is None


async def test_token_unknown_garbage(meta_db):
    from qualcoder_api.services import token_service

    assert await token_service.verify_token("") is None
    assert await token_service.verify_token("not-a-token") is None


async def test_revoked_user_tokens_all_dead(meta_db):
    from qualcoder_api.services import token_service

    user = await metadata_db.insert_user("carol", "h")
    t1, _ = await token_service.issue_token(user["id"])
    t2, _ = await token_service.issue_token(user["id"])
    await token_service.revoke_all_for_user(user["id"])
    assert await token_service.verify_token(t1) is None
    assert await token_service.verify_token(t2) is None


# ── auth API ────────────────────────────────────────────────────────────


async def test_bootstrap_first_user_is_admin(client):
    token, user = await _bootstrap_admin(client)
    assert user["username"] == "admin" and user["role"] == "admin"
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["id"] == user["id"]


async def test_register_requires_admin_after_bootstrap(client):
    admin_token, _ = await _bootstrap_admin(client)
    # Unauthenticated → 401; authenticated NON-admin → 403.
    anon = await client.post(
        "/api/v1/auth/register", json={"username": "eve", "password": "pw-12345"}
    )
    assert anon.status_code == 401
    await client.post(
        "/api/v1/auth/register",
        json={"username": "bob", "password": "bob-pw-123"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    bob_login = await client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "bob-pw-123"}
    )
    bob_headers = {"Authorization": f"Bearer {bob_login.json()['token']}"}
    forbidden = await client.post(
        "/api/v1/auth/register",
        json={"username": "eve2", "password": "pw-12345"},
        headers=bob_headers,
    )
    assert forbidden.status_code == 403


async def test_admin_registers_second_user_then_login(client):
    admin_token, _ = await _bootstrap_admin(client)
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = await client.post(
        "/api/v1/auth/register",
        json={"username": "bob", "password": "bob-pw-123"},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["user"]["role"] == "user"
    dup = await client.post(
        "/api/v1/auth/register",
        json={"username": "BOB", "password": "x-1234567"},
        headers=headers,
    )
    assert dup.status_code == 409
    login = await client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "bob-pw-123"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["username"] == "bob"


async def test_login_bad_credentials(client):
    await _bootstrap_admin(client)
    for payload in (
        {"username": "admin", "password": "wrong"},
        {"username": "ghost", "password": "whatever-1"},
    ):
        r = await client.post("/api/v1/auth/login", json=payload)
        assert r.status_code == 401


async def test_logout_revokes_token(client):
    token, _ = await _bootstrap_admin(client)
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_refresh_rotates_token(client):
    old, _ = await _bootstrap_admin(client)
    headers = {"Authorization": f"Bearer {old}"}
    r = await client.post("/api/v1/auth/refresh", headers=headers)
    assert r.status_code == 200
    new = r.json()["token"]
    assert new != old
    ok = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new}"})
    assert ok.status_code == 200
    stale = await client.get("/api/v1/auth/me", headers=headers)
    assert stale.status_code == 401


async def test_me_requires_bearer(client):
    assert (await client.get("/api/v1/auth/me")).status_code in (401, 403)
    basic = await client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"})
    assert basic.status_code == 401


async def test_admin_disable_kills_tokens(client):
    admin_token, _ = await _bootstrap_admin(client)
    headers = {"Authorization": f"Bearer {admin_token}"}
    await client.post(
        "/api/v1/auth/register",
        json={"username": "mallory", "password": "mallory-123"},
        headers=headers,
    )
    mlogin = await client.post(
        "/api/v1/auth/login", json={"username": "mallory", "password": "mallory-123"}
    )
    mtoken = mlogin.json()["token"]
    target_id = mlogin.json()["user"]["id"]
    disable = await client.post(f"/api/v1/auth/users/{target_id}/disable", headers=headers)
    assert disable.status_code == 200
    dead = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {mtoken}"})
    assert dead.status_code == 401


async def test_register_validates_username(client):
    for bad in ("ab", "", "has space", "way-too-long-" + "x" * 40):
        r = await client.post(
            "/api/v1/auth/register", json={"username": bad, "password": "pw-12345"}
        )
        assert r.status_code == 422
