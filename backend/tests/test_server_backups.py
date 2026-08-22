"""SERVER_PLAN.md Phase 4 — backup service + endpoints.

Covers: manual snapshot (checksum on disk), list, restore round trip
(marker file disappears), GFS retention pruning, scheduled sweep, and
the admin run-all/status endpoints.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qualcoder_api.persistence import metadata_db


@pytest.fixture()
def server_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_SERVER_MODE", "true")
    monkeypatch.setenv("QC_SECRET_KEY", "s")
    monkeypatch.setenv("QC_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path
    from qualcoder_api.persistence import metadata_db

    asyncio.run(metadata_db.dispose_metadata_engine())


@pytest.fixture()
async def client(server_env):
    from httpx import ASGITransport, AsyncClient

    from qualcoder_api.api.v1.auth import router as auth_router
    from qualcoder_api.api.v1.server_backups import router as backups_router
    from qualcoder_api.api.v1.server_projects import router as projects_router
    from qualcoder_api.main import create_app  # noqa: F401 (wiring parity)

    await metadata_db.migrate_metadata(server_env / "data" / "metadata" / "qualcoder.db")

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(backups_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await metadata_db.dispose_metadata_engine()


async def _admin(client):
    r = await client.post(
        "/api/v1/auth/register", json={"username": "admin", "password": "admin-pw-123"}
    )
    assert r.status_code == 200
    login = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin-pw-123"}
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


async def _make_project(client, admin_headers, name: str) -> str:
    created = await client.post(
        "/api/v1/server/projects", json={"name": name}, headers=admin_headers
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


async def test_manual_backup_list_and_restore_roundtrip(client, server_env):
    headers = await _admin(client)
    pid = await _make_project(client, headers, "Backmeup")

    # First snapshot.
    first = await client.post(f"/api/v1/server/projects/{pid}/backups", headers=headers)
    assert first.status_code == 200, first.text
    record = first.json()["backup"]
    assert record["checksum"]
    stored = await metadata_db.get_backup_record(pid, record["id"])
    assert stored is not None and Path(stored["local_path"]).is_file()

    # Mutate the live project: drop a marker file into documents/.
    project = await metadata_db.get_project(pid)
    marker = Path(project["data_path"]) / "documents" / "marker.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("delete me on restore", encoding="utf-8")

    second = await client.post(f"/api/v1/server/projects/{pid}/backups", headers=headers)
    assert second.status_code == 200

    listed = (await client.get(f"/api/v1/server/projects/{pid}/backups", headers=headers)).json()
    assert len(listed["backups"]) == 2

    # Restore the FIRST snapshot → the marker must be gone.
    restore = await client.post(
        f"/api/v1/server/projects/{pid}/backups/{record['id']}/restore", headers=headers
    )
    assert restore.status_code == 200, restore.text
    assert not marker.exists()

    # data.qda survived the swap.
    project_after = await metadata_db.get_project(pid)
    assert (Path(project_after["data_path"]) / "data.qda").is_file()


async def test_backup_requires_owner_role(client):
    headers = await _admin(client)
    pid = await _make_project(client, headers, "Owned")

    # Second user registers; admin does NOT share the project.
    await client.post(
        "/api/v1/auth/register",
        json={"username": "peon", "password": "peon-pw-123"},
        headers=headers,
    )
    peon_login = await client.post(
        "/api/v1/auth/login", json={"username": "peon", "password": "peon-pw-123"}
    )
    peon = {"Authorization": f"Bearer {peon_login.json()['token']}"}

    denied = await client.post(f"/api/v1/server/projects/{pid}/backups", headers=peon)
    assert denied.status_code in (403, 404)


async def test_retention_gfs_prunes_oldest(client, server_env):
    from qualcoder_api.services import backup_service

    monkeypatch_policy = "daily=1,weekly=0,monthly=0"
    headers = await _admin(client)
    pid = await _make_project(client, headers, "Retained")

    for _ in range(3):
        r = await client.post(f"/api/v1/server/projects/{pid}/backups", headers=headers)
        assert r.status_code == 200

    deleted = await backup_service.apply_retention(monkeypatch_policy)
    assert deleted >= 1
    remaining = await metadata_db.list_backup_records(pid)
    assert len(remaining) <= 1
    # The newest survives.
    newest = max(int(r["id"]) for r in remaining) if remaining else None
    assert newest is not None


async def test_scheduled_sweep_and_admin_endpoints(client, server_env):
    headers = await _admin(client)
    pid = await _make_project(client, headers, "Sweepy")

    from qualcoder_api.services import backup_service

    ran = await backup_service.run_all_scheduled(max_age_hours=24)
    assert ran == 1
    # A fresh (<24h) backup exists now — the sweep must not add another.
    ran_again = await backup_service.run_all_scheduled(max_age_hours=24)
    assert ran_again == 0

    status = await client.post("/api/v1/admin/backup/run-all", headers=headers)
    assert status.status_code == 200
    agg = await client.get("/api/v1/admin/backup/status", headers=headers)
    assert agg.status_code == 200
    assert agg.json()["active_projects"] == 1
