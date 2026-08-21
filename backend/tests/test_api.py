"""API tests — health and project lifecycle endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.core import APP_VERSION
from qualcoder_api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client):
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["version"] == APP_VERSION


async def test_unhandled_exception_500_has_cors_headers_and_json_body():
    """An unhandled backend exception must reach the client as a readable
    JSON 500 WITH CORS headers.

    Starlette's ServerErrorMiddleware handles unhandled exceptions outside
    the CORSMiddleware, so the plain 500 it produces lacks the CORS headers
    and the frontend browser masks it as "Failed to fetch". The catch-all
    handler must echo the allowed origin itself.
    """
    async def _boom(request) -> None:
        raise RuntimeError("boom-test")

    app.router.add_route("/api/v1/probe-raise", _boom, methods=["GET"])

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Packaged webview origin: CORS header echoed, JSON body readable.
        res = await c.get(
            "/api/v1/probe-raise", headers={"Origin": "http://tauri.localhost"}
        )
        assert res.status_code == 500
        assert res.headers["access-control-allow-origin"] == "http://tauri.localhost"
        assert res.headers["vary"] == "Origin"
        body = res.json()
        assert "detail" in body
        assert body["detail"].startswith("internal error: RuntimeError")
        assert "boom-test" in body["detail"]

        # Dev origin works too.
        res = await c.get(
            "/api/v1/probe-raise", headers={"Origin": "http://localhost:5173"}
        )
        assert res.status_code == 500
        assert res.headers["access-control-allow-origin"] == "http://localhost:5173"

        # A non-browser call (no Origin header) gets no CORS header, exactly
        # like CORSMiddleware's behavior on normal responses.
        res = await c.get("/api/v1/probe-raise")
        assert res.status_code == 500
        assert "access-control-allow-origin" not in res.headers
        assert res.json()["detail"].startswith("internal error:")


async def test_create_then_summary(client, tmp_path, app_version):
    target = tmp_path / "api.qda"
    res = await client.post(
        "/api/v1/projects",
        json={"project_path": str(target), "codername": "api-tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["project_name"] == "api.qda"

    res = await client.get("/api/v1/projects/current/summary")
    assert res.status_code == 200
    assert res.json()["summary"]["files_count"] == 0
    assert res.json()["summary"]["codes_count"] == 0


async def test_close_then_summary_conflict(client, tmp_path):
    target = tmp_path / "api2.qda"
    await client.post("/api/v1/projects", json={"project_path": str(target)})
    res = await client.post("/api/v1/projects/close")
    assert res.status_code == 200
    res = await client.get("/api/v1/projects/current/summary")
    assert res.status_code == 409


async def test_open_after_close_roundtrip(client, tmp_path):
    target = tmp_path / "api3.qda"
    created = await client.post("/api/v1/projects", json={"project_path": str(target)})
    assert created.status_code == 200
    await client.post("/api/v1/projects/close")

    opened = await client.post(
        "/api/v1/projects/open",
        json={"project_path": str(target), "codername": "api-tester"},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["ok"] is True
    assert opened.json()["migrations_applied"] == []

    await client.post("/api/v1/projects/close")


async def test_open_missing_project_returns_error(client, tmp_path):
    res = await client.post(
        "/api/v1/projects/open",
        json={"project_path": str(tmp_path / "ghost.qda")},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is False
    assert res.json()["error"] != ""


async def test_open_locked_project_reports_lock_user(client, tmp_path):
    target = tmp_path / "api4.qda"
    await client.post("/api/v1/projects", json={"project_path": str(target)})
    await client.post("/api/v1/projects/close")

    # simulate a foreign presence entry from a dead instance (stale — the
    # registry prunes it; the open succeeds)
    lock = target / "project_in_use.lock"
    lock.write_text("someone-else\n9999999999\n", encoding="utf-8")

    res = await client.post(
        "/api/v1/projects/open", json={"project_path": str(target)}
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


async def test_recent_projects_records_created(client, tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    # redirect settings to a temp file so the test is hermetic
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")

    res = await client.get("/api/v1/projects")
    assert res.json()["recent"] == []

    target = tmp_path / "recent.qda"
    await client.post("/api/v1/projects", json={"project_path": str(target)})

    res = await client.get("/api/v1/projects")
    recent = res.json()["recent"]
    assert str(target) in recent
    assert recent[0] == str(target)
    await client.post("/api/v1/projects/close")
