"""API tests — tree ordering positions + code/category move endpoints.

Covers: sibling ordering by (position, id), move into a category / under a
parent code / after and before siblings, position conservation on promote,
cycle rejection (422) and the audit rows of the move endpoints.
"""

from __future__ import annotations

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.persistence.migration import MigrationChain


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "order.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


def _root_items(tree):
    """Root-level items in tree order (categories and codes mixed)."""
    return [t for t in tree if t["parent_id"] is None]


def _cat_codes(tree, catid):
    return [t for t in tree if t["kind"] == "code" and t["parent_id"] == catid]


def _subcodes(tree, cid):
    return [
        t for t in tree
        if t["kind"] == "code" and t["subcode"] and t["parent_id"] == cid
    ]


def _tree_item(tree, kind, id_):
    return next(t for t in tree if t["kind"] == kind and t["id"] == id_)


async def _create_code(client, name, **extra):
    res = await client.post("/api/v1/codes", json={"name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def _create_category(client, name, **extra):
    res = await client.post("/api/v1/codes/categories", json={"name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def test_sibling_order_follows_creation_order(project_client):
    """New codes land at the end of their group; the tree keeps creation order."""
    client, _ = project_client
    a = await _create_code(client, "alpha")
    b = await _create_code(client, "beta")
    c = await _create_code(client, "gamma")

    tree = (await client.get("/api/v1/codes")).json()
    names = [t["name"] for t in _root_items(tree)]
    assert names == ["alpha", "beta", "gamma"]
    # Every sibling also carries a unique position.
    positions = {
        t["id"]: t["position"] for t in _root_items(tree)
    }
    assert positions == {a["cid"]: 0, b["cid"]: 1, c["cid"]: 2}


async def test_move_after_sibling_reorders(project_client):
    client, _ = project_client
    a = await _create_code(client, "a")
    await _create_code(client, "b")
    c = await _create_code(client, "c")

    res = await client.post(
        f"/api/v1/codes/{c['cid']}/move", json={"after_cid": a["cid"]}
    )
    assert res.status_code == 200, res.text

    tree = (await client.get("/api/v1/codes")).json()
    assert [t["name"] for t in _root_items(tree)] == ["a", "c", "b"]


async def test_move_before_first_sibling(project_client):
    client, _ = project_client
    a = await _create_code(client, "a")
    await _create_code(client, "b")
    c = await _create_code(client, "c")

    res = await client.post(
        f"/api/v1/codes/{c['cid']}/move", json={"before_cid": a["cid"]}
    )
    assert res.status_code == 200, res.text

    tree = (await client.get("/api/v1/codes")).json()
    assert [t["name"] for t in _root_items(tree)] == ["c", "a", "b"]


async def test_move_into_category_appends_at_end(project_client):
    client, _ = project_client
    cat = await _create_category(client, "box")
    a = await _create_code(client, "a")
    await _create_code(client, "b")
    c = await _create_code(client, "c")

    res = await client.post(
        f"/api/v1/codes/{a['cid']}/move", json={"parent_catid": cat["catid"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["catid"] == cat["catid"]
    assert res.json()["supercid"] is None

    res = await client.post(
        f"/api/v1/codes/{c['cid']}/move", json={"parent_catid": cat["catid"]}
    )
    assert res.status_code == 200, res.text

    tree = (await client.get("/api/v1/codes")).json()
    assert [t["name"] for t in _cat_codes(tree, cat["catid"])] == ["a", "c"]
    assert [t["name"] for t in _root_items(tree)] == ["box", "b"]


async def test_move_under_parent_code_makes_subcode(project_client):
    client, _ = project_client
    parent = await _create_code(client, "parent")
    x = await _create_code(client, "x")

    res = await client.post(
        f"/api/v1/codes/{x['cid']}/move", json={"supercid": parent["cid"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["supercid"] == parent["cid"]

    tree = (await client.get("/api/v1/codes")).json()
    item = _tree_item(tree, "code", x["cid"])
    assert item["subcode"] is True
    assert item["parent_id"] == parent["cid"]
    assert [t["name"] for t in _subcodes(tree, parent["cid"])] == ["x"]


async def test_move_to_root_with_explicit_null(project_client):
    client, _ = project_client
    cat = await _create_category(client, "box")
    a = await _create_code(client, "a", catid=cat["catid"])
    await _create_code(client, "b", catid=cat["catid"])

    res = await client.post(
        f"/api/v1/codes/{a['cid']}/move", json={"parent_catid": None}
    )
    assert res.status_code == 200, res.text
    assert res.json()["catid"] is None

    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "code", a["cid"])["parent_id"] is None
    assert [t["name"] for t in _cat_codes(tree, cat["catid"])] == ["b"]


async def test_move_cycle_rejected(project_client):
    client, _ = project_client
    parent = await _create_code(client, "parent")
    sub = await _create_code(client, "sub", supercid=parent["cid"])

    # Nesting the parent under its own sub-code is a cycle.
    res = await client.post(
        f"/api/v1/codes/{parent['cid']}/move", json={"supercid": sub["cid"]}
    )
    assert res.status_code == 422
    assert "sub-code" in res.json()["detail"]

    # A code cannot be its own parent.
    res = await client.post(
        f"/api/v1/codes/{sub['cid']}/move", json={"supercid": sub["cid"]}
    )
    assert res.status_code == 422

    # Moving relative to itself is rejected too.
    res = await client.post(
        f"/api/v1/codes/{parent['cid']}/move", json={"after_cid": parent["cid"]}
    )
    assert res.status_code == 422

    # The tree still loads and nothing moved.
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "code", parent["cid"])["parent_id"] is None
    assert _tree_item(tree, "code", sub["cid"])["parent_id"] == parent["cid"]


async def test_move_requires_target_and_finds_missing(project_client):
    client, _ = project_client
    a = await _create_code(client, "a")

    res = await client.post(f"/api/v1/codes/{a['cid']}/move", json={})
    assert res.status_code == 422

    res = await client.post("/api/v1/codes/9999/move", json={"parent_catid": None})
    assert res.status_code == 404

    res = await client.post(
        f"/api/v1/codes/{a['cid']}/move", json={"after_cid": 9999}
    )
    assert res.status_code == 404


async def test_category_move_after_and_into(project_client):
    client, _ = project_client
    a = await _create_category(client, "ca")
    b = await _create_category(client, "cb")
    c = await _create_category(client, "cc")

    res = await client.post(
        f"/api/v1/codes/categories/{c['catid']}/move", json={"after_catid": a["catid"]}
    )
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert [t["name"] for t in _root_items(tree)] == ["ca", "cc", "cb"]

    # Move b under a (append as subcategory).
    res = await client.post(
        f"/api/v1/codes/categories/{b['catid']}/move", json={"supercatid": a["catid"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["supercatid"] == a["catid"]
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_item(tree, "category", b["catid"])["parent_id"] == a["catid"]


async def test_category_move_cycle_rejected(project_client):
    client, _ = project_client
    a = await _create_category(client, "outer")
    inner = await _create_category(client, "inner", supercatid=a["catid"])

    res = await client.post(
        f"/api/v1/codes/categories/{a['catid']}/move",
        json={"supercatid": inner["catid"]},
    )
    assert res.status_code == 422

    # Dropping after a descendant implies the same cycle.
    res = await client.post(
        f"/api/v1/codes/categories/{a['catid']}/move",
        json={"after_catid": inner["catid"]},
    )
    assert res.status_code == 422

    res = await client.post(
        f"/api/v1/codes/categories/{a['catid']}/move", json={"after_catid": a["catid"]}
    )
    assert res.status_code == 422


async def test_promote_code_preserves_parent_position(project_client):
    client, _ = project_client
    c1 = await _create_category(client, "cat1")
    await _create_category(client, "cat2")
    x = await _create_code(client, "x", catid=c1["catid"])

    # x lands at the slot its category occupied in the root list.
    res = await client.post(f"/api/v1/codes/{x['cid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["catid"] is None

    tree = (await client.get("/api/v1/codes")).json()
    names = [t["name"] for t in _root_items(tree)]
    assert names == ["x", "cat1", "cat2"]


async def test_promote_subcode_lands_after_parents_group(project_client):
    client, _ = project_client
    cat = await _create_category(client, "box")
    parent = await _create_code(client, "parent", catid=cat["catid"])
    sub = await _create_code(
        client, "sub", supercid=parent["cid"], catid=cat["catid"]
    )

    res = await client.post(f"/api/v1/codes/{sub['cid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["supercid"] is None

    tree = (await client.get("/api/v1/codes")).json()
    # sub joined the box group at the parent's index (box has one code).
    assert [t["name"] for t in _cat_codes(tree, cat["catid"])] == ["sub", "parent"]


async def test_promote_category_preserves_parent_position(project_client):
    client, _ = project_client
    root1 = await _create_category(client, "r1")
    await _create_category(client, "r2")
    mid = await _create_category(client, "mid", supercatid=root1["catid"])
    leaf = await _create_category(client, "leaf", supercatid=mid["catid"])

    # leaf moves under the grandparent at mid's old slot in that list.
    res = await client.post(f"/api/v1/codes/categories/{leaf['catid']}/promote")
    assert res.status_code == 200, res.text
    assert res.json()["supercatid"] == root1["catid"]
    tree = (await client.get("/api/v1/codes")).json()
    assert [t["name"] for t in _root_items(tree)] == ["r1", "r2"]
    assert [
        t["name"]
        for t in tree
        if t["kind"] == "category" and t["parent_id"] == root1["catid"]
    ] == ["leaf", "mid"]


async def test_move_operations_record_audit(project_client):
    client, _ = project_client
    cat = await _create_category(client, "box")
    a = await _create_code(client, "a")
    b = await _create_code(client, "b")

    await client.post(f"/api/v1/codes/{b['cid']}/move", json={"after_cid": a["cid"]})
    await client.post(f"/api/v1/codes/{a['cid']}/move", json={"parent_catid": cat["catid"]})
    await client.post(
        f"/api/v1/codes/categories/{cat['catid']}/move", json={"supercatid": None}
    )

    res = await client.get("/api/v1/audit", params={"action": "code.move"})
    assert res.json()["total"] == 2
    row = res.json()["rows"][0]
    assert row["entity"] == "code"
    assert row["entity_id"] == a["cid"]
    assert row["detail"]["catid"] == cat["catid"]

    res = await client.get("/api/v1/audit", params={"action": "category.move"})
    assert res.json()["total"] == 1
    row = res.json()["rows"][0]
    assert row["entity"] == "code_cat"
    assert row["entity_id"] == cat["catid"]
    assert row["detail"]["supercatid"] is None


# ---------------------------------------------------------------------------
# Migration v31
# ---------------------------------------------------------------------------

_LEGACY_TABLES = [
    "CREATE TABLE project (databaseversion text, date text, memo text, about text)",
    "CREATE TABLE source (id integer primary key, name text, fulltext text, mediapath text, memo text, "
    "owner text, date text, unique(name))",
    "CREATE TABLE code_image (imid integer primary key, id integer, x1 integer, y1 integer, width integer, "
    "height integer, cid integer, memo text, date text, owner text)",
    "CREATE TABLE code_av (avid integer primary key, id integer, pos0 integer, pos1 integer, cid integer, "
    "memo text, date text, owner text)",
    "CREATE TABLE annotation (anid integer primary key, fid integer, pos0 integer, pos1 integer, memo text, "
    "owner text, date text, unique(fid,pos0,pos1,owner))",
    "CREATE TABLE attribute_type (name text primary key, date text, owner text, memo text, caseOrFile text, "
    "valuetype text)",
    "CREATE TABLE attribute (attrid integer primary key, name text, attr_type text, value text, id integer, "
    "date text, owner text, unique(name,attr_type,id))",
    "CREATE TABLE case_text (id integer primary key, caseid integer, fid integer, pos0 integer, pos1 integer, "
    "owner text, date text)",
    "CREATE TABLE cases (caseid integer primary key, name text, memo text, owner text, date text, "
    "constraint ucm unique(name))",
    "CREATE TABLE code_cat (catid integer primary key, name text, owner text, date text, memo text, "
    "supercatid integer, unique(name))",
    "CREATE TABLE code_text (cid integer, fid integer, seltext text, pos0 integer, pos1 integer, "
    "owner text, date text, memo text)",
    "CREATE TABLE code_name (cid integer primary key, name text, memo text, catid integer, owner text, "
    "date text, color text, unique(name))",
    "CREATE TABLE journal (jid integer primary key, name text, jentry text, date text, owner text)",
]


async def test_v31_adds_position_columns_and_stamps_version(tmp_path):
    """v31 adds position to code_name/code_cat and bumps the version."""
    db = tmp_path / "legacy.qda"
    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    for sql in _LEGACY_TABLES:
        await cur.execute(sql)
    await cur.execute("INSERT INTO project VALUES ('v2', '2020-01-01', 'memo', 'QualCoder 1.0')")
    await conn.commit()

    chain = MigrationChain(conn)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v31" in applied

    for table in ("code_name", "code_cat"):
        await cur.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in await cur.fetchall()}
        assert "position" in cols, f"missing position on {table}"
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v35"
    await conn.close()
