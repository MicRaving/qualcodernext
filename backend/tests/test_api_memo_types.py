"""API tests — memo types (MAXQDA-style) on code and file memos.

``memo_type`` is an optional free-form type id ("" default, ≤200 chars) on
``code_name`` and ``source``; the frontend maps ids to icons. The PATCH
endpoints accept it, GET /codes and GET /sources expose it.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "memotypes.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def _one_source(client) -> int:
    """Import one text file and return its id."""
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("a.txt", "alpha beta gamma", "text/plain")}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _one_code(client) -> int:
    """Create one code and return its cid."""
    res = await client.post("/api/v1/codes", json={"name": "Theme A", "owner": "tester"})
    assert res.status_code == 201, res.text
    return res.json()["cid"]


async def test_memo_type_defaults_empty(project_client):
    client, _ = project_client
    fid = await _one_source(client)
    cid = await _one_code(client)

    # Sources list: memo_type defaults to "".
    sources = (await client.get("/api/v1/sources")).json()
    by_id = {s["id"]: s for s in sources}
    assert "memo_type" in by_id[fid]
    assert by_id[fid]["memo_type"] == ""

    # Code tree: memo_type defaults to "".
    tree = (await client.get("/api/v1/codes")).json()
    code = next(c for c in tree if c["kind"] == "code" and c["id"] == cid)
    assert "memo_type" in code
    assert code["memo_type"] == ""

    # Code details embed the type too.
    details = (await client.get(f"/api/v1/codes/{cid}/details")).json()
    assert details["code"]["memo_type"] == ""

    # Source details embed the type too.
    details = (await client.get(f"/api/v1/sources/{fid}/details")).json()
    assert details["source"]["memo_type"] == ""


async def test_code_memo_type_roundtrip(project_client):
    client, _ = project_client
    cid = await _one_code(client)

    # PATCH memo_type alone persists.
    patched = await client.patch(f"/api/v1/codes/{cid}", json={"memo_type": "idea"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["memo_type"] == "idea"

    # GET /codes exposes it.
    tree = (await client.get("/api/v1/codes")).json()
    code = next(c for c in tree if c["kind"] == "code" and c["id"] == cid)
    assert code["memo_type"] == "idea"

    # Switching the type overwrites; memo stays untouched.
    patched = await client.patch(f"/api/v1/codes/{cid}", json={"memo_type": "theory", "memo": "t"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["memo_type"] == "theory"
    assert patched.json()["memo"] == "t"
    assert (await client.get("/api/v1/codes")).json()  # list still loads

    # Clearing back to "" works (empty string is a valid explicit value).
    patched = await client.patch(f"/api/v1/codes/{cid}", json={"memo_type": ""})
    assert patched.status_code == 200, patched.text
    assert patched.json()["memo_type"] == ""


async def test_source_memo_type_roundtrip(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    # PATCH memo_type alone persists.
    patched = await client.patch(f"/api/v1/sources/{fid}", json={"memo_type": "interview"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["memo_type"] == "interview"

    # GET /sources exposes it.
    sources = (await client.get("/api/v1/sources")).json()
    by_id = {s["id"]: s for s in sources}
    assert by_id[fid]["memo_type"] == "interview"

    # Together with a memo.
    patched = await client.patch(
        f"/api/v1/sources/{fid}", json={"memo_type": "observation", "memo": "m"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["memo_type"] == "observation"
    assert patched.json()["memo"] == "m"

    # Clearing back to "" works.
    patched = await client.patch(f"/api/v1/sources/{fid}", json={"memo_type": ""})
    assert patched.status_code == 200, patched.text
    assert patched.json()["memo_type"] == ""


async def test_memo_type_length_cap(project_client):
    client, _ = project_client
    cid = await _one_code(client)
    fid = await _one_source(client)
    too_long = "x" * 201

    # 201 chars are rejected on both endpoints (422), 200 are accepted.
    assert (
        await client.patch(f"/api/v1/codes/{cid}", json={"memo_type": too_long})
    ).status_code == 422
    assert (
        await client.patch(f"/api/v1/sources/{fid}", json={"memo_type": too_long})
    ).status_code == 422

    ok = "y" * 200
    assert (
        await client.patch(f"/api/v1/codes/{cid}", json={"memo_type": ok})
    ).status_code == 200
    assert (
        await client.patch(f"/api/v1/sources/{fid}", json={"memo_type": ok})
    ).status_code == 200


async def test_memo_type_unknown_entity_404(project_client):
    client, _ = project_client
    assert (
        await client.patch("/api/v1/codes/9999", json={"memo_type": "idea"})
    ).status_code == 404
    assert (
        await client.patch("/api/v1/sources/9999", json={"memo_type": "idea"})
    ).status_code == 404
