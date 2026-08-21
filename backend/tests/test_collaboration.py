"""Collaboration (Golden Master + sandbox) mode tests.

Exercises project_service mode transitions end-to-end: activation, close /
reopen in collaboration mode, consolidation, and revert to single-coder.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
from sqlalchemy import text

from qualcoder_api.persistence.repositories import CodeRepository
from qualcoder_api.services import project_marker, sandbox, sync
from qualcoder_api.services.project_service import ProjectService


@pytest.fixture
async def collab_svc(tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    s = ProjectService()
    await s.create_project(str(tmp_path / "C.qda"), codername="alice")
    # Two real coders so the activation gate passes.
    async with s.session_factory() as session:
        for name in ("alice", "bob"):
            await session.execute(
                text("INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"),
                {"n": name},
            )
        await session.commit()
    user_settings.save_sync_settings(True)
    yield s, str(tmp_path / "C.qda")
    await s.close_project()
    marker = project_marker.read_marker(str(tmp_path / "C.qda"))
    if marker:
        sandbox.remove_sandbox(marker["uuid"])


async def test_activate_writes_marker_and_sandbox(collab_svc):
    svc, path = collab_svc
    sync.set_current_user("alice")
    result = await svc.activate_collaboration(codername="alice")
    assert result["ok"] is True
    assert svc.collaboration_mode() is True
    assert svc.uuid
    assert project_marker.marker_exists(path) is True
    assert sandbox.sandbox_exists(svc.uuid) is True
    # Idempotent.
    again = await svc.activate_collaboration(codername="alice")
    assert again["ok"] is False


async def test_activate_requires_two_coders(tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "Solo.qda"), codername="solo")
    user_settings.save_sync_settings(True)
    try:
        sync.set_current_user("solo")
        result = await svc.activate_collaboration(codername="solo")
        assert result["ok"] is False
        assert "coder" in result["reason"]
    finally:
        await svc.close_project()


async def test_close_consolidates_and_reopens_in_collab(collab_svc):
    svc, path = collab_svc
    sync.set_current_user("alice")
    await svc.activate_collaboration(codername="alice")
    async with svc.session_factory() as session:
        await CodeRepository(session).add_code(name="fear", owner="alice")
    await svc.close_project()

    # The cold archive now holds the code.
    conn = await aiosqlite.connect(Path(path) / "data.qda")
    cur = await conn.cursor()
    await cur.execute("SELECT COUNT(*) FROM code_name")
    assert (await cur.fetchone())[0] == 1
    await conn.close()

    # Reopen: collaboration mode, sandbox is the live DB, code present.
    opener = ProjectService()
    result = await opener.open_project(path, codername="alice")
    try:
        assert result.ok is True
        assert opener.collaboration_mode() is True
        async with opener.session_factory() as session:
            count = (await session.execute(text("SELECT COUNT(*) FROM code_name"))).scalar()
        assert count == 1
    finally:
        await opener.close_project()
    marker = project_marker.read_marker(path)
    if marker:
        sandbox.remove_sandbox(marker["uuid"])


async def test_revert_returns_to_single_coder(collab_svc):
    svc, path = collab_svc
    sync.set_current_user("alice")
    await svc.activate_collaboration(codername="alice")
    result = await svc.revert_collaboration()
    assert result["ok"] is True
    assert svc.collaboration_mode() is False
    assert project_marker.marker_exists(path) is False
    # data.qda is the live DB again.
    conn = await aiosqlite.connect(Path(path) / "data.qda")
    cur = await conn.cursor()
    await cur.execute("SELECT COUNT(*) FROM project")
    assert (await cur.fetchone())[0] == 1
    await conn.close()


# ── API level ────────────────────────────────────────────────────────────

@pytest.fixture
async def api_collab(tmp_path, monkeypatch):
    """API client with an open project seeded for collaboration activation."""
    from httpx import ASGITransport, AsyncClient

    from qualcoder_api.main import app, service
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "api-collab.qda"
        res = await c.post(
            "/api/v1/projects",
            json={"project_path": str(target), "codername": "alice"},
        )
        assert res.status_code == 200, res.text
        # Seed a second coder + enable sync through the shared service.
        async with service.session_factory() as session:
            for name in ("alice", "bob"):
                await session.execute(
                    text("INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"),
                    {"n": name},
                )
            await session.commit()
        user_settings.save_sync_settings(True)
        yield c, str(target), service
        await c.post("/api/v1/projects/close")
        marker = project_marker.read_marker(str(target))
        if marker:
            sandbox.remove_sandbox(marker["uuid"])


async def test_api_mode_and_activate_revert(api_collab):
    c, _target, _service = api_collab
    sync.set_current_user("alice")

    # Initially single mode.
    res = await c.get("/api/v1/projects/mode")
    assert res.status_code == 200
    assert res.json()["mode"] == "single"

    # Activate.
    res = await c.post("/api/v1/projects/activate-collaboration")
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    res = await c.get("/api/v1/projects/mode")
    assert res.json()["mode"] == "collaboration"

    # Revert.
    res = await c.post("/api/v1/projects/revert-collaboration")
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    res = await c.get("/api/v1/projects/mode")
    assert res.json()["mode"] == "single"


async def test_api_activate_409_without_two_coders(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from qualcoder_api.main import app
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "api-solo.qda"
        await c.post(
            "/api/v1/projects",
            json={"project_path": str(target), "codername": "solo"},
        )
        user_settings.save_sync_settings(True)
        res = await c.post("/api/v1/projects/activate-collaboration")
        assert res.status_code == 409, res.text
        assert "coder" in res.json()["detail"]
        await c.post("/api/v1/projects/close")
