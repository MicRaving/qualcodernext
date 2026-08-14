"""API tests — history undo / redo (edit review)."""

from __future__ import annotations

import os
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def open_project(client, tmp_path):
    target = tmp_path / "undo.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text
    yield target
    await client.post("/api/v1/projects/close")


async def _find_audit_id(client, action: str) -> int:
    res = await client.get("/api/v1/audit", params={"action": action})
    rows = res.json()["rows"]
    assert rows, f"no audit rows for {action}"
    return rows[0]["id"]


async def _import_text(client, open_project, name: str, content: str = "hello world") -> int:
    path = open_project / "documents" / name
    os.makedirs(path.parent, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import", files={"file": (name, content, "text/plain")}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _make_code(client, name: str, **extra) -> int:
    res = await client.post("/api/v1/codes", json={"name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()["cid"]


def _tree_code(tree, cid: int) -> dict:
    for item in tree:
        if item["kind"] == "code" and item["id"] == cid:
            return item
    raise AssertionError(f"code {cid} not in tree")


def _tree_category(tree, catid: int) -> dict:
    for item in tree:
        if item["kind"] == "category" and item["id"] == catid:
            return item
    raise AssertionError(f"category {catid} not in tree")


async def _drop_companion(target, media_id: int) -> None:
    """Remove the automatic import-time transcript companion (test setup)."""
    with sqlite3.connect(str(target / "data.qda")) as conn:
        row = conn.execute(
            "SELECT av_text_id FROM source WHERE id = ?", (media_id,)
        ).fetchone()
        if row and row[0] is not None:
            conn.execute("DELETE FROM source WHERE id = ?", (row[0],))
        conn.execute("UPDATE source SET av_text_id = NULL WHERE id = ?", (media_id,))
        conn.commit()


async def test_undo_redo_coding_create(client, open_project):
    source = open_project / "documents" / "a.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("a.txt", "hello world", "text/plain")}
    )
    fid = res.json()["id"]
    res = await client.post("/api/v1/codes", json={"name": "U"})
    cid = res.json()["cid"]

    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    ctid = res.json()["ctid"]

    # Undo the coding.create → the coding is gone.
    aid = await _find_audit_id(client, "coding.create")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert all(c["ctid"] != ctid for c in codings)

    # Redo → the coding is back.
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid for c in codings)


async def test_undo_redo_coding_delete(client, open_project):
    source = open_project / "documents" / "b.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("b.txt", "hello world", "text/plain")}
    )
    fid = res.json()["id"]
    res = await client.post("/api/v1/codes", json={"name": "D"})
    cid = res.json()["cid"]
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    ctid = res.json()["ctid"]

    res = await client.delete(f"/api/v1/codings/text/{ctid}")
    assert res.status_code == 204

    # Undo the coding.delete → the row is restored.
    aid = await _find_audit_id(client, "coding.delete")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid for c in codings)

    # Redo → deleted again.
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert all(c["ctid"] != ctid for c in codings)


async def test_undo_redo_source_edit(client, open_project):
    source = open_project / "documents" / "e.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("old text content", encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("e.txt", "old text content", "text/plain")}
    )
    fid = res.json()["id"]
    await client.post(
        "/api/v1/codings/commit-edit",
        json={"fid": fid, "new_text": "new text content here"},
    )

    aid = await _find_audit_id(client, "source.edit")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    text = (await client.get(f"/api/v1/sources/{fid}")).json()["fulltext"]
    assert text == "old text content"

    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    text = (await client.get(f"/api/v1/sources/{fid}")).json()["fulltext"]
    assert text == "new text content here"


async def test_undo_rename_and_create(client, open_project):
    res = await client.post("/api/v1/codes", json={"name": "OldName"})
    cid = res.json()["cid"]
    await client.patch(f"/api/v1/codes/{cid}", json={"name": "NewName"})

    # Undo the rename.
    aid = await _find_audit_id(client, "code.rename")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert any(c["kind"] == "code" and c["name"] == "OldName" for c in tree)

    # Undo the create → the code is gone.
    aid = await _find_audit_id(client, "code.create")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != cid for c in tree)

    # Redo → the code is back (as created).
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert any(c["kind"] == "code" and c["id"] == cid for c in tree)


async def test_undo_redo_code_delete(client, open_project):
    res = await client.post("/api/v1/codes", json={"name": "Gone"})
    cid = res.json()["cid"]
    res = await client.delete(f"/api/v1/codes/{cid}")
    assert res.status_code == 204
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != cid for c in tree)

    # Undo the code.delete → the code row is restored.
    aid = await _find_audit_id(client, "code.delete")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert any(c["kind"] == "code" and c["id"] == cid for c in tree)

    # Redo → deleted again.
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != cid for c in tree)


async def test_undo_redo_code_move_promote_demote(client, open_project):
    cid = await _make_code(client, "M")
    res = await client.post("/api/v1/codes/categories", json={"name": "Group"})
    catid = res.json()["catid"]

    # Move into the category.
    res = await client.post(f"/api/v1/codes/{cid}/move", json={"parent_catid": catid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, cid)["parent_id"] == catid

    aid = await _find_audit_id(client, "code.move")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, cid)["parent_id"] is None
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, cid)["parent_id"] == catid

    # Promote to the root and back.
    res = await client.post(f"/api/v1/codes/{cid}/promote")
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "code.promote")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, cid)["parent_id"] == catid
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, cid)["parent_id"] is None

    # Demote needs a sibling: code B joins the root, B demotes under the
    # previously promoted code.
    b = await _make_code(client, "Sibling")
    res = await client.post(f"/api/v1/codes/{b}/demote")
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, b)["parent_id"] == cid
    aid = await _find_audit_id(client, "code.demote")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, b)["parent_id"] is None
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, b)["parent_id"] == cid


async def test_undo_redo_code_merge(client, open_project):
    fid = await _import_text(client, open_project, "merge.txt")
    a = await _make_code(client, "MergeA")
    b = await _make_code(client, "MergeB")
    sub = await _make_code(client, "MergeSub", supercid=a)
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": a, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    ctid = res.json()["ctid"]

    res = await client.post(f"/api/v1/codes/{a}/merge", json={"target_cid": b})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != a for c in tree)

    aid = await _find_audit_id(client, "code.merge")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_code(tree, a)["name"] == "MergeA"
    assert _tree_code(tree, sub)["parent_id"] == a
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid and c["cid"] == a for c in codings)

    # Redo → merged again: the code vanishes and the coding follows target.
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != a for c in tree)
    assert _tree_code(tree, sub)["parent_id"] == b
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid and c["cid"] == b for c in codings)


async def test_undo_redo_category_create_rename_delete(client, open_project):
    # Create (with a code inside) + rename + delete, each inverted.
    res = await client.post("/api/v1/codes/categories", json={"name": "CatA"})
    catid = res.json()["catid"]
    cid = await _make_code(client, "CatCode", catid=catid)

    res = await client.patch(f"/api/v1/codes/categories/{catid}", json={"name": "CatB"})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "category.rename")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_category(tree, catid)["name"] == "CatA"
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_category(tree, catid)["name"] == "CatB"

    res = await client.delete(f"/api/v1/codes/categories/{catid}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "category.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_category(tree, catid)["name"] == "CatB"
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != catid for c in tree if c["kind"] == "category")

    # Undo the create: the category (and its orphaned code) are removed.
    aid = await _find_audit_id(client, "category.create")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != catid for c in tree if c["kind"] == "category")
    assert _tree_code(tree, cid)["parent_id"] is None
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_category(tree, catid)["name"] == "CatA"


async def test_undo_redo_category_merge(client, open_project):
    res = await client.post("/api/v1/codes/categories", json={"name": "MergeCatA"})
    cat_a = res.json()["catid"]
    res = await client.post("/api/v1/codes/categories", json={"name": "MergeCatB"})
    cat_b = res.json()["catid"]
    x = await _make_code(client, "CatX", catid=cat_a)
    y = await _make_code(client, "CatY", catid=cat_b)

    res = await client.post(
        f"/api/v1/codes/categories/{cat_a}/merge", json={"target_catid": cat_b}
    )
    assert res.status_code == 204
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != cat_a for c in tree if c["kind"] == "category")

    aid = await _find_audit_id(client, "category.merge")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert _tree_category(tree, cat_a)["name"] == "MergeCatA"
    assert _tree_code(tree, x)["parent_id"] == cat_a
    assert _tree_code(tree, y)["parent_id"] == cat_b

    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != cat_a for c in tree if c["kind"] == "category")
    assert _tree_code(tree, x)["parent_id"] == cat_b


async def test_undo_redo_coding_update(client, open_project):
    fid = await _import_text(client, open_project, "update.txt")
    cid = await _make_code(client, "UpdateCode")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5,
              "memo": "before", "important": 1, "weight": 10},
    )
    ctid = res.json()["ctid"]

    res = await client.patch(
        f"/api/v1/codings/text/{ctid}", json={"memo": "after", "weight": 90}
    )
    assert res.status_code == 200, res.text

    aid = await _find_audit_id(client, "coding.update")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    coding = next(c for c in (await client.get(f"/api/v1/codings/text/{fid}")).json())
    assert coding["memo"] == "before"
    assert coding["weight"] == 10
    assert coding["important"] == 1

    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    coding = next(c for c in (await client.get(f"/api/v1/codings/text/{fid}")).json())
    assert coding["memo"] == "after"
    assert coding["weight"] == 90

    # AV coding memo/weight/important restore.
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("talk.mp3", b"ID3fake", "audio/mpeg")}
    )
    media_id = res.json()["id"]
    res = await client.post(
        "/api/v1/codings/av",
        json={"id": media_id, "pos0": 0, "pos1": 100, "cid": cid,
              "memo": "old", "important": 0, "weight": 0},
    )
    avid = res.json()["avid"]
    res = await client.patch(
        f"/api/v1/codings/av/{avid}", json={"memo": "new", "important": 1, "weight": 42}
    )
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "coding.update")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    av = next(a for a in (await client.get(f"/api/v1/codings/av/{media_id}")).json())
    assert av["memo"] == "old"
    assert av["important"] == 0
    assert av["weight"] == 0
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    av = next(a for a in (await client.get(f"/api/v1/codings/av/{media_id}")).json())
    assert av["memo"] == "new"
    assert av["weight"] == 42


async def test_undo_redo_transcript(client, open_project):
    # transcript.delete → undo restores companion + link; redo removes again.
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("song.mp3", b"ID3fake", "audio/mpeg")}
    )
    media_id = res.json()["id"]
    trans_id = res.json()["av_text_id"]

    res = await client.delete(f"/api/v1/sources/{media_id}/transcript")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "transcript.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    after = (await client.get(f"/api/v1/sources/{media_id}")).json()
    assert after["av_text_id"] == trans_id
    assert (await client.get(f"/api/v1/sources/{trans_id}")).status_code == 200
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    after = (await client.get(f"/api/v1/sources/{media_id}")).json()
    assert after["av_text_id"] is None
    assert (await client.get(f"/api/v1/sources/{trans_id}")).status_code == 404

    # transcript.create → undo removes the companion; redo brings it back.
    await _drop_companion(open_project, media_id)
    res = await client.post(f"/api/v1/sources/{media_id}/transcript", json={})
    assert res.status_code == 200, res.text
    trans_id = res.json()["av_text_id"]
    aid = await _find_audit_id(client, "transcript.create")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    after = (await client.get(f"/api/v1/sources/{media_id}")).json()
    assert after["av_text_id"] is None
    assert (await client.get(f"/api/v1/sources/{trans_id}")).status_code == 404
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    after = (await client.get(f"/api/v1/sources/{media_id}")).json()
    assert after["av_text_id"] == trans_id


async def test_undo_redo_source_update(client, open_project):
    fid = await _import_text(client, open_project, "rename.txt")
    res = await client.patch(
        f"/api/v1/sources/{fid}", json={"name": "renamed.txt", "memo": "some memo"}
    )
    assert res.status_code == 200, res.text

    aid = await _find_audit_id(client, "source.update")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    src = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert src["name"] == "rename.txt"
    assert src["memo"] == ""
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    src = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert src["name"] == "renamed.txt"
    assert src["memo"] == "some memo"


async def test_undo_redo_case_and_attributes(client, open_project):
    fid = await _import_text(client, open_project, "case.txt")
    res = await client.post("/api/v1/cases", json={"name": "CaseOne", "memo": "m1"})
    caseid = res.json()["caseid"]

    # link_file → undo deletes the link; redo restores it.
    res = await client.post(f"/api/v1/cases/{caseid}/files", json={"fid": fid})
    assert res.status_code == 201, res.text
    aid = await _find_audit_id(client, "case.link_file")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    files = (await client.get(f"/api/v1/cases/{caseid}/files")).json()
    assert all(f["id"] != fid for f in files)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    files = (await client.get(f"/api/v1/cases/{caseid}/files")).json()
    assert any(f["id"] == fid for f in files)

    # unlink_file → undo restores the row.
    res = await client.delete(f"/api/v1/cases/{caseid}/files/{fid}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "case.unlink_file")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    files = (await client.get(f"/api/v1/cases/{caseid}/files")).json()
    assert any(f["id"] == fid for f in files)

    # Attribute type + value: set → undo restores the previous value.
    res = await client.post(
        "/api/v1/attributes/types", json={"name": "age", "case_or_file": "case",
                                          "value_type": "number"}
    )
    assert res.status_code == 201, res.text
    res = await client.put(
        "/api/v1/attributes/values/age", params={"attr_type": "case", "entity_id": caseid},
        json={"value": "33"},
    )
    assert res.status_code == 200, res.text
    res = await client.put(
        "/api/v1/attributes/values/age", params={"attr_type": "case", "entity_id": caseid},
        json={"value": "40"},
    )
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "attribute.set_value")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    values = (await client.get("/api/v1/attributes/values", params={
        "entity_id": caseid, "attr_type": "case"})).json()
    assert any(v["name"] == "age" and v["value"] == "33" for v in values)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    values = (await client.get("/api/v1/attributes/values", params={
        "entity_id": caseid, "attr_type": "case"})).json()
    assert any(v["name"] == "age" and v["value"] == "40" for v in values)

    # Unset (first assignment had no before): undo removes the value.
    res = await client.post("/api/v1/cases", json={"name": "CaseTwo"})
    case2 = res.json()["caseid"]
    res = await client.put(
        "/api/v1/attributes/values/age", params={"attr_type": "case", "entity_id": case2},
        json={"value": "25"},
    )
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "attribute.set_value")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    values = (await client.get("/api/v1/attributes/values", params={
        "entity_id": case2, "attr_type": "case"})).json()
    assert all(v["name"] != "age" for v in values)

    # attribute type create → undo removes type; delete → undo restores it.
    aid = await _find_audit_id(client, "attribute.create")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    types = (await client.get("/api/v1/attributes/types")).json()
    assert all(t["name"] != "age" for t in types)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    types = (await client.get("/api/v1/attributes/types")).json()
    assert any(t["name"] == "age" for t in types)

    res = await client.delete("/api/v1/attributes/types/age")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "attribute.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    types = (await client.get("/api/v1/attributes/types")).json()
    assert any(t["name"] == "age" for t in types)

    # case.delete → undo restores the case row; redo removes it again.
    res = await client.delete(f"/api/v1/cases/{caseid}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "case.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    cases = (await client.get("/api/v1/cases")).json()
    assert any(c["caseid"] == caseid and c["name"] == "CaseOne" for c in cases)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    cases = (await client.get("/api/v1/cases")).json()
    assert all(c["caseid"] != caseid for c in cases)


async def test_undo_redo_journal_update_delete(client, open_project):
    res = await client.post("/api/v1/journals", json={"name": "J", "jentry": "first"})
    jid = res.json()["jid"]
    res = await client.patch(f"/api/v1/journals/{jid}", json={"name": "J2", "jentry": "second"})
    assert res.status_code == 200, res.text

    aid = await _find_audit_id(client, "journal.update")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    journal = next(j for j in (await client.get("/api/v1/journals")).json() if j["jid"] == jid)
    assert journal["name"] == "J"
    assert journal["jentry"] == "first"
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    journal = next(j for j in (await client.get("/api/v1/journals")).json() if j["jid"] == jid)
    assert journal["name"] == "J2"

    res = await client.delete(f"/api/v1/journals/{jid}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "journal.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    journals = (await client.get("/api/v1/journals")).json()
    assert any(j["jid"] == jid for j in journals)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    journals = (await client.get("/api/v1/journals")).json()
    assert all(j["jid"] != jid for j in journals)


async def test_undo_redo_link_create_delete(client, open_project):
    fid = await _import_text(client, open_project, "link.txt")
    payload = {
        "from_fid": fid, "from_pos0": 0, "from_pos1": 5,
        "to_fid": fid, "to_pos0": 6, "to_pos1": 11,
    }
    res = await client.post("/api/v1/links", json=payload)
    assert res.status_code == 201, res.text
    link_id = res.json()["id"]

    aid = await _find_audit_id(client, "link.create")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    links = (await client.get("/api/v1/links", params={"fid": fid})).json()
    assert all(item["id"] != link_id for item in links)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    links = (await client.get("/api/v1/links", params={"fid": fid})).json()
    assert any(item["id"] == link_id for item in links)

    res = await client.delete(f"/api/v1/links/{link_id}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "link.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    links = (await client.get("/api/v1/links", params={"fid": fid})).json()
    assert any(item["id"] == link_id for item in links)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    links = (await client.get("/api/v1/links", params={"fid": fid})).json()
    assert all(item["id"] != link_id for item in links)


async def test_undo_redo_comment_create_update_delete(client, open_project):
    fid = await _import_text(client, open_project, "comment.txt")
    res = await client.post(
        "/api/v1/comments", json={"target_kind": "source", "target_id": fid, "body": "first"}
    )
    comment_id = res.json()["id"]

    aid = await _find_audit_id(client, "comment.create")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    thread = (await client.get("/api/v1/comments", params={
        "target_kind": "source", "target_id": fid})).json()
    assert all(c["id"] != comment_id for c in thread)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    thread = (await client.get("/api/v1/comments", params={
        "target_kind": "source", "target_id": fid})).json()
    assert any(c["id"] == comment_id and c["body"] == "first" for c in thread)

    res = await client.patch(f"/api/v1/comments/{comment_id}", json={"body": "revised"})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "comment.update")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    thread = (await client.get("/api/v1/comments", params={
        "target_kind": "source", "target_id": fid})).json()
    assert next(c for c in thread if c["id"] == comment_id)["body"] == "first"
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    thread = (await client.get("/api/v1/comments", params={
        "target_kind": "source", "target_id": fid})).json()
    assert next(c for c in thread if c["id"] == comment_id)["body"] == "revised"

    res = await client.delete(f"/api/v1/comments/{comment_id}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "comment.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    thread = (await client.get("/api/v1/comments", params={
        "target_kind": "source", "target_id": fid})).json()
    assert any(c["id"] == comment_id for c in thread)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    thread = (await client.get("/api/v1/comments", params={
        "target_kind": "source", "target_id": fid})).json()
    assert all(c["id"] != comment_id for c in thread)


async def test_undo_redo_creative_and_promote(client, open_project):
    fid = await _import_text(client, open_project, "creative.txt")
    res = await client.post(
        "/api/v1/creative",
        json={"text": "quote", "source_fid": fid, "pos0": 0, "pos1": 5, "note": "n1"},
    )
    item_id = res.json()["id"]

    aid = await _find_audit_id(client, "creative.create")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    items = (await client.get("/api/v1/creative")).json()
    assert all(i["id"] != item_id for i in items)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    items = (await client.get("/api/v1/creative")).json()
    assert any(i["id"] == item_id for i in items)

    res = await client.patch(f"/api/v1/creative/{item_id}", json={"text": "quote2", "note": "n2"})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "creative.update")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    items = (await client.get("/api/v1/creative")).json()
    item = next(i for i in items if i["id"] == item_id)
    assert item["text"] == "quote"
    assert item["note"] == "n1"
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    item = next(i for i in (await client.get("/api/v1/creative")).json() if i["id"] == item_id)
    assert item["text"] == "quote2"

    # Promote → undo removes the created code + coding; redo restores both.
    res = await client.post(f"/api/v1/creative/{item_id}/promote", json={"code_name": "Promo"})
    assert res.status_code == 200, res.text
    cid, ctid = res.json()["cid"], res.json()["ctid"]
    aid = await _find_audit_id(client, "creative.promote")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["id"] != cid for c in tree)
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert all(c["ctid"] != ctid for c in codings)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    tree = (await client.get("/api/v1/codes")).json()
    assert any(c["id"] == cid and c["name"] == "Promo" for c in tree)
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid and c["cid"] == cid for c in codings)

    # creative.delete → undo restores the full row.
    res = await client.delete(f"/api/v1/creative/{item_id}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "creative.delete")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    items = (await client.get("/api/v1/creative")).json()
    assert any(i["id"] == item_id and i["text"] == "quote2" for i in items)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    items = (await client.get("/api/v1/creative")).json()
    assert all(i["id"] != item_id for i in items)


async def test_undo_annotation_update_position(client, open_project):
    fid = await _import_text(client, open_project, "ann.txt")
    res = await client.post(
        "/api/v1/annotations",
        json={"fid": fid, "pos0": 0, "pos1": 5, "memo": "old memo"},
    )
    anid = res.json()["anid"]
    res = await client.patch(
        f"/api/v1/annotations/{anid}", json={"memo": "new memo", "pos0": 1, "pos1": 3}
    )
    assert res.status_code == 200, res.text

    aid = await _find_audit_id(client, "annotation.update")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    ann = next(a for a in (await client.get(f"/api/v1/annotations/{fid}")).json()
               if a["anid"] == anid)
    assert ann["memo"] == "old memo"
    assert ann["pos0"] == 0
    assert ann["pos1"] == 5
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    ann = next(a for a in (await client.get(f"/api/v1/annotations/{fid}")).json()
               if a["anid"] == anid)
    assert ann["memo"] == "new memo"
    assert ann["pos1"] == 3


async def test_undo_unsupported_action(client, open_project):
    await client.post("/api/v1/codes", json={"name": "S"})
    # Force an unsupported action row (autocode is not undoable).
    await client.post(
        "/api/v1/codings/autocode",
        json={"cid": None, "find_texts": [], "mode": "all", "use_regex": False},
    )
    res = await client.get("/api/v1/audit", params={"action": "coding.autocode"})
    if not res.json()["rows"]:
        return
    aid = res.json()["rows"][0]["id"]
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 422
