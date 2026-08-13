"""API tests — segment links (link table + endpoints)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "links.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def _two_sources(client):
    """Import two text files and return their ids."""
    a = await client.post(
        "/api/v1/sources/import", files={"file": ("a.txt", "alpha beta gamma", "text/plain")}
    )
    assert a.status_code == 200, a.text
    b = await client.post(
        "/api/v1/sources/import", files={"file": ("b.txt", "delta epsilon zeta", "text/plain")}
    )
    assert b.status_code == 200, b.text
    return a.json()["id"], b.json()["id"]


async def test_link_crud(project_client):
    client, _ = project_client
    from_fid, to_fid = await _two_sources(client)

    created = await client.post(
        "/api/v1/links",
        json={
            "from_fid": from_fid,
            "from_pos0": 0,
            "from_pos1": 5,
            "to_fid": to_fid,
            "to_pos0": 6,
            "to_pos1": 13,
            "memo": "cross-reference",
            "owner": "tester",
        },
    )
    assert created.status_code == 201, created.text
    link = created.json()
    assert link["id"] > 0
    assert link["from_name"] == "a.txt"
    assert link["to_name"] == "b.txt"
    assert link["from_text"] == "alpha"
    assert link["to_text"] == "epsilon"

    # Outgoing list for the anchor source.
    outgoing = (await client.get(f"/api/v1/links?fid={from_fid}")).json()
    assert [ln["id"] for ln in outgoing] == [link["id"]]
    assert outgoing[0]["to_name"] == "b.txt"

    # Incoming list for the target source (Inspector target side).
    incoming = (await client.get(f"/api/v1/links/source/{to_fid}")).json()
    assert [ln["id"] for ln in incoming] == [link["id"]]
    assert incoming[0]["from_name"] == "a.txt"

    # The anchor source sees no incoming links, the target no outgoing ones.
    assert (await client.get(f"/api/v1/links/source/{from_fid}")).json() == []
    assert (await client.get(f"/api/v1/links?fid={to_fid}")).json() == []

    # Unfiltered list.
    all_links = (await client.get("/api/v1/links")).json()
    assert [ln["id"] for ln in all_links] == [link["id"]]

    # Delete removes it from both directions.
    assert (await client.delete(f"/api/v1/links/{link['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/links?fid={from_fid}")).json() == []
    assert (await client.get(f"/api/v1/links/source/{to_fid}")).json() == []

    # Deleting twice yields 404.
    assert (await client.delete(f"/api/v1/links/{link['id']}")).status_code == 404


async def test_link_position_validation(project_client):
    client, _ = project_client
    from_fid, to_fid = await _two_sources(client)

    def payload(**overrides):
        base = {
            "from_fid": from_fid,
            "from_pos0": 0,
            "from_pos1": 5,
            "to_fid": to_fid,
            "to_pos0": 0,
            "to_pos1": 5,
        }
        base.update(overrides)
        return base

    # pos1 <= pos0 on either side.
    res = await client.post("/api/v1/links", json=payload(from_pos0=6, from_pos1=3))
    assert res.status_code == 422

    # Positions beyond the source text length.
    res = await client.post("/api/v1/links", json=payload(from_pos1=100))
    assert res.status_code == 422
    res = await client.post("/api/v1/links", json=payload(to_pos1=200))
    assert res.status_code == 422

    # Negative positions.
    res = await client.post("/api/v1/links", json=payload(to_pos0=-2))
    assert res.status_code == 422

    # Nonexistent source.
    res = await client.post("/api/v1/links", json=payload(to_fid=999))
    assert res.status_code == 422

    # A valid link is still accepted afterwards.
    res = await client.post("/api/v1/links", json=payload())
    assert res.status_code == 201, res.text


async def test_link_audit_rows(project_client):
    client, _ = project_client
    from_fid, to_fid = await _two_sources(client)

    res = await client.post(
        "/api/v1/links",
        json={
            "from_fid": from_fid,
            "from_pos0": 0,
            "from_pos1": 5,
            "to_fid": to_fid,
            "to_pos0": 6,
            "to_pos1": 13,
            "owner": "tester",
        },
    )
    link_id = res.json()["id"]

    rows = (await client.get("/api/v1/audit", params={"action": "link.create"})).json()["rows"]
    assert len(rows) == 1
    create_row = rows[0]
    assert create_row["user"] == "tester"
    assert create_row["entity"] == "link"
    assert create_row["entity_id"] == link_id
    assert create_row["source_id"] == from_fid
    assert create_row["detail"]["to_fid"] == to_fid

    await client.delete(f"/api/v1/links/{link_id}")

    rows = (await client.get("/api/v1/audit", params={"action": "link.delete"})).json()["rows"]
    assert len(rows) == 1
    delete_row = rows[0]
    assert delete_row["entity_id"] == link_id
    assert delete_row["source_id"] == from_fid
    assert delete_row["detail"]["to_fid"] == to_fid
