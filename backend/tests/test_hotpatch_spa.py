"""Hotpatch SPA route tests.

The catch-all is always registered and resolves the hotpatch dir per
request, so a frontend patch installed into an already-running backend
serves immediately (no restart). Without a hotpatch it answers 404 exactly
like an unmounted route.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import hotpatch


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _seed_spa(root, index_body="<html>patched</html>"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(index_body, encoding="utf-8")
    (root / "assets").mkdir(exist_ok=True)
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return root


async def test_spa_route_404_without_hotpatch(client, monkeypatch):
    monkeypatch.setattr(hotpatch, "frontend_spa_dir", lambda: None)
    res = await client.get("/")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not Found"}


async def test_spa_serves_installed_hotpatch(client, tmp_path, monkeypatch):
    spa = _seed_spa(tmp_path / "current")
    monkeypatch.setattr(hotpatch, "frontend_spa_dir", lambda: spa)
    res = await client.get("/")
    assert res.status_code == 200
    assert "patched" in res.text
    asset = await client.get("/assets/app.js")
    assert asset.status_code == 200
    # SPA fallback for client-side routes.
    deep = await client.get("/settings/updates")
    assert deep.status_code == 200
    assert "patched" in deep.text


async def test_spa_never_shadows_api_or_docs(client, tmp_path, monkeypatch):
    spa = _seed_spa(tmp_path / "current")
    monkeypatch.setattr(hotpatch, "frontend_spa_dir", lambda: spa)
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    missing_api = await client.get("/api/v1/does-not-exist")
    assert missing_api.status_code == 404


async def test_spa_missing_index_404s(client, tmp_path, monkeypatch):
    empty = tmp_path / "current"
    empty.mkdir()
    monkeypatch.setattr(hotpatch, "frontend_spa_dir", lambda: empty)
    res = await client.get("/")
    assert res.status_code == 404


async def test_spa_never_shadows_later_api_routes(client):
    """Routes added after app creation (dynamically added test routes)
    still win: the catch-all excludes the api/ namespace at the route
    level, so matching falls through to them."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def _probe(request):
        return JSONResponse({"ok": True})

    route = Route("/api/v1/probe-spa-test", _probe, methods=["GET"])
    app.router.routes.append(route)
    try:
        res = await client.get("/api/v1/probe-spa-test")
        assert res.status_code == 200
        assert res.json() == {"ok": True}
    finally:
        app.router.routes.remove(route)
