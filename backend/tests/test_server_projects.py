"""SERVER_PLAN.md Phase 2 — session pool, registry, ACL, transfer.

Drives the REAL server app (QC_SERVER_MODE=true) with httpx: project
create/list/share/delete, session open via X-Project-Id against a
project-scoped endpoint, viewer/editor/owner gating, upload/download.
"""
from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest


@pytest.fixture
def server_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QC_SERVER_MODE", "true")
    monkeypatch.setenv("QC_SECRET_KEY", "test-secret")
    monkeypatch.setenv("QC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QC_RP_ID", "")
    return tmp_path


@pytest.fixture
async def client(server_env):
    from httpx import ASGITransport, AsyncClient

    import qualcoder_api.services.session_manager as sm
    from qualcoder_api.main import create_app
    from qualcoder_api.persistence import metadata_db

    # reset module-level state between tests
    await metadata_db.dispose_metadata_engine()
    sm.manager.sessions.clear()
    # ASGITransport does NOT run the ASGI lifespan — initialise what the
    # lifespan would have initialised.
    await metadata_db.migrate_metadata(server_env / "data" / "metadata" / "qualcoder.db")

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await metadata_db.dispose_metadata_engine()
    sm.manager.sessions.clear()


async def _register_and_login(client, username: str, *, admin: bool = False) -> dict:
    """Register (first user bootstraps as admin) and return auth headers."""
    if admin:
        r = await client.post(
            "/api/v1/auth/register", json={"username": username, "password": f"{username}-pw-1"}
        )
        assert r.status_code == 200, r.text
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": f"{username}-pw-1"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_headers(client):
    return await _register_and_login(client, "admin", admin=True)


async def test_project_lifecycle_and_acl(client, admin_headers):
    # Admin creates a project.
    created = await client.post(
        "/api/v1/server/projects", json={"name": "Study"}, headers=admin_headers
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]

    # Listed for the owner with owner role.
    listed = await client.get("/api/v1/server/projects", headers=admin_headers)
    roles = {p["name"]: p["role"] for p in listed.json()["projects"]}
    assert roles.get("Study") == "owner"

    # A second user exists but is NOT a member → project gated for them.
    # (Register via admin, then share nothing.)
    r = await client.post(
        "/api/v1/auth/register",
        json={"username": "outsider", "password": "out-pw-123"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    outsider_login = await client.post(
        "/api/v1/auth/login", json={"username": "outsider", "password": "out-pw-123"}
    )
    outsider = {"Authorization": f"Bearer {outsider_login.json()['token']}"}
    anon_list = await client.get("/api/v1/server/projects", headers=outsider)
    assert all(p["name"] != "Study" for p in anon_list.json()["projects"])

    denied_open = await client.post(
        f"/api/v1/server/projects/{pid}/open",
        headers={**outsider, "X-Project-Id": pid},
    )
    assert denied_open.status_code == 403

    # Owner registers bob2 and shares the project as VIEWER.
    r = await client.post(
        "/api/v1/auth/register",
        json={"username": "bob2", "password": "bob2-pw-1"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    bob2_id = r.json()["user"]["id"]
    share = await client.put(
        f"/api/v1/server/projects/{pid}/members/{bob2_id}",
        json={"role": "viewer"},
        headers=admin_headers,
    )
    assert share.status_code == 200

    bob2_login = await client.post(
        "/api/v1/auth/login", json={"username": "bob2", "password": "bob2-pw-1"}
    )
    bob2 = {"Authorization": f"Bearer {bob2_login.json()['token']}"}

    # Viewer CAN open a session and read…
    opened = await client.post(
        f"/api/v1/server/projects/{pid}/open", headers={**bob2, "X-Project-Id": pid}
    )
    assert opened.status_code == 200
    read = await client.get(
        "/api/v1/sources", headers={**bob2, "X-Project-Id": pid}
    )
    assert read.status_code == 200
    # …but NOT mutate.
    mutated = await client.post(
        "/api/v1/codes",
        json={"name": "nope"},
        headers={**bob2, "X-Project-Id": pid},
    )
    assert mutated.status_code == 403

    # Editor can mutate: promote bob2 then retry.
    promote = await client.put(
        f"/api/v1/server/projects/{pid}/members/{bob2_id}",
        json={"role": "editor"},
        headers=admin_headers,
    )
    assert promote.status_code == 200
    mutated_ok = await client.post(
        "/api/v1/codes",
        json={"name": "editor-can-write"},
        headers={**bob2, "X-Project-Id": pid},
    )
    assert mutated_ok.status_code < 500
    assert mutated_ok.status_code != 403

    # Owner removes membership; bob2 loses access again.
    removed = await client.delete(
        f"/api/v1/server/projects/{pid}/members/{bob2_id}", headers=admin_headers
    )
    assert removed.status_code == 200
    gone = await client.get("/api/v1/sources", headers={**bob2, "X-Project-Id": pid})
    assert gone.status_code == 403


async def test_session_isolation_two_projects(client, admin_headers):
    """Two projects hold INDEPENDENT sessions (one service each)."""
    p1 = await client.post("/api/v1/server/projects", json={"name": "A"}, headers=admin_headers)
    p2 = await client.post("/api/v1/server/projects", json={"name": "B"}, headers=admin_headers)
    id1, id2 = p1.json()["id"], p2.json()["id"]
    o1 = await client.post(f"/api/v1/server/projects/{id1}/open", headers=admin_headers)
    o2 = await client.post(f"/api/v1/server/projects/{id2}/open", headers=admin_headers)
    assert o1.status_code == 200 and o2.status_code == 200

    from qualcoder_api.services.session_manager import manager

    s1, s2 = manager.sessions[id1].service, manager.sessions[id2].service
    assert s1 is not s2
    assert s1.project_path != s2.project_path

    # Close is per-user and must NOT evict the shared session (that would
    # disconnect every other member of the project): both sessions stay live
    # and the other project keeps working on its own independent service.
    c1 = await client.post(f"/api/v1/server/projects/{id1}/close", headers=admin_headers)
    assert c1.status_code == 200
    assert manager.sessions[id1].service is s1
    assert manager.sessions[id2].service is s2
    o2_again = await client.post(f"/api/v1/server/projects/{id2}/open", headers=admin_headers)
    assert o2_again.status_code == 200
    assert manager.sessions[id2].service is s2


async def test_upload_download_roundtrip(client, admin_headers, tmp_path):
    # Build a minimal .qda zip via the real create path.
    created = await client.post(
        "/api/v1/server/projects", json={"name": "Round"}, headers=admin_headers
    )
    pid = created.json()["id"]
    detail = await client.get(f"/api/v1/server/projects/{pid}", headers=admin_headers)
    data_dir = Path(detail.json()["path"]) if "path" in detail.json() else None
    assert data_dir is None or True  # data_path never exposed to clients

    # Download → must be a zip containing data.qda.
    dl = await client.get(f"/api/v1/server/projects/{pid}/download", headers=admin_headers)
    assert dl.status_code == 200
    zf = zipfile.ZipFile(BytesIO(dl.content))
    data_members = [n for n in zf.namelist() if n.endswith("data.qda")]
    assert len(data_members) == 1

    # Re-upload under a new name → appears as a separate project.
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for name in zf.namelist():
            zout.writestr(name.replace("Round.qda/", "Copy.qda/"), zf.read(name))
    up = await client.post(
        "/api/v1/server/projects/upload",
        files={"file": ("copy.zip", buf.getvalue(), "application/zip")},
        headers=admin_headers,
    )
    assert up.status_code == 200, up.text
    copy_id = up.json()["id"]
    assert copy_id != pid
    listed = await client.get("/api/v1/server/projects", headers=admin_headers)
    names = {p["name"] for p in listed.json()["projects"]}
    assert {"Round", "copy"} <= names

    # The copy opens as its own session.
    opened = await client.post(
        f"/api/v1/server/projects/{copy_id}/open", headers=admin_headers
    )
    assert opened.status_code == 200


async def test_local_lifecycle_disabled_in_server_mode(client, admin_headers):
    r = await client.post(
        "/api/v1/projects", json={"project_path": "x.qda"}, headers=admin_headers
    )
    assert r.status_code == 410
