"""API tests — code sets (MAXQDA-style named subsets of codes)."""

from __future__ import annotations

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.code_sets import router as code_sets_router
from qualcoder_api.main import app


def _ensure_code_sets_wired() -> None:
    """Mount the code-sets router when the v1 router does not carry it yet.

    The router is wired into ``api/v1/router.py`` by the supervisor; until
    then this test file mounts it itself so the suite runs standalone.
    """
    if any(getattr(route, "path", "") == "/api/v1/code-sets" for route in app.router.routes):
        return
    app.include_router(code_sets_router, prefix="/api/v1")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    _ensure_code_sets_wired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "codesets.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def _three_codes(client) -> list[int]:
    """Create three codes and return their cids."""
    cids = []
    for name in ("Alpha", "Beta", "Gamma"):
        res = await client.post("/api/v1/codes", json={"name": name, "owner": "tester"})
        assert res.status_code == 201, res.text
        cids.append(res.json()["cid"])
    return cids


async def test_code_set_crud(project_client):
    client, _ = project_client

    # Empty list initially.
    assert (await client.get("/api/v1/code-sets")).json() == []

    # Create.
    created = await client.post("/api/v1/code-sets", json={"name": "Core themes", "owner": "tester"})
    assert created.status_code == 201, created.text
    set_body = created.json()
    set_id = set_body["id"]
    assert set_body["name"] == "Core themes"
    assert set_body["owner"] == "tester"
    assert set_body["created"]
    assert set_body["member_count"] == 0

    # List shows the set with a member count.
    listed = (await client.get("/api/v1/code-sets")).json()
    assert [s["name"] for s in listed] == ["Core themes"]
    assert listed[0]["member_count"] == 0

    # Rename.
    renamed = await client.patch(f"/api/v1/code-sets/{set_id}", json={"name": "Key themes"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Key themes"

    # Unknown id → 404 for PATCH and DELETE.
    assert (await client.patch("/api/v1/code-sets/9999", json={"name": "x"})).status_code == 404
    assert (await client.delete("/api/v1/code-sets/9999")).status_code == 404

    # Delete.
    assert (await client.delete(f"/api/v1/code-sets/{set_id}")).status_code == 204
    assert (await client.get("/api/v1/code-sets")).json() == []
    assert (await client.delete(f"/api/v1/code-sets/{set_id}")).status_code == 404


async def test_code_set_duplicate_names(project_client):
    client, _ = project_client
    res = await client.post("/api/v1/code-sets", json={"name": "Same"})
    assert res.status_code == 201, res.text
    other = await client.post("/api/v1/code-sets", json={"name": "Other"})
    assert other.status_code == 201, other.text

    # Duplicate create → 409.
    dup = await client.post("/api/v1/code-sets", json={"name": "same"})
    assert dup.status_code == 409

    # Rename onto an existing name → 409; the original keeps its name.
    collision = await client.patch(f"/api/v1/code-sets/{other.json()['id']}", json={"name": "Same"})
    assert collision.status_code == 409
    listed = (await client.get("/api/v1/code-sets")).json()
    assert {s["name"] for s in listed} == {"Same", "Other"}

    # Blank name → 422 for create and rename.
    assert (await client.post("/api/v1/code-sets", json={"name": "  "})).status_code == 422
    assert (await client.patch(f"/api/v1/code-sets/{res.json()['id']}", json={"name": " "})).status_code == 422


async def test_code_set_members(project_client):
    client, _ = project_client
    cids = await _three_codes(client)
    alpha, beta, gamma = cids
    set_id = (await client.post("/api/v1/code-sets", json={"name": "Set"})).json()["id"]

    # Add members: duplicates are deduped, unknown cids ignored, count reported.
    res = await client.post(
        f"/api/v1/code-sets/{set_id}/members",
        json={"cids": [alpha, beta, alpha, 9999]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["added"] == 2
    assert sorted(res.json()["cids"]) == sorted([alpha, beta])

    # Adding again does not duplicate.
    res = await client.post(f"/api/v1/code-sets/{set_id}/members", json={"cids": [alpha, gamma]})
    assert res.status_code == 200, res.text
    assert res.json()["added"] == 1

    # GET returns members with code names.
    body = (await client.get(f"/api/v1/code-sets/{set_id}")).json()
    assert sorted((m["cid"], m["name"]) for m in body["members"]) == [
        (alpha, "Alpha"),
        (beta, "Beta"),
        (gamma, "Gamma"),
    ]

    # List reports the member count.
    listed = (await client.get("/api/v1/code-sets")).json()
    assert listed[0]["member_count"] == 3

    # Remove some members.
    res = await client.request(
        "DELETE",
        f"/api/v1/code-sets/{set_id}/members",
        json={"cids": [beta, 9999]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["removed"] == 1
    body = (await client.get(f"/api/v1/code-sets/{set_id}")).json()
    assert sorted(m["cid"] for m in body["members"]) == [alpha, gamma]

    # Members on a missing set → 404.
    assert (
        await client.post("/api/v1/code-sets/9999/members", json={"cids": [alpha]})
    ).status_code == 404
    assert (
        await client.request(
            "DELETE",
            "/api/v1/code-sets/9999/members",
            json={"cids": [alpha]},
        )
    ).status_code == 404


async def test_code_set_delete_cascades_members(project_client):
    client, target = project_client
    cids = await _three_codes(client)
    set_id = (await client.post("/api/v1/code-sets", json={"name": "Doomed"})).json()["id"]
    await client.post(f"/api/v1/code-sets/{set_id}/members", json={"cids": cids})

    async with aiosqlite.connect(target / "data.qda") as db:
        before = (
            await db.execute("SELECT COUNT(*) FROM code_set_member WHERE set_id = ?", (set_id,))
        )
        assert (await before.fetchone())[0] == 3

    assert (await client.delete(f"/api/v1/code-sets/{set_id}")).status_code == 204

    async with aiosqlite.connect(target / "data.qda") as db:
        after = (
            await db.execute("SELECT COUNT(*) FROM code_set_member WHERE set_id = ?", (set_id,))
        )
        assert (await after.fetchone())[0] == 0
        # The codes themselves must survive the cascade.
        codes = await db.execute("SELECT COUNT(*) FROM code_name")
        assert (await codes.fetchone())[0] == 3


async def test_code_set_audit_rows(project_client):
    client, _ = project_client
    cids = await _three_codes(client)

    created = await client.post("/api/v1/code-sets", json={"name": "Audited", "owner": "tester"})
    set_id = created.json()["id"]

    rows = (await client.get("/api/v1/audit", params={"action": "code_set.create"})).json()["rows"]
    assert len(rows) == 1
    create_row = rows[0]
    assert create_row["user"] == "tester"
    assert create_row["entity"] == "code_set"
    assert create_row["entity_id"] == set_id
    assert create_row["detail"]["name"] == "Audited"

    await client.patch(f"/api/v1/code-sets/{set_id}", json={"name": "Renamed"})
    rows = (await client.get("/api/v1/audit", params={"action": "code_set.rename"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == set_id
    assert rows[0]["detail"]["old_name"] == "Audited"
    assert rows[0]["detail"]["new_name"] == "Renamed"

    await client.post(f"/api/v1/code-sets/{set_id}/members", json={"cids": cids})
    rows = (await client.get("/api/v1/audit", params={"action": "code_set.members_add"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == set_id
    assert rows[0]["detail"]["added"] == 3

    await client.request(
        "DELETE",
        f"/api/v1/code-sets/{set_id}/members",
        json={"cids": [cids[0]]},
    )
    rows = (await client.get("/api/v1/audit", params={"action": "code_set.members_remove"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == set_id
    assert rows[0]["detail"]["removed"] == 1

    await client.delete(f"/api/v1/code-sets/{set_id}")
    rows = (await client.get("/api/v1/audit", params={"action": "code_set.delete"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == set_id
    assert rows[0]["detail"]["name"] == "Renamed"
