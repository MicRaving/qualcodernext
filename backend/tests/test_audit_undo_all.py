"""API tests — history undo / redo for the remaining audit families.

Covers: source import/link/delete/link_fix/replace, transcribe.start
(cancel-when-queued), autocode, coding.undo, code.memo (MCP), bookmarks,
speakers, pseudonyms, references, saved filters, stored SQL, coders, sync
toggle, dictionaries, code sets, R scripts, QTT sheets/items and graphs.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

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
    target = tmp_path / "undo_all.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text
    yield target
    await client.post("/api/v1/projects/close")


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Keep the developer's real ~/.qualcoder/settings.json out of the run."""
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    return user_settings.SETTINGS_FILE


async def _find_audit_id(client, action: str, index: int = 0) -> int:
    res = await client.get("/api/v1/audit", params={"action": action})
    rows = res.json()["rows"]
    assert rows, f"no audit rows for {action}"
    return rows[index]["id"]


def _find_marker_id(target, action: str) -> int:
    """Internal marker rows (sync.toggle / audit.undo / audit.redo) are hidden
    from the API list — read the raw log to find one."""
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


async def _make_code(client, name: str) -> int:
    res = await client.post("/api/v1/codes", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["cid"]


def _insert_audit(target, action: str, entity: str, entity_id, detail: dict) -> None:
    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute(
            "INSERT INTO audit_log (ts, user, action, entity, entity_id, source_id, detail) "
            "VALUES (datetime('now'), 'default', ?, ?, ?, NULL, ?)",
            (action, entity, entity_id, json.dumps(detail)),
        )
        conn.commit()


def _all_items(sheet: dict) -> list[dict]:
    return [i for items in sheet["items"].values() for i in items]


async def _undo(client, aid: int) -> dict:
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 200, res.text
    return res.json()


async def _redo(client, aid: int) -> dict:
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 200, res.text
    return res.json()


# ----------------------------------------------------------------------
# Sources: import / link / delete / link_fix / replace
# ----------------------------------------------------------------------


async def test_undo_source_import_and_link(client, open_project):
    fid = await _import_text(client, open_project, "imp.txt", "import me")
    aid = await _find_audit_id(client, "source.import")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/sources/{fid}")).status_code == 404
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 422  # cannot redo an import

    res = await client.post("/api/v1/sources/link", json={"path": "C:/virtual/linked.txt"})
    assert res.status_code == 200, res.text
    link_id = res.json()["id"]
    aid = await _find_audit_id(client, "source.link")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/sources/{link_id}")).status_code == 404


async def test_undo_redo_source_delete(client, open_project):
    fid = await _import_text(client, open_project, "del.txt", "delete me text")
    cid = await _make_code(client, "DelCode")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "delete", "pos0": 0, "pos1": 6},
    )
    ctid = res.json()["ctid"]
    res = await client.post(
        "/api/v1/annotations", json={"fid": fid, "pos0": 0, "pos1": 6, "memo": "ann"}
    )
    anid = res.json()["anid"]

    res = await client.delete(f"/api/v1/sources/{fid}")
    assert res.status_code == 204
    assert (await client.get(f"/api/v1/sources/{fid}")).status_code == 404

    aid = await _find_audit_id(client, "source.delete")
    await _undo(client, aid)
    src = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert src["name"] == "del.txt"
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid for c in codings)
    anns = (await client.get(f"/api/v1/annotations/{fid}")).json()
    assert any(a["anid"] == anid for a in anns)

    await _redo(client, aid)
    assert (await client.get(f"/api/v1/sources/{fid}")).status_code == 404


async def test_undo_redo_source_link_fix(client, open_project):
    fid = await _import_text(client, open_project, "fix.txt", "fix me")
    res = await client.patch(
        f"/api/v1/sources/{fid}/mediapath", json={"mediapath": "C:/data/fix.txt"}
    )
    assert res.status_code == 200, res.text

    aid = await _find_audit_id(client, "source.link_fix")
    await _undo(client, aid)
    src = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert src["mediapath"] == "/docs/fix.txt"
    await _redo(client, aid)
    src = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert src["mediapath"] == "docs:C:/data/fix.txt"


async def test_undo_source_replace(client, open_project):
    fid = await _import_text(client, open_project, "rep.txt", "old text content here")
    cid = await _make_code(client, "RepCode")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "old text", "pos0": 0, "pos1": 8},
    )
    ctid = res.json()["ctid"]

    res = await client.post(
        f"/api/v1/sources/{fid}/replace",
        files={"file": ("new.txt", "new text content here", "text/plain")},
    )
    assert res.status_code == 200, res.text
    src = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert src["name"] == "new.txt"

    aid = await _find_audit_id(client, "source.replace")
    await _undo(client, aid)
    src = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert src["name"] == "rep.txt"
    assert src["fulltext"] == "old text content here"
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid and c["pos0"] == 0 for c in codings)

    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 422


async def test_undo_transcribe_start_queued(client, open_project):
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("talk.mp3", b"ID3fake", "audio/mpeg")}
    )
    media_id = res.json()["id"]
    res = await client.post(
        "/api/v1/transcribe", json={"source_id": media_id, "start": False}
    )
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    aid = await _find_audit_id(client, "transcribe.start")
    await _undo(client, aid)
    job = (await client.get(f"/api/v1/transcribe/jobs/{job_id}")).json()
    assert job["state"] == "cancelled"
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 422


# ----------------------------------------------------------------------
# Codings: autocode + the user's own undo endpoint
# ----------------------------------------------------------------------


async def test_undo_redo_autocode(client, open_project):
    fid = await _import_text(client, open_project, "ac.txt", "cat sat cat mat")
    cid = await _make_code(client, "AC")
    res = await client.post(
        "/api/v1/codings/autocode",
        json={"cids": [cid], "find_texts": ["cat"], "mode": "all", "use_regex": False},
    )
    assert res.status_code == 201, res.text
    assert res.json()["count"] == 2
    assert len((await client.get(f"/api/v1/codings/text/{fid}")).json()) == 2

    aid = await _find_audit_id(client, "coding.autocode")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/codings/text/{fid}")).json() == []
    await _redo(client, aid)
    assert len((await client.get(f"/api/v1/codings/text/{fid}")).json()) == 2


async def test_undo_redo_coding_undo_endpoint(client, open_project):
    fid = await _import_text(client, open_project, "cu.txt", "hello world")
    cid = await _make_code(client, "CU")
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    ctid = res.json()["ctid"]
    await client.delete(f"/api/v1/codings/text/{ctid}")
    audit = (await client.get("/api/v1/audit", params={"action": "coding.delete"})).json()["rows"][0]

    res = await client.post("/api/v1/codings/undo", json={"items": [audit["detail"]]})
    assert res.status_code == 200, res.text
    assert res.json()["restored"] == 1

    aid = await _find_audit_id(client, "coding.undo")
    await _undo(client, aid)
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert all(c["ctid"] != ctid for c in codings)
    await _redo(client, aid)
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert any(c["ctid"] == ctid for c in codings)


async def test_undo_code_memo(client, open_project):
    cid = await _make_code(client, "MemoCode")
    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        conn.execute("UPDATE code_name SET memo = 'old' WHERE cid = ?", (cid,))
        conn.commit()
    _insert_audit(open_project, "code.memo", "code", cid, {"memo": "new", "old_memo": "old"})

    aid = await _find_audit_id(client, "code.memo")
    await _undo(client, aid)
    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        memo = conn.execute("SELECT memo FROM code_name WHERE cid = ?", (cid,)).fetchone()[0]
    assert memo == "old"
    await _redo(client, aid)
    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        memo = conn.execute("SELECT memo FROM code_name WHERE cid = ?", (cid,)).fetchone()[0]
    assert memo == "new"


# ----------------------------------------------------------------------
# Tools: bookmarks / speakers / pseudonyms / references / filters
# ----------------------------------------------------------------------


async def test_undo_redo_bookmark(client, open_project):
    fid = await _import_text(client, open_project, "bm.txt", "bookmark text")
    await client.put("/api/v1/bookmarks", json={"file_id": fid, "pos": 10})
    await client.put("/api/v1/bookmarks", json={"file_id": fid, "pos": 20})

    aid = await _find_audit_id(client, "bookmark.set")
    await _undo(client, aid)
    bookmarks = (await client.get("/api/v1/bookmarks")).json()
    assert bookmarks["bookmark_file_id"] == fid
    assert bookmarks["bookmark_pos"] == 10
    await _redo(client, aid)
    bookmarks = (await client.get("/api/v1/bookmarks")).json()
    assert bookmarks["bookmark_pos"] == 20


async def test_undo_speakers_mark(client, open_project):
    fid = await _import_text(client, open_project, "sp.txt", "Alice: Hello there\nBob: Hi Alice")
    res = await client.post(
        "/api/v1/speakers/mark", json={"fid": fid, "identifiers": ["name"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["turns_marked"] == 2
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert len(codings) == 2

    aid = await _find_audit_id(client, "speakers.mark")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/codings/text/{fid}")).json() == []
    tree = (await client.get("/api/v1/codes")).json()
    assert all(c["kind"] != "code" or c["name"] not in ("Alice", "Bob") for c in tree)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 422


async def test_undo_redo_pseudonym(client, open_project, settings_file):
    res = await client.post(
        "/api/v1/pseudonyms", json={"original": "John Doe", "pseudonym": "JDOE"}
    )
    assert res.status_code == 200, res.text

    aid = await _find_audit_id(client, "pseudonym.add")
    await _undo(client, aid)
    assert (await client.get("/api/v1/pseudonyms")).json()["pseudonyms"] == []
    await _redo(client, aid)
    pseudonyms = (await client.get("/api/v1/pseudonyms")).json()["pseudonyms"]
    assert any(p["original"] == "John Doe" and p["pseudonym"] == "JDOE" for p in pseudonyms)

    res = await client.delete("/api/v1/pseudonyms/John Doe")
    assert res.status_code == 200
    aid = await _find_audit_id(client, "pseudonym.delete")
    await _undo(client, aid)
    pseudonyms = (await client.get("/api/v1/pseudonyms")).json()["pseudonyms"]
    assert any(p["original"] == "John Doe" and p["pseudonym"] == "JDOE" for p in pseudonyms)
    await _redo(client, aid)
    assert (await client.get("/api/v1/pseudonyms")).json()["pseudonyms"] == []


async def test_undo_redo_references(client, open_project):
    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        conn.execute("INSERT INTO ris (risid, tag, longtag, value) VALUES (42, 'TI', 'TI', 'Test title')")
        conn.execute("INSERT INTO ris (risid, tag, longtag, value) VALUES (42, 'AU', 'AU', 'Doe, Jane')")
        conn.commit()

    # attach → undo deletes the created source; redo restores it + link.
    res = await client.post(
        "/api/v1/references/42/attach",
        files={"file": ("att1.pdf", b"%PDF-1.4\nfake", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    source_id = res.json()["source_id"]
    aid = await _find_audit_id(client, "reference.attach")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/sources/{source_id}")).status_code == 404
    await _redo(client, aid)
    src = (await client.get(f"/api/v1/sources/{source_id}")).json()
    assert src["risid"] == 42

    # detach → undo re-links; redo unlinks again.
    res = await client.delete(f"/api/v1/references/42/attach/{source_id}")
    assert res.status_code == 204
    aid = await _find_audit_id(client, "reference.detach")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/sources/{source_id}")).json()["risid"] == 42
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/sources/{source_id}")).json()["risid"] is None

    # delete → undo restores the ris rows; redo removes them again.
    res = await client.delete("/api/v1/references/42")
    assert res.status_code == 204
    assert (await client.get("/api/v1/references")).json()["references"] == []
    aid = await _find_audit_id(client, "reference.delete")
    await _undo(client, aid)
    refs = (await client.get("/api/v1/references")).json()["references"]
    assert any(r["risid"] == 42 and r["title"] == "Test title" for r in refs)
    await _redo(client, aid)
    assert (await client.get("/api/v1/references")).json()["references"] == []


async def test_undo_redo_filters_and_stored_sql(client, open_project):
    res = await client.post("/api/v1/sources/filters", json={"name": "f1", "filter": "{}"})
    filterid = res.json()["filterid"]

    aid = await _find_audit_id(client, "filter.create")
    await _undo(client, aid)
    filters = (await client.get("/api/v1/sources/filters")).json()["filters"]
    assert all(f["filterid"] != filterid for f in filters)
    await _redo(client, aid)
    filters = (await client.get("/api/v1/sources/filters")).json()["filters"]
    assert any(f["filterid"] == filterid for f in filters)

    await client.delete(f"/api/v1/sources/filters/{filterid}")
    aid = await _find_audit_id(client, "filter.delete")
    await _undo(client, aid)
    filters = (await client.get("/api/v1/sources/filters")).json()["filters"]
    assert any(f["filterid"] == filterid and f["name"] == "f1" for f in filters)
    await _redo(client, aid)
    filters = (await client.get("/api/v1/sources/filters")).json()["filters"]
    assert all(f["filterid"] != filterid for f in filters)

    await client.post("/api/v1/sql/saved", json={"title": "q1", "ssql": "SELECT 1"})
    aid = await _find_audit_id(client, "sql.save")
    await _undo(client, aid)
    assert (await client.get("/api/v1/sql/saved")).json()["rows"] == []
    await _redo(client, aid)
    assert len((await client.get("/api/v1/sql/saved")).json()["rows"]) == 1

    await client.delete("/api/v1/sql/saved/q1")
    aid = await _find_audit_id(client, "sql.delete")
    await _undo(client, aid)
    rows = (await client.get("/api/v1/sql/saved")).json()["rows"]
    assert any(r["title"] == "q1" and r["ssql"] == "SELECT 1" for r in rows)
    await _redo(client, aid)
    assert (await client.get("/api/v1/sql/saved")).json()["rows"] == []


# ----------------------------------------------------------------------
# Settings-backed: coders / sync toggle
# ----------------------------------------------------------------------


async def test_undo_redo_coders(client, open_project, settings_file):
    res = await client.post("/api/v1/coders", json={"name": "Bob"})
    assert res.status_code == 201, res.text

    aid = await _find_audit_id(client, "coder.create")
    await _undo(client, aid)
    names = [c["name"] for c in (await client.get("/api/v1/coders")).json()["coders"]]
    assert "Bob" not in names
    await _redo(client, aid)
    names = [c["name"] for c in (await client.get("/api/v1/coders")).json()["coders"]]
    assert "Bob" in names

    res = await client.delete("/api/v1/coders/Bob")
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "coder.delete")
    await _undo(client, aid)
    names = [c["name"] for c in (await client.get("/api/v1/coders")).json()["coders"]]
    assert "Bob" in names
    await _redo(client, aid)
    names = [c["name"] for c in (await client.get("/api/v1/coders")).json()["coders"]]
    assert "Bob" not in names

    # Visibility: hide → undo restores the coder as visible again.
    # (Creation registers the coder in coder_names with visibility=1, so the
    # recorded "before" of the first hide is visible=1 — undo returns there.)
    await client.post("/api/v1/coders", json={"name": "Bob"})
    res = await client.put("/api/v1/coders/Bob/visibility", json={"visible": False})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "coder.visibility")
    await _undo(client, aid)
    visibility = (await client.get("/api/v1/coders/visibility")).json()["visibility"]
    assert visibility.get("Bob") == 1
    await _redo(client, aid)
    visibility = (await client.get("/api/v1/coders/visibility")).json()["visibility"]
    assert visibility.get("Bob") == 0


async def test_undo_redo_sync_toggle(client, open_project, settings_file):
    res = await client.put("/api/v1/sync/settings", json={"enabled": True})
    assert res.status_code == 200, res.text
    assert (await client.get("/api/v1/sync/settings")).json()["enabled"] is True

    aid = _find_marker_id(open_project, "sync.toggle")
    await _undo(client, aid)
    assert (await client.get("/api/v1/sync/settings")).json()["enabled"] is False
    await _redo(client, aid)
    assert (await client.get("/api/v1/sync/settings")).json()["enabled"] is True


# ----------------------------------------------------------------------
# Dictionaries / code sets / R scripts
# ----------------------------------------------------------------------


async def test_undo_redo_dictionary(client, open_project):
    res = await client.post("/api/v1/dictionaries", json={"name": "dictA"})
    dict_id = res.json()["id"]
    res = await client.post(
        f"/api/v1/dictionaries/{dict_id}/entries",
        json={"code_name": "CodeX", "term": "alpha"},
    )
    entry_id = res.json()["id"]

    # entry add → undo/redo
    aid = await _find_audit_id(client, "dictionary.entry_add")
    await _undo(client, aid)
    d = (await client.get("/api/v1/dictionaries")).json()[0]
    assert all(e["id"] != entry_id for e in d["entries"])
    await _redo(client, aid)
    d = (await client.get("/api/v1/dictionaries")).json()[0]
    assert any(e["id"] == entry_id for e in d["entries"])

    # entry delete → undo/redo
    await client.delete(f"/api/v1/dictionaries/entries/{entry_id}")
    aid = await _find_audit_id(client, "dictionary.entry_delete")
    await _undo(client, aid)
    d = (await client.get("/api/v1/dictionaries")).json()[0]
    assert any(e["id"] == entry_id and e["term"] == "alpha" for e in d["entries"])
    await _redo(client, aid)
    d = (await client.get("/api/v1/dictionaries")).json()[0]
    assert all(e["id"] != entry_id for e in d["entries"])

    # rename → undo/redo
    res = await client.patch(f"/api/v1/dictionaries/{dict_id}", json={"name": "dictB"})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "dictionary.update")
    await _undo(client, aid)
    assert (await client.get("/api/v1/dictionaries")).json()[0]["name"] == "dictA"
    await _redo(client, aid)
    assert (await client.get("/api/v1/dictionaries")).json()[0]["name"] == "dictB"

    # delete → undo restores dict + entries; redo removes them again.
    res = await client.post(
        f"/api/v1/dictionaries/{dict_id}/entries",
        json={"code_name": "CodeX", "term": "beta"},
    )
    assert res.status_code == 201, res.text
    await client.delete(f"/api/v1/dictionaries/{dict_id}")
    aid = await _find_audit_id(client, "dictionary.delete")
    await _undo(client, aid)
    d = (await client.get("/api/v1/dictionaries")).json()[0]
    assert d["name"] == "dictB"
    assert len(d["entries"]) == 1
    await _redo(client, aid)
    assert (await client.get("/api/v1/dictionaries")).json() == []

    # create → undo/redo
    aid = await _find_audit_id(client, "dictionary.create")
    await _undo(client, aid)
    assert (await client.get("/api/v1/dictionaries")).json() == []
    await _redo(client, aid)
    assert (await client.get("/api/v1/dictionaries")).json()[0]["name"] == "dictA"


async def test_undo_redo_code_set(client, open_project):
    cid = await _make_code(client, "CS")
    res = await client.post("/api/v1/code-sets", json={"name": "setA"})
    set_id = res.json()["id"]

    # members add → undo/redo
    res = await client.post(f"/api/v1/code-sets/{set_id}/members", json={"cids": [cid]})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "code_set.members_add")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/code-sets/{set_id}")).json()["members"] == []
    await _redo(client, aid)
    assert len((await client.get(f"/api/v1/code-sets/{set_id}")).json()["members"]) == 1

    # members remove → undo/redo
    await client.request(
        "DELETE", f"/api/v1/code-sets/{set_id}/members", json={"cids": [cid]}
    )
    aid = await _find_audit_id(client, "code_set.members_remove")
    await _undo(client, aid)
    assert len((await client.get(f"/api/v1/code-sets/{set_id}")).json()["members"]) == 1
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/code-sets/{set_id}")).json()["members"] == []

    # rename → undo/redo
    res = await client.patch(f"/api/v1/code-sets/{set_id}", json={"name": "setB"})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "code_set.rename")
    await _undo(client, aid)
    sets = (await client.get("/api/v1/code-sets")).json()
    assert next(s for s in sets if s["id"] == set_id)["name"] == "setA"
    await _redo(client, aid)
    sets = (await client.get("/api/v1/code-sets")).json()
    assert next(s for s in sets if s["id"] == set_id)["name"] == "setB"

    # delete → undo restores set + members; redo removes them.
    await client.post(f"/api/v1/code-sets/{set_id}/members", json={"cids": [cid]})
    await client.delete(f"/api/v1/code-sets/{set_id}")
    aid = await _find_audit_id(client, "code_set.delete")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/code-sets/{set_id}")).json()
    assert data["set_id"] == set_id
    assert len(data["members"]) == 1
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/code-sets/{set_id}")).status_code == 404

    # create → undo/redo
    aid = await _find_audit_id(client, "code_set.create")
    await _undo(client, aid)
    assert all(s["id"] != set_id for s in (await client.get("/api/v1/code-sets")).json())
    await _redo(client, aid)
    assert any(s["id"] == set_id for s in (await client.get("/api/v1/code-sets")).json())


async def test_undo_redo_r_script(client, open_project):
    res = await client.post("/api/v1/r/scripts", json={"name": "s1", "script": "print(1)"})
    script_id = res.json()["id"]

    # update → undo/redo (name + script)
    res = await client.patch(
        f"/api/v1/r/scripts/{script_id}", json={"name": "s2", "script": "print(2)"}
    )
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "r_script.update")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/r/scripts/{script_id}")).json()
    assert data["name"] == "s1"
    assert data["script"] == "print(1)"
    await _redo(client, aid)
    data = (await client.get(f"/api/v1/r/scripts/{script_id}")).json()
    assert data["name"] == "s2"
    assert data["script"] == "print(2)"

    # delete → undo/redo
    await client.delete(f"/api/v1/r/scripts/{script_id}")
    aid = await _find_audit_id(client, "r_script.delete")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/r/scripts/{script_id}")).status_code == 200
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/r/scripts/{script_id}")).status_code == 404

    # create → undo/redo
    aid = await _find_audit_id(client, "r_script.create")
    await _undo(client, aid)
    assert all(s["id"] != script_id for s in (await client.get("/api/v1/r/scripts")).json())
    await _redo(client, aid)
    assert any(s["id"] == script_id for s in (await client.get("/api/v1/r/scripts")).json())


# ----------------------------------------------------------------------
# QTT sheets/items
# ----------------------------------------------------------------------


async def test_undo_redo_qtt(client, open_project):
    fid = await _import_text(client, open_project, "qtt.txt", "hello world segment")
    res = await client.post("/api/v1/qtt", json={"name": "sheet1"})
    sheet_id = res.json()["id"]

    # item create → undo/redo
    res = await client.post(
        f"/api/v1/qtt/{sheet_id}/items",
        json={"section": "Insights", "kind": "note", "payload": {"text": "note1"}},
    )
    item_id = res.json()["id"]
    aid = await _find_audit_id(client, "qtt.item.create")
    await _undo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    assert all(i["id"] != item_id for i in _all_items(sheet))
    await _redo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    assert any(i["id"] == item_id for i in _all_items(sheet))

    # item update → undo/redo
    res = await client.patch(f"/api/v1/qtt/items/{item_id}", json={"payload": {"text": "note2"}})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "qtt.item.update")
    await _undo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    item = next(i for i in _all_items(sheet) if i["id"] == item_id)
    assert item["payload"]["text"] == "note1"
    await _redo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    item = next(i for i in _all_items(sheet) if i["id"] == item_id)
    assert item["payload"]["text"] == "note2"

    # item delete → undo/redo
    await client.delete(f"/api/v1/qtt/items/{item_id}")
    aid = await _find_audit_id(client, "qtt.item.delete")
    await _undo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    assert any(i["id"] == item_id for i in _all_items(sheet))
    await _redo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    assert all(i["id"] != item_id for i in _all_items(sheet))

    # send-segment → undo/redo
    res = await client.post(
        f"/api/v1/qtt/{sheet_id}/send-segment", json={"fid": fid, "pos0": 0, "pos1": 5}
    )
    seg_id = res.json()["id"]
    aid = await _find_audit_id(client, "qtt.send_segment")
    await _undo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    assert all(i["id"] != seg_id for i in _all_items(sheet))
    await _redo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    assert any(i["id"] == seg_id and i["kind"] == "segment" for i in _all_items(sheet))

    # sheet update → undo/redo
    res = await client.patch(f"/api/v1/qtt/{sheet_id}", json={"name": "sheet2"})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "qtt.update")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/qtt/{sheet_id}")).json()["name"] == "sheet1"
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/qtt/{sheet_id}")).json()["name"] == "sheet2"

    # sheet delete → undo restores sheet + items
    await client.delete(f"/api/v1/qtt/{sheet_id}")
    aid = await _find_audit_id(client, "qtt.delete")
    await _undo(client, aid)
    sheet = (await client.get(f"/api/v1/qtt/{sheet_id}")).json()
    assert sheet["name"] == "sheet2"
    assert any(i["kind"] == "segment" for i in _all_items(sheet))
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/qtt/{sheet_id}")).status_code == 404

    # sheet create → undo/redo
    aid = await _find_audit_id(client, "qtt.create")
    await _undo(client, aid)
    assert all(s["id"] != sheet_id for s in (await client.get("/api/v1/qtt")).json())
    await _redo(client, aid)
    assert any(s["id"] == sheet_id for s in (await client.get("/api/v1/qtt")).json())


# ----------------------------------------------------------------------
# Graphs
# ----------------------------------------------------------------------


async def test_undo_redo_graphs(client, open_project):
    cid = await _make_code(client, "GraphCode")
    res = await client.post("/api/v1/graphs", json={"name": "g1"})
    grid = res.json()["grid"]

    # item add → undo/redo (undo the FIRST cdct item row)
    res = await client.post(
        f"/api/v1/graphs/{grid}/items/cdct", json={"kind": "code", "ref_id": cid}
    )
    gtextid = res.json()["gtextid"]
    aid = await _find_audit_id(client, "graph.item_add")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert all(i["gtextid"] != gtextid for i in data["cdct_items"])
    await _redo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert any(i["gtextid"] == gtextid for i in data["cdct_items"])

    # item update → undo/redo
    res = await client.patch(
        f"/api/v1/graphs/{grid}/items/cdct/{gtextid}", json={"x": 100}
    )
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "graph.item_update")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    item = next(i for i in data["cdct_items"] if i["gtextid"] == gtextid)
    assert item["x"] == 0
    await _redo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    item = next(i for i in data["cdct_items"] if i["gtextid"] == gtextid)
    assert item["x"] == 100

    # line add → undo/redo
    res = await client.post(
        f"/api/v1/graphs/{grid}/items/cdct", json={"kind": "code", "ref_id": cid}
    )
    gtextid2 = res.json()["gtextid"]
    res = await client.post(
        f"/api/v1/graphs/{grid}/lines/cdct",
        json={"from_node": gtextid, "to_node": gtextid2},
    )
    glineid = res.json()["glineid"]
    aid = await _find_audit_id(client, "graph.line_add")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert all(ln["glineid"] != glineid for ln in data["cdct_lines"])
    await _redo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert any(ln["glineid"] == glineid for ln in data["cdct_lines"])

    # line update → undo/redo
    res = await client.patch(
        f"/api/v1/graphs/{grid}/lines/cdct/{glineid}", json={"color": "#ff0000"}
    )
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "graph.line_update")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    line = next(ln for ln in data["cdct_lines"] if ln["glineid"] == glineid)
    assert line["color"] == "#888888"
    await _redo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    line = next(ln for ln in data["cdct_lines"] if ln["glineid"] == glineid)
    assert line["color"] == "#ff0000"

    # line delete → undo/redo
    await client.delete(f"/api/v1/graphs/{grid}/lines/cdct/{glineid}")
    aid = await _find_audit_id(client, "graph.line_delete")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert any(ln["glineid"] == glineid for ln in data["cdct_lines"])
    await _redo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert all(ln["glineid"] != glineid for ln in data["cdct_lines"])

    # item delete → undo/redo
    await client.delete(f"/api/v1/graphs/{grid}/items/cdct/{gtextid}")
    aid = await _find_audit_id(client, "graph.item_delete")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert any(i["gtextid"] == gtextid for i in data["cdct_items"])
    await _redo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert all(i["gtextid"] != gtextid for i in data["cdct_items"])

    # graph update → undo/redo
    res = await client.patch(f"/api/v1/graphs/{grid}", json={"name": "g2"})
    assert res.status_code == 200, res.text
    aid = await _find_audit_id(client, "graph.update")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/graphs/{grid}")).json()["graph"]["name"] == "g1"
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/graphs/{grid}")).json()["graph"]["name"] == "g2"

    # graph delete → undo restores the graph and its items
    await client.delete(f"/api/v1/graphs/{grid}")
    aid = await _find_audit_id(client, "graph.delete")
    await _undo(client, aid)
    data = (await client.get(f"/api/v1/graphs/{grid}")).json()
    assert data["graph"]["name"] == "g2"
    assert len(data["cdct_items"]) == 1
    await _redo(client, aid)
    assert (await client.get(f"/api/v1/graphs/{grid}")).status_code == 404

    # graph create → undo/redo
    aid = await _find_audit_id(client, "graph.create")
    await _undo(client, aid)
    graphs = (await client.get("/api/v1/graphs")).json()["graphs"]
    assert all(g["grid"] != grid for g in graphs)
    await _redo(client, aid)
    graphs = (await client.get("/api/v1/graphs")).json()["graphs"]
    assert any(g["grid"] == grid for g in graphs)

    # model-generated graph: undo removes it, redo is not possible.
    res = await client.post(
        "/api/v1/graphs/models", json={"model": "file-hierarchy", "name": "mg"}
    )
    assert res.status_code == 201, res.text
    mgrid = res.json()["grid"]
    aid = await _find_audit_id(client, "graph.create")
    await _undo(client, aid)
    assert (await client.get(f"/api/v1/graphs/{mgrid}")).status_code == 404
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 422


# ----------------------------------------------------------------------
# R run cancel + remaining unsupported messages
# ----------------------------------------------------------------------


async def test_undo_r_run_cancels_queued_job(client, open_project):
    from qualcoder_api.services import r_service

    with r_service._jobs_lock:
        r_service._JOBS["fakejob"] = {
            "id": "fakejob",
            "state": "queued",
            "message": "queued",
            "_cancelled": threading.Event(),
            "_proc": None,
        }
    try:
        _insert_audit(open_project, "r.run", "r", None, {"job_id": "fakejob", "script_len": 5})
        aid = await _find_audit_id(client, "r.run")
        await _undo(client, aid)
        assert r_service.get_r_job("fakejob")["state"] == "cancelled"
        res = await client.post("/api/v1/audit/redo", json={"id": aid})
        assert res.status_code == 422
    finally:
        with r_service._jobs_lock:
            r_service._JOBS.pop("fakejob", None)


async def test_undo_unsupported_actions_still_explain(client, open_project):
    _insert_audit(open_project, "project.compact", "project", None, {})
    _insert_audit(open_project, "interchange.import", "project", None, {})
    _insert_audit(
        open_project,
        "coding.autocode",
        "code_text",
        None,
        {"batch": 2, "job_ids": ["j1"], "cids": [1]},
    )
    for action, needle in (
        ("project.compact", "Compaction"),
        ("interchange.import", "delete the affected rows manually"),
        ("coding.autocode", "background autocode jobs"),
    ):
        aid = await _find_audit_id(client, action)
        res = await client.post("/api/v1/audit/undo", json={"id": aid})
        assert res.status_code == 422, (action, res.text)
        assert needle in res.json()["detail"], (action, res.text)
