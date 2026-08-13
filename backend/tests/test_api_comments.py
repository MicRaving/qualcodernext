"""API tests — threaded comments (comment table, thread CRUD, validation,
audit rows)."""

from __future__ import annotations

import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.comments import router as comments_router
from qualcoder_api.main import app


def _ensure_comments_wired() -> None:
    """Mount the comments router when the v1 router does not carry it yet.

    The router is wired into ``api/v1/router.py`` by the supervisor; until
    then this test file mounts it itself so the suite runs standalone.
    """
    if any(getattr(route, "path", "") == "/api/v1/comments" for route in app.router.routes):
        return
    app.include_router(comments_router, prefix="/api/v1")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    _ensure_comments_wired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "comments.qda"
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


def _coding_rows(target, cid: int, fid: int | None = None) -> dict[str, int]:
    """Insert coding rows directly into the project DB (text/image/av) and
    return their primary keys.

    Bypasses the codings API so the test only depends on the ``comment``
    feature, not on whatever the codings endpoints require at the time.
    """
    pks: dict[str, int] = {}
    with sqlite3.connect(str(target / "data.qda")) as conn:
        cur = conn.execute(
            "INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date) "
            "VALUES (?,?,?,?,?,?,datetime('now'))",
            (cid, fid, "alpha", 0, 5, "tester"),
        )
        pks["text"] = cur.lastrowid
        # Explicit primary keys keep the three coding tables' ids apart (each
        # table has its own autoincrement counter starting at 1).
        conn.execute(
            "INSERT INTO code_image (imid, id, cid, owner, date) VALUES (100,?,?,?,datetime('now'))",
            (fid or 0, cid, "tester"),
        )
        pks["image"] = 100
        conn.execute(
            "INSERT INTO code_av (avid, id, cid, owner, date) VALUES (200,?,?,?,datetime('now'))",
            (fid or 0, cid, "tester"),
        )
        pks["av"] = 200
        conn.commit()
    return pks


async def _thread(client, kind: str, target_id: int) -> list[dict]:
    res = await client.get("/api/v1/comments", params={"target_kind": kind, "target_id": target_id})
    assert res.status_code == 200, res.text
    return res.json()


async def test_comments_crud_and_thread_ordering(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    # Fresh thread is empty.
    assert await _thread(client, "source", fid) == []

    # Three comments, added out of chronological intent but ids order them.
    first = await client.post(
        "/api/v1/comments", json={"target_kind": "source", "target_id": fid, "body": "  first thought  ", "owner": "tester"}
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["id"] > 0
    assert first_body["body"] == "first thought"  # trimmed
    assert first_body["owner"] == "tester"
    assert first_body["target_kind"] == "source"
    assert first_body["target_id"] == fid
    assert first_body["created"]

    second = await client.post(
        "/api/v1/comments", json={"target_kind": "source", "target_id": fid, "body": "second"})
    assert second.status_code == 201, second.text

    third = await client.post(
        "/api/v1/comments", json={"target_kind": "source", "target_id": fid, "body": "third"})
    assert third.status_code == 201, third.text

    # Thread comes back oldest-first with coder + created on every row.
    thread = await _thread(client, "source", fid)
    assert [c["id"] for c in thread] == [first_body["id"], second.json()["id"], third.json()["id"]]
    assert [c["body"] for c in thread] == ["first thought", "second", "third"]
    assert all(c["owner"] and c["created"] for c in thread)

    # PATCH edits the body (and only the body).
    patched = await client.patch(
        f"/api/v1/comments/{first_body['id']}", json={"body": "  revised  "}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["body"] == "revised"
    assert patched.json()["owner"] == "tester"
    assert patched.json()["target_id"] == fid

    # Thread reflects the edit without reordering.
    thread = await _thread(client, "source", fid)
    assert [c["body"] for c in thread] == ["revised", "second", "third"]

    # DELETE removes a comment; deleting it again yields 404.
    assert (await client.delete(f"/api/v1/comments/{second.json()['id']}")).status_code == 204
    assert [c["id"] for c in await _thread(client, "source", fid)] == [first_body["id"], third.json()["id"]]
    assert (await client.delete(f"/api/v1/comments/{second.json()['id']}")).status_code == 404

    # Missing comment for PATCH yields 404.
    assert (await client.patch("/api/v1/comments/9999", json={"body": "x"})).status_code == 404


async def test_comments_validation(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    # Empty body on create → 422.
    assert (
        await client.post("/api/v1/comments", json={"target_kind": "source", "target_id": fid, "body": "   "})
    ).status_code == 422

    # Unknown target kind → 422 on create and on list.
    assert (
        await client.post("/api/v1/comments", json={"target_kind": "memo", "target_id": 1, "body": "x"})
    ).status_code == 422
    assert (await client.get("/api/v1/comments", params={"target_kind": "memo", "target_id": 1})).status_code == 422

    # Missing target row → 404 (whitelisted kinds with a bogus id).
    for kind in ("source", "code", "case", "coding", "annotation", "creative_item", "qtt_item"):
        res = await client.post(
            "/api/v1/comments", json={"target_kind": kind, "target_id": 999999, "body": "x"}
        )
        assert res.status_code == 404, (kind, res.text)

    # Empty body on PATCH → 422.
    made = (await client.post(
        "/api/v1/comments", json={"target_kind": "source", "target_id": fid, "body": "ok"}
    )).json()
    assert (
        await client.patch(f"/api/v1/comments/{made['id']}", json={"body": "  "})
    ).status_code == 422

    # A valid comment still lands afterwards.
    res = await client.post(
        "/api/v1/comments", json={"target_kind": "source", "target_id": fid, "body": "beta"}
    )
    assert res.status_code == 201, res.text


async def test_comments_on_all_target_kinds(project_client):
    client, target = project_client
    fid = await _one_source(client)
    code = (await client.post("/api/v1/codes", json={"name": "c1"})).json()
    case = (await client.post("/api/v1/cases", json={"name": "P1"})).json()
    coding_pks = _coding_rows(target, code["cid"], fid)
    annotation = (await client.post(
        "/api/v1/annotations", json={"fid": fid, "pos0": 0, "pos1": 1, "memo": "note"}
    )).json()
    creative = (await client.post("/api/v1/creative", json={"text": "idea"})).json()
    sheet = (await client.post("/api/v1/qtt", json={"name": "Board", "kind": "qual"})).json()
    qtt_item = (await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "note", "payload": {"text": "thought"}},
    )).json()

    targets = [
        ("source", fid),
        ("code", code["cid"]),
        ("case", case["caseid"]),
        ("coding", coding_pks["text"]),
        ("annotation", annotation["anid"]),
        ("creative_item", creative["id"]),
        ("qtt_item", qtt_item["id"]),
    ]
    for kind, target_id in targets:
        res = await client.post(
            "/api/v1/comments", json={"target_kind": kind, "target_id": target_id, "body": f"on {kind}"}
        )
        assert res.status_code == 201, (kind, res.text)

    # Every thread resolves and threads are isolated per target.
    for kind, target_id in targets:
        thread = await _thread(client, kind, target_id)
        assert len(thread) == 1
        assert thread[0]["target_kind"] == kind
        assert thread[0]["target_id"] == target_id
    assert await _thread(client, "source", fid) != await _thread(client, "code", code["cid"])


async def test_coding_target_covers_all_coding_tables(project_client):
    client, target = project_client
    code = (await client.post("/api/v1/codes", json={"name": "img"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("pic.png", b"\x89PNGfake", "image/png")}
    )
    sid = (await client.get("/api/v1/sources")).json()[0]["id"]
    pks = _coding_rows(target, code["cid"], sid)

    # The coding kind accepts any of the three tables by id.
    assert (
        await client.post("/api/v1/comments", json={"target_kind": "coding", "target_id": pks["image"], "body": "image"})
    ).status_code == 201
    assert (
        await client.post("/api/v1/comments", json={"target_kind": "coding", "target_id": pks["av"], "body": "av"})
    ).status_code == 201

    # Both comments land on the coding thread for their own ids.
    assert len(await _thread(client, "coding", pks["image"])) == 1
    assert len(await _thread(client, "coding", pks["av"])) == 1


async def test_comments_audit_rows(project_client):
    client, _ = project_client
    fid = await _one_source(client)

    created = await client.post(
        "/api/v1/comments",
        json={"target_kind": "source", "target_id": fid, "body": "quote check", "owner": "tester"},
    )
    comment_id = created.json()["id"]

    rows = (await client.get("/api/v1/audit", params={"action": "comment.create"})).json()["rows"]
    assert len(rows) == 1
    create_row = rows[0]
    assert create_row["user"] == "tester"
    assert create_row["entity"] == "comment"
    assert create_row["entity_id"] == comment_id
    assert create_row["detail"]["target_kind"] == "source"
    assert create_row["detail"]["target_id"] == fid
    assert create_row["detail"]["body"] == "quote check"

    await client.patch(f"/api/v1/comments/{comment_id}", json={"body": "revised"})
    rows = (await client.get("/api/v1/audit", params={"action": "comment.update"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == comment_id
    assert rows[0]["detail"]["body"] == "revised"
    assert rows[0]["detail"]["target_id"] == fid

    await client.delete(f"/api/v1/comments/{comment_id}")
    rows = (await client.get("/api/v1/audit", params={"action": "comment.delete"})).json()["rows"]
    assert len(rows) == 1
    delete_row = rows[0]
    assert delete_row["entity_id"] == comment_id
    assert delete_row["detail"]["target_kind"] == "source"
    assert delete_row["detail"]["target_id"] == fid
    assert delete_row["detail"]["body"] == "revised"
