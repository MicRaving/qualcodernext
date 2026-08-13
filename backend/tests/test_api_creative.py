"""API tests — creative coding scratchpad (creative_item + promote)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.creative import router as creative_router
from qualcoder_api.main import app


def _ensure_creative_wired() -> None:
    """Mount the creative router when the v1 router does not carry it yet.

    The router is wired into ``api/v1/router.py`` by the supervisor; until
    then this test file mounts it itself so the suite runs standalone.
    """
    if any(getattr(route, "path", "") == "/api/v1/creative" for route in app.router.routes):
        return
    app.include_router(creative_router, prefix="/api/v1")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    _ensure_creative_wired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "creative.qda"
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


async def test_creative_crud(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    # Sourced item (a quote with a span).
    created = await client.post(
        "/api/v1/creative",
        json={"text": "alpha beta", "source_fid": fid, "pos0": 0, "pos1": 10, "note": "keep me", "owner": "tester"},
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["id"] > 0
    assert item["text"] == "alpha beta"
    assert item["source_name"] == "a.txt"
    assert item["source_text"] == "alpha beta"
    assert item["note"] == "keep me"
    assert item["owner"] == "tester"

    # Unsourced idea (positions nullable).
    idea = await client.post(
        "/api/v1/creative",
        json={"text": "free idea", "note": ""},
    )
    assert idea.status_code == 201, idea.text
    assert idea.json()["source_fid"] is None
    assert idea.json()["source_name"] == ""

    # List: newest first, excerpts attached.
    listed = (await client.get("/api/v1/creative")).json()
    assert [i["id"] for i in listed] == [idea.json()["id"], item["id"]]
    assert listed[1]["source_name"] == "a.txt"
    assert listed[1]["source_text"] == "alpha beta"
    assert listed[0]["source_text"] == ""

    # PATCH text and note.
    patched = await client.patch(
        f"/api/v1/creative/{item['id']}",
        json={"text": "alpha beta gamma", "note": "edited"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["text"] == "alpha beta gamma"
    assert patched.json()["note"] == "edited"

    # PATCH with no fields is a no-op returning the current row.
    noop = await client.patch(f"/api/v1/creative/{item['id']}", json={})
    assert noop.status_code == 200
    assert noop.json()["text"] == "alpha beta gamma"

    # Delete removes it; deleting twice yields 404.
    assert (await client.delete(f"/api/v1/creative/{item['id']}")).status_code == 204
    assert (await client.get("/api/v1/creative")).json()[0]["id"] == idea.json()["id"]
    assert (await client.delete(f"/api/v1/creative/{item['id']}")).status_code == 404

    # Unknown item for PATCH yields 404.
    assert (await client.patch("/api/v1/creative/9999", json={"text": "x"})).status_code == 404


async def test_creative_validation(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    # Empty text.
    res = await client.post("/api/v1/creative", json={"text": "  "})
    assert res.status_code == 422

    # pos1 <= pos0.
    res = await client.post("/api/v1/creative", json={"text": "q", "source_fid": fid, "pos0": 6, "pos1": 3})
    assert res.status_code == 422

    # Positions beyond the source text length.
    res = await client.post("/api/v1/creative", json={"text": "q", "source_fid": fid, "pos0": 0, "pos1": 100})
    assert res.status_code == 422

    # Negative positions.
    res = await client.post("/api/v1/creative", json={"text": "q", "source_fid": fid, "pos0": -2, "pos1": 5})
    assert res.status_code == 422

    # Nonexistent source.
    res = await client.post("/api/v1/creative", json={"text": "q", "source_fid": 999, "pos0": 0, "pos1": 5})
    assert res.status_code == 422

    # Positions without a source.
    res = await client.post("/api/v1/creative", json={"text": "q", "pos0": 0, "pos1": 5})
    assert res.status_code == 422

    # Empty text on PATCH.
    item = (await client.post("/api/v1/creative", json={"text": "ok"})).json()
    res = await client.patch(f"/api/v1/creative/{item['id']}", json={"text": "  "})
    assert res.status_code == 422

    # A valid sourced item is still accepted afterwards.
    res = await client.post("/api/v1/creative", json={"text": "beta", "source_fid": fid, "pos0": 6, "pos1": 10})
    assert res.status_code == 201, res.text


async def test_promote_creates_code_and_coding(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    # Sourced item: promoting codes the referenced span with the new code.
    item = (
        await client.post(
            "/api/v1/creative",
            json={"text": "alpha beta", "source_fid": fid, "pos0": 0, "pos1": 10, "note": "quote note"},
        )
    ).json()
    res = await client.post(f"/api/v1/creative/{item['id']}/promote", json={"code_name": "Theme A"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cid"] > 0
    assert body["ctid"] > 0

    # The code exists with the right name.
    tree = (await client.get("/api/v1/codes")).json()
    codes = [c for c in tree if c["kind"] == "code" and c["id"] == body["cid"]]
    assert len(codes) == 1
    assert codes[0]["name"] == "Theme A"

    # The coding covers the span with the item text as seltext.
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert [c["ctid"] for c in codings] == [body["ctid"]]
    coding = codings[0]
    assert coding["cid"] == body["cid"]
    assert coding["seltext"] == "alpha beta"
    assert coding["pos0"] == 0
    assert coding["pos1"] == 10

    # Unsourced item: promote creates the code without a coding.
    idea = (await client.post("/api/v1/creative", json={"text": "free idea"})).json()
    res = await client.post(f"/api/v1/creative/{idea['id']}/promote", json={"code_name": "Theme B"})
    assert res.status_code == 200, res.text
    assert res.json()["ctid"] is None

    # A category can be attached to the new code.
    cat = (await client.post("/api/v1/codes/categories", json={"name": "Bucket"})).json()
    res = await client.post(
        f"/api/v1/creative/{idea['id']}/promote", json={"code_name": "Theme C", "catid": cat["catid"]}
    )
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    c3 = next(c for c in tree if c["kind"] == "code" and c["id"] == res.json()["cid"])
    assert c3["parent_id"] == cat["catid"]

    # Duplicate code name → 409 (like POST /codes).
    res = await client.post(f"/api/v1/creative/{idea['id']}/promote", json={"code_name": "theme a"})
    assert res.status_code == 409

    # Missing item → 404; empty name → 422.
    assert (await client.post("/api/v1/creative/9999/promote", json={"code_name": "X"})).status_code == 404
    assert (
        await client.post(f"/api/v1/creative/{idea['id']}/promote", json={"code_name": "  "})
    ).status_code == 422


async def test_creative_audit_rows(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    created = await client.post(
        "/api/v1/creative",
        json={"text": "quote", "source_fid": fid, "pos0": 0, "pos1": 5, "owner": "tester"},
    )
    item_id = created.json()["id"]

    rows = (await client.get("/api/v1/audit", params={"action": "creative.create"})).json()["rows"]
    assert len(rows) == 1
    create_row = rows[0]
    assert create_row["user"] == "tester"
    assert create_row["entity"] == "creative_item"
    assert create_row["entity_id"] == item_id
    assert create_row["source_id"] == fid
    assert create_row["detail"]["pos0"] == 0

    await client.patch(f"/api/v1/creative/{item_id}", json={"note": "updated"})
    rows = (await client.get("/api/v1/audit", params={"action": "creative.update"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == item_id
    assert rows[0]["detail"]["note"] == "updated"

    await client.post(f"/api/v1/creative/{item_id}/promote", json={"code_name": "FromQuote"})
    rows = (await client.get("/api/v1/audit", params={"action": "creative.promote"})).json()["rows"]
    assert len(rows) == 1
    promote_row = rows[0]
    assert promote_row["entity_id"] == item_id
    assert promote_row["source_id"] == fid
    assert promote_row["detail"]["code_name"] == "FromQuote"
    assert promote_row["detail"]["cid"] > 0
    assert promote_row["detail"]["ctid"] > 0

    await client.delete(f"/api/v1/creative/{item_id}")
    rows = (await client.get("/api/v1/audit", params={"action": "creative.delete"})).json()["rows"]
    assert len(rows) == 1
    delete_row = rows[0]
    assert delete_row["entity_id"] == item_id
    assert delete_row["source_id"] == fid
    assert delete_row["detail"]["text"] == "quote"
