"""API tests — the history view's supporting endpoints added alongside the
audit undo/redo feature:

  * GET /audit/{id}/undoable — grey-out predicate (no mutation)
  * GET /audit/{id}          — single full row for the detail modal
  * GET /audit?summary=true  — list without the (huge) detail column
  * GET /audit?q=...         — server-side search across every page
  * GET /audit?entity=...    — filter by entity
  * GET /audit/redo-pending  — reconstruct the redo stack across reloads
  * undo/redo record audit.undo / audit.redo marker rows
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import user_settings
from qualcoder_api.services.audit_undo import MISSING_DATA_MESSAGE


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def open_project(client, tmp_path):
    target = tmp_path / "audit_api.qda"
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


def _insert_audit(target, action: str, entity: str, entity_id, detail: dict | None) -> None:
    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute(
            "INSERT INTO audit_log (ts, user, action, entity, entity_id, source_id, detail) "
            "VALUES (datetime('now'), 'default', ?, ?, ?, NULL, ?)",
            (action, entity, entity_id, json.dumps(detail or {})),
        )
        conn.commit()


async def _find_audit_id(client, action: str, index: int = 0) -> int:
    res = await client.get("/api/v1/audit", params={"action": action})
    rows = res.json()["rows"]
    assert rows, f"no audit rows for {action}"
    return rows[index]["id"]


def _find_marker_id(target, action: str) -> int:
    """Internal marker rows (audit.undo / audit.redo) are hidden from the API
    list — read the raw log to find one."""
    with sqlite3.connect(str(target / "data.qda")) as conn:
        row = conn.execute(
            "SELECT id FROM audit_log WHERE action = ? ORDER BY id DESC LIMIT 1",
            (action,),
        ).fetchone()
    assert row, f"no {action} marker row"
    return row[0]


async def _import_text(client, open_project, name: str, content: str) -> int:
    path = open_project / "documents" / name
    os.makedirs(path.parent, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    res = await client.post(
        "/api/v1/sources/import", files={"file": (name, content, "text/plain")}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_undoable_predicate(client, open_project):
    # A coding.create with a full detail row is undoable.
    res = await client.post("/api/v1/codes", json={"name": "U"})
    cid = res.json()["cid"]
    fid = await _import_text(client, open_project, "u.txt", "hello world")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5, "owner": "default"},
    )
    aid = await _find_audit_id(client, "coding.create")

    res = await client.get(f"/api/v1/audit/{aid}/undoable", params={"undo": "true"})
    assert res.status_code == 200, res.text
    assert res.json() == {"undoable": True, "reason": None}


async def test_undoable_predicate_not_invertible(client, open_project, settings_file):
    _insert_audit(open_project, "interchange.import", "project", None, {})
    aid = await _find_audit_id(client, "interchange.import")
    res = await client.get(f"/api/v1/audit/{aid}/undoable", params={"undo": "true"})
    assert res.status_code == 200
    body = res.json()
    assert body["undoable"] is False
    assert "Import actions cannot be undone" in body["reason"]


async def test_undoable_predicate_legacy_missing_data(client, open_project, settings_file):
    _insert_audit(open_project, "code.rename", "code", 11, {})
    aid = await _find_audit_id(client, "code.rename")
    res = await client.get(f"/api/v1/audit/{aid}/undoable", params={"undo": "true"})
    assert res.status_code == 200
    body = res.json()
    assert body["undoable"] is False
    assert body["reason"] == MISSING_DATA_MESSAGE


async def test_undoable_predicate_redo_never_invertible(client, open_project, settings_file):
    _insert_audit(open_project, "source.import", "source", 11, {})
    aid = await _find_audit_id(client, "source.import")
    res = await client.get(f"/api/v1/audit/{aid}/undoable", params={"undo": "false"})
    assert res.status_code == 200
    assert res.json()["undoable"] is False
    assert "import the file again" in res.json()["reason"]


async def test_undoable_predicate_404(client, open_project):
    res = await client.get("/api/v1/audit/999999/undoable")
    assert res.status_code == 404


async def test_get_audit_single_row(client, open_project):
    res = await client.post("/api/v1/codes", json={"name": "G"})
    cid = res.json()["cid"]
    fid = await _import_text(client, open_project, "g.txt", "some text")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "some", "pos0": 0, "pos1": 4, "owner": "default"},
    )
    aid = await _find_audit_id(client, "coding.create")
    res = await client.get(f"/api/v1/audit/{aid}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == aid
    assert body["action"] == "coding.create"
    assert body["detail"]["cid"] == cid


async def test_list_summary_omits_detail(client, open_project):
    res = await client.post("/api/v1/codes", json={"name": "S"})
    cid = res.json()["cid"]
    fid = await _import_text(client, open_project, "s.txt", "a very long body of text " * 50)
    await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "a", "pos0": 0, "pos1": 1, "owner": "default"},
    )
    res = await client.get("/api/v1/audit", params={"summary": "true"})
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert rows
    for row in rows:
        assert row["detail"] == {}
    # The lightweight summary is still populated for the list view.
    coding = next(r for r in rows if r["action"] == "coding.create")
    assert "cid" in coding["summary"]
    # The undoable flag is computed server-side (no per-row round trips).
    assert coding["undoable"] is True


async def test_list_search_is_server_side(client, open_project, settings_file):
    _insert_audit(open_project, "coding.create", "code_text", 1,
                  {"cid": 42, "seltext": "needle phrase here"})
    res = await client.get("/api/v1/audit", params={"q": "needle"})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["rows"][0]["detail"]["cid"] == 42

    res = await client.get("/api/v1/audit", params={"q": "no-such-token"})
    assert res.status_code == 200
    assert res.json()["total"] == 0


async def test_list_filter_by_entity(client, open_project, settings_file):
    _insert_audit(open_project, "code.create", "code", 1, {"cid": 1})
    _insert_audit(open_project, "source.import", "source", 2, {})
    res = await client.get("/api/v1/audit", params={"entity": "code"})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["rows"][0]["entity"] == "code"


async def test_undo_records_marker_and_redo_pending(client, open_project):
    res = await client.post("/api/v1/codes", json={"name": "R"})
    cid = res.json()["cid"]
    fid = await _import_text(client, open_project, "r.txt", "marker text")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "marker", "pos0": 0, "pos1": 6, "owner": "default"},
    )
    aid = await _find_audit_id(client, "coding.create")

    # No undo yet → nothing pending.
    res = await client.get("/api/v1/audit/redo-pending")
    assert res.status_code == 200
    assert res.json() == {"count": 0, "next_id": None}

    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text

    # An audit.undo marker exists and redo-pending reports it.
    marker = _find_marker_id(open_project, "audit.undo")
    assert marker
    res = await client.get("/api/v1/audit/redo-pending")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["next_id"] == aid

    # Redo re-applies and clears the pending state.
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    res = await client.get("/api/v1/audit/redo-pending")
    assert res.json()["count"] == 0
    assert res.json()["next_id"] is None


async def test_undo_marker_is_not_itself_undoable(client, open_project):
    res = await client.post("/api/v1/codes", json={"name": "M"})
    cid = res.json()["cid"]
    fid = await _import_text(client, open_project, "m.txt", "marker2")
    await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "mark", "pos0": 0, "pos1": 4, "owner": "default"},
    )
    aid = await _find_audit_id(client, "coding.create")
    await client.post("/api/v1/audit/undo", json={"id": aid})
    marker = _find_marker_id(open_project, "audit.undo")
    res = await client.get(f"/api/v1/audit/{marker}/undoable")
    assert res.json()["undoable"] is False


async def test_internal_actions_hidden_from_list_and_stats(client, open_project, settings_file):
    # sync.toggle is an internal marker (drives the sync UI) — recorded in the
    # raw log but excluded from the user-facing list and stats.
    await client.put("/api/v1/sync/settings", json={"enabled": True})
    res = await client.get("/api/v1/audit", params={"action": "sync.toggle"})
    assert res.status_code == 200
    assert res.json()["total"] == 0
    res = await client.get("/api/v1/audit")
    assert all(r["action"] != "sync.toggle" for r in res.json()["rows"])
    stats = {row["action"] for row in (await client.get("/api/v1/audit/stats")).json()}
    assert "sync.toggle" not in stats

    marker = _find_marker_id(open_project, "sync.toggle")
    res = await client.get(f"/api/v1/audit/{marker}")
    assert res.status_code == 200
    assert res.json()["action"] == "sync.toggle"
