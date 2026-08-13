"""API tests — code/category promote & demote (Word-list style)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "promote.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


def _tree_item(tree, kind, id_):
    return next(t for t in tree if t["kind"] == kind and t["id"] == id_)


async def test_promote_subcode_clears_supercid(project_client):
    client, _ = project_client
    parent = (await client.post("/api/v1/codes", json={"name": "parent"})).json()
    sub = (
        await client.post(
            "/api/v1/codes", json={"name": "sub", "supercid": parent["cid"]}
        )
    ).json()

    res = await client.post(f"/api/v1/codes/{sub['cid']}/promote")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["supercid"] is None

    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "code", sub["cid"])["parent_id"] is None
    assert _tree_item(tree, "code", sub["cid"])["subcode"] is False


async def test_promote_category_child_moves_into_parent_category(project_client):
    client, _ = project_client
    top = (await client.post("/api/v1/codes/categories", json={"name": "top"})).json()
    inner = (
        await client.post(
            "/api/v1/codes/categories",
            json={"name": "inner", "supercatid": top["catid"]},
        )
    ).json()
    code = (
        await client.post("/api/v1/codes", json={"name": "c", "catid": inner["catid"]})
    ).json()

    res = await client.post(f"/api/v1/codes/{code['cid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["catid"] == top["catid"]

    tree = (await client.get("/api/v1/codes")).json()
    item = _tree_item(tree, "code", code["cid"])
    assert item["parent_id"] == top["catid"]


async def test_promote_top_level_category_member_goes_to_root(project_client):
    client, _ = project_client
    top = (await client.post("/api/v1/codes/categories", json={"name": "solo"})).json()
    code = (
        await client.post("/api/v1/codes", json={"name": "r", "catid": top["catid"]})
    ).json()

    res = await client.post(f"/api/v1/codes/{code['cid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["catid"] is None

    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "code", code["cid"])["parent_id"] is None


async def test_promote_root_code_rejected(project_client):
    client, _ = project_client
    code = (await client.post("/api/v1/codes", json={"name": "rooty"})).json()

    res = await client.post(f"/api/v1/codes/{code['cid']}/promote")
    assert res.status_code == 422
    assert res.json()["detail"] == "This code is already at the top level and cannot be promoted further."

    # The tree still loads and the code is untouched.
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "code", code["cid"])["parent_id"] is None


async def test_promote_missing_code_404(project_client):
    client, _ = project_client
    assert (await client.post("/api/v1/codes/9999/promote")).status_code == 404


async def test_demote_under_previous_sibling(project_client):
    client, _ = project_client
    a = (await client.post("/api/v1/codes", json={"name": "a"})).json()
    b = (await client.post("/api/v1/codes", json={"name": "b"})).json()

    res = await client.post(f"/api/v1/codes/{b['cid']}/demote")
    assert res.status_code == 200, res.text
    assert res.json()["supercid"] == a["cid"]

    tree = (await client.get("/api/v1/codes")).json()
    item = _tree_item(tree, "code", b["cid"])
    assert item["parent_id"] == a["cid"]
    assert item["subcode"] is True

    # Promote undoes the demote (back to category level / root).
    res = await client.post(f"/api/v1/codes/{b['cid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["supercid"] is None


async def test_demote_inside_category(project_client):
    client, _ = project_client
    cat = (await client.post("/api/v1/codes/categories", json={"name": "box"})).json()
    a = (
        await client.post("/api/v1/codes", json={"name": "ca", "catid": cat["catid"]})
    ).json()
    b = (
        await client.post("/api/v1/codes", json={"name": "cb", "catid": cat["catid"]})
    ).json()

    res = await client.post(f"/api/v1/codes/{b['cid']}/demote")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["supercid"] == a["cid"]
    assert body["catid"] == cat["catid"]  # stays inside its category


async def test_demote_without_previous_sibling_rejected(project_client):
    client, _ = project_client
    a = (await client.post("/api/v1/codes", json={"name": "only"})).json()
    b = (
        await client.post("/api/v1/codes", json={"name": "sub", "supercid": a["cid"]})
    ).json()

    # Sole root code and sole sub-code both have no previous sibling.
    res = await client.post(f"/api/v1/codes/{a['cid']}/demote")
    assert res.status_code == 422
    assert (
        res.json()["detail"]
        == "This code cannot be demoted — there is no sibling below it to move under."
    )

    res = await client.post(f"/api/v1/codes/{b['cid']}/demote")
    assert res.status_code == 422
    assert (
        res.json()["detail"]
        == "This code cannot be demoted — there is no sibling below it to move under."
    )


async def test_demote_missing_code_404(project_client):
    client, _ = project_client
    assert (await client.post("/api/v1/codes/9999/demote")).status_code == 404


async def test_category_promote_moves_into_grandparent(project_client):
    client, _ = project_client
    root = (await client.post("/api/v1/codes/categories", json={"name": "grand"})).json()
    mid = (
        await client.post(
            "/api/v1/codes/categories",
            json={"name": "mid", "supercatid": root["catid"]},
        )
    ).json()
    leaf = (
        await client.post(
            "/api/v1/codes/categories",
            json={"name": "leaf", "supercatid": mid["catid"]},
        )
    ).json()

    res = await client.post(f"/api/v1/codes/categories/{leaf['catid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["supercatid"] == root["catid"]

    res = await client.post(f"/api/v1/codes/categories/{mid['catid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["supercatid"] is None

    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "category", leaf["catid"])["parent_id"] == root["catid"]
    assert _tree_item(tree, "category", mid["catid"])["parent_id"] is None


async def test_category_promote_top_level_rejected(project_client):
    client, _ = project_client
    cat = (await client.post("/api/v1/codes/categories", json={"name": "lonely"})).json()

    res = await client.post(f"/api/v1/codes/categories/{cat['catid']}/promote")
    assert res.status_code == 422
    assert (
        res.json()["detail"]
        == "This category is already at the top level and cannot be promoted further."
    )


async def test_category_demote_under_previous_sibling(project_client):
    client, _ = project_client
    a = (await client.post("/api/v1/codes/categories", json={"name": "cat_a"})).json()
    b = (await client.post("/api/v1/codes/categories", json={"name": "cat_b"})).json()

    res = await client.post(f"/api/v1/codes/categories/{b['catid']}/demote")
    assert res.status_code == 200, res.text
    assert res.json()["supercatid"] == a["catid"]

    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "category", b["catid"])["parent_id"] == a["catid"]

    # Promote undoes the demote back to the root.
    res = await client.post(f"/api/v1/codes/categories/{b['catid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["supercatid"] is None


async def test_category_demote_without_previous_sibling_rejected(project_client):
    client, _ = project_client
    cat = (await client.post("/api/v1/codes/categories", json={"name": "first"})).json()

    res = await client.post(f"/api/v1/codes/categories/{cat['catid']}/demote")
    assert res.status_code == 422
    assert (
        res.json()["detail"]
        == "This category cannot be demoted — there is no sibling below it to move under."
    )


async def test_category_demote_missing_404(project_client):
    client, _ = project_client
    assert (
        await client.post("/api/v1/codes/categories/9999/demote")
    ).status_code == 404


async def test_promote_demote_record_audit(project_client):
    client, _ = project_client
    a = (await client.post("/api/v1/codes", json={"name": "aud_a"})).json()
    b = (await client.post("/api/v1/codes", json={"name": "aud_b"})).json()
    parent = (await client.post("/api/v1/codes/categories", json={"name": "aud_parent"})).json()
    cat = (
        await client.post(
            "/api/v1/codes/categories",
            json={"name": "aud_cat", "supercatid": parent["catid"]},
        )
    ).json()

    await client.post(f"/api/v1/codes/{b['cid']}/demote")
    await client.post(f"/api/v1/codes/{b['cid']}/promote")
    await client.post(f"/api/v1/codes/categories/{cat['catid']}/promote")

    res = await client.get("/api/v1/audit", params={"action": "code.demote"})
    assert res.json()["total"] == 1
    row = res.json()["rows"][0]
    assert row["entity"] == "code"
    assert row["entity_id"] == b["cid"]
    assert row["detail"]["supercid"] == a["cid"]

    res = await client.get("/api/v1/audit", params={"action": "code.promote"})
    assert res.json()["total"] == 1
    assert res.json()["rows"][0]["entity_id"] == b["cid"]

    res = await client.get("/api/v1/audit", params={"action": "category.promote"})
    assert res.json()["total"] == 1
    assert res.json()["rows"][0]["entity"] == "code_cat"
    assert res.json()["rows"][0]["entity_id"] == cat["catid"]
