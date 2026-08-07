"""API details endpoints — code details and source details aggregation."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "details.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


# ----------------------------------------------------------------------
# GET /api/v1/codes/{cid}/details
# ----------------------------------------------------------------------

async def test_code_details_endpoint(project_client):
    client, _ = project_client
    outer = (await client.post("/api/v1/codes/categories", json={"name": "Outer"})).json()
    inner = (
        await client.post(
            "/api/v1/codes/categories",
            json={"name": "Inner", "supercatid": outer["catid"]},
        )
    ).json()
    code = (
        await client.post(
            "/api/v1/codes",
            json={"name": "cd", "catid": inner["catid"], "color": "#FF0000"},
        )
    ).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("cd.txt", "alpha beta", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    created = await client.post(
        "/api/v1/codings/text",
        json={"cid": code["cid"], "fid": fid, "seltext": "alpha", "pos0": 0, "pos1": 5},
    )
    assert created.status_code == 201, created.text

    res = await client.get(f"/api/v1/codes/{code['cid']}/details")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"]["cid"] == code["cid"]
    assert body["code"]["name"] == "cd"
    assert body["code"]["catid"] == inner["catid"]
    assert body["code"]["color"] == "#FF0000"
    assert body["category_path"] == ["Outer", "Inner"]
    assert body["coding_count"] == 1
    assert body["file_count"] == 1
    assert len(body["recent_examples"]) == 1
    example = body["recent_examples"][0]
    assert example["ctid"] == created.json()["ctid"]
    assert example["file_name"] == "cd.txt"
    assert example["seltext"] == "alpha"
    assert example["pos0"] == 0
    assert example["pos1"] == 5


async def test_code_details_empty_and_404(project_client):
    client, _ = project_client
    code = (await client.post("/api/v1/codes", json={"name": "lonely"})).json()
    res = await client.get(f"/api/v1/codes/{code['cid']}/details")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["category_path"] == []
    assert body["coding_count"] == 0
    assert body["file_count"] == 0
    assert body["recent_examples"] == []

    assert (await client.get("/api/v1/codes/99999/details")).status_code == 404


# ----------------------------------------------------------------------
# GET /api/v1/sources/{id}/details
# ----------------------------------------------------------------------

async def test_source_details_endpoint(project_client):
    client, _ = project_client
    a = (await client.post("/api/v1/codes", json={"name": "A", "color": "#111111"})).json()
    b = (await client.post("/api/v1/codes", json={"name": "B", "color": "#222222"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("sd.txt", "one two three", "text/plain")}
    )
    sid = (await client.get("/api/v1/sources")).json()[0]["id"]

    await client.post(
        "/api/v1/codings/text",
        json={"cid": a["cid"], "fid": sid, "seltext": "one", "pos0": 0, "pos1": 3},
    )
    await client.post(
        "/api/v1/codings/text",
        json={"cid": b["cid"], "fid": sid, "seltext": "two", "pos0": 4, "pos1": 7},
    )
    await client.post(
        "/api/v1/codings/text",
        json={"cid": a["cid"], "fid": sid, "seltext": "three", "pos0": 8, "pos1": 13},
    )

    case = (await client.post("/api/v1/cases", json={"name": "C1"})).json()
    link = await client.post(
        f"/api/v1/cases/{case['caseid']}/files", json={"fid": sid, "owner": "tester"}
    )
    assert link.status_code == 201

    await client.post(
        "/api/v1/attributes/types",
        json={"name": "Note", "case_or_file": "file", "value_type": "text"},
    )
    setv = await client.put(
        f"/api/v1/attributes/values/Note?attr_type=file&entity_id={sid}",
        json={"value": "hello", "owner": "tester"},
    )
    assert setv.status_code == 200, setv.text

    res = await client.get(f"/api/v1/sources/{sid}/details")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"]["id"] == sid
    assert body["source"]["name"] == "sd.txt"
    assert body["source"]["media_type"] == "text"
    assert body["text_codings"] == 3
    assert body["image_codings"] == 0
    assert body["av_codings"] == 0
    assert body["codes_used"] == [
        {"cid": a["cid"], "name": "A", "color": "#111111", "count": 2},
        {"cid": b["cid"], "name": "B", "color": "#222222", "count": 1},
    ]
    assert any(c["caseid"] == case["caseid"] and c["name"] == "C1" for c in body["cases"])
    assert any(
        at["name"] == "Note" and at["value"] == "hello" and at["attr_type"] == "file"
        for at in body["attributes"]
    )


async def test_source_details_404(project_client):
    client, _ = project_client
    assert (await client.get("/api/v1/sources/99999/details")).status_code == 404
