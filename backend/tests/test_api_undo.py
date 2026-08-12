"""API tests — history undo / redo (edit review)."""

from __future__ import annotations

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
