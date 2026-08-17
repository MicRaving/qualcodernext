"""API tests — undo cascade parity: no orphaned comments/links when an undo
removes codings, a code, or a source."""

from __future__ import annotations

import os
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import user_settings


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def open_project(client, tmp_path):
    target = tmp_path / "cascade.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text
    yield target
    await client.post("/api/v1/projects/close")


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    return user_settings.SETTINGS_FILE


async def _import_text(client, open_project, name: str, content: str) -> int:
    path = open_project / "documents" / name
    os.makedirs(path.parent, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import", files={"file": (name, content, "text/plain")}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _make_code(client, name: str) -> int:
    res = await client.post("/api/v1/codes", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["cid"]


async def _find_audit_id(client, action: str, index: int = 0) -> int:
    res = await client.get("/api/v1/audit", params={"action": action})
    rows = res.json()["rows"]
    assert rows, f"no audit rows for {action}"
    return rows[index]["id"]


def _count_comments(target, kind: str, target_id: int) -> int:
    with sqlite3.connect(str(target / "data.qda")) as conn:
        return conn.execute(
            "SELECT count(*) FROM comment WHERE target_kind = ? AND target_id = ?",
            (kind, target_id),
        ).fetchone()[0]


async def test_undo_coding_create_removes_coding_comment(client, open_project):
    cid = await _make_code(client, "CC")
    fid = await _import_text(client, open_project, "c.txt", "commentable text")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "commentable", "pos0": 0, "pos1": 11, "owner": "default"},
    )
    ctid = res.json()["ctid"]
    res = await client.post(
        "/api/v1/comments",
        json={"target_kind": "coding", "target_id": ctid, "body": "note"},
    )
    assert res.status_code in (200, 201), res.text
    assert _count_comments(open_project, "coding", ctid) == 1

    aid = await _find_audit_id(client, "coding.create")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    assert _count_comments(open_project, "coding", ctid) == 0


async def test_undo_code_create_removes_code_and_coding_comments(client, open_project):
    cid = await _make_code(client, "DelMe")
    fid = await _import_text(client, open_project, "d.txt", "delete me later")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "delete", "pos0": 0, "pos1": 6, "owner": "default"},
    )
    ctid = res.json()["ctid"]
    await client.post("/api/v1/comments", json={"target_kind": "code", "target_id": cid, "body": "on code"})
    await client.post("/api/v1/comments", json={"target_kind": "coding", "target_id": ctid, "body": "on coding"})
    assert _count_comments(open_project, "code", cid) == 1
    assert _count_comments(open_project, "coding", ctid) == 1

    aid = await _find_audit_id(client, "code.create")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    assert _count_comments(open_project, "code", cid) == 0
    assert _count_comments(open_project, "coding", ctid) == 0
