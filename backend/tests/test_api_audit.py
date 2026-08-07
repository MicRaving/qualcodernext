"""API tests — audit log (project history)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """These tests assert owner == 'default' — keep the developer's real
    user settings (custom coder names, AI config) out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def open_project(client, tmp_path):
    target = tmp_path / "audit.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text
    yield target
    await client.post("/api/v1/projects/close")


async def test_audit_records_coding_and_code(client, open_project):
    res = await client.post("/api/v1/codes", json={"name": "A", "catid": None})
    assert res.status_code == 201, res.text
    cid = res.json()["cid"]

    source = open_project / "documents" / "a.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("a.txt", "hello world", "text/plain")},
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]

    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    assert res.status_code == 201, res.text

    res = await client.get("/api/v1/audit")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 3
    actions = [r["action"] for r in body["rows"]]
    assert "code.create" in actions
    assert "source.import" in actions
    assert "coding.create" in actions
    coding_row = next(r for r in body["rows"] if r["action"] == "coding.create")
    assert coding_row["user"] == "default"
    assert coding_row["source_id"] == fid
    assert coding_row["detail"]["cid"] == cid

    # Filters narrow the result set.
    res = await client.get("/api/v1/audit", params={"action": "coding.create"})
    body = res.json()
    assert body["total"] == 1
    assert all(r["action"] == "coding.create" for r in body["rows"])

    res = await client.get("/api/v1/audit", params={"user": "default"})
    assert res.json()["total"] >= 3


async def test_audit_stats(client, open_project):
    await client.post("/api/v1/codes", json={"name": "S", "catid": None})
    res = await client.get("/api/v1/audit/stats")
    assert res.status_code == 200
    stats = {row["action"]: row["count"] for row in res.json()}
    assert stats.get("code.create", 0) >= 1


async def test_audit_edit_records_before_after(client, open_project):
    source = open_project / "documents" / "edit.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("old text content", encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("edit.txt", "old text content", "text/plain")},
    )
    fid = res.json()["id"]

    res = await client.post(
        "/api/v1/codings/commit-edit",
        json={"fid": fid, "new_text": "new text content here"},
    )
    assert res.status_code == 200, res.text

    res = await client.get("/api/v1/audit", params={"action": "source.edit"})
    rows = res.json()["rows"]
    assert rows, "expected a source.edit audit row"
    detail = rows[0]["detail"]
    assert detail["before"] == "old text content"
    assert detail["after"] == "new text content here"
