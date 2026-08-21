"""API tests — coder management (create / switch / delete / owner resolution)."""

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
    """Create and open a project; close it afterwards."""
    target = tmp_path / "coders.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text
    yield target
    await client.post("/api/v1/projects/close")


async def test_list_coders_starts_with_default(client, monkeypatch, tmp_path):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    res = await client.get("/api/v1/coders")
    assert res.status_code == 200
    body = res.json()
    assert body["current"] == "default"
    assert [c["name"] for c in body["coders"]] == ["default"]


async def test_list_coders_merges_project_owners(client, open_project, monkeypatch, tmp_path):
    """The coder view must show coders that only exist in the project
    (e.g. imported projects with other raters' codings)."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")

    source = open_project / "documents" / "a.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")
    await client.post(
        "/api/v1/sources/import",
        files={"file": ("a.txt", "hello world", "text/plain")},
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    await client.post(
        "/api/v1/codes", json={"name": "T", "owner": None, "catid": None}
    )
    cid = (await client.get("/api/v1/codes")).json()[-1]["id"]
    await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )

    # Simulate another rater's rows in the imported project DB.
    import sqlite3

    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        conn.execute("UPDATE code_text SET owner = 'marvin'")
        conn.commit()

    res = await client.get("/api/v1/coders")
    assert res.status_code == 200
    names = [c["name"] for c in res.json()["coders"]]
    assert "marvin" in names

    # Switching to a project-only coder must work and persist the choice.
    res = await client.put("/api/v1/coders/current", json={"name": "marvin"})
    assert res.status_code == 200, res.text
    assert res.json()["current"] == "marvin"


async def test_coding_count_counts_segments_not_all_owner_rows(client, open_project, monkeypatch, tmp_path):
    """The coder flyout's "coded segments" number must reflect codings only —
    NOT every owned record (sources, codes, ... which would inflate it)."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")

    import os

    source = open_project / "documents" / "a.txt"
    os.makedirs(source.parent, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")
    await client.post(
        "/api/v1/sources/import",
        files={"file": ("a.txt", "hello world", "text/plain")},
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    await client.post("/api/v1/codes", json={"name": "T", "owner": None, "catid": None})
    cid = (await client.get("/api/v1/codes")).json()[-1]["id"]
    await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )

    # "default" owns a source + a code + a coding: the displayed count is the
    # number of coding SEGMENTS (1), not the owner-row total (3).
    res = await client.get("/api/v1/coders")
    by_name = {c["name"]: c["coding_count"] for c in res.json()["coders"]}
    assert by_name.get("default") == 1


async def test_rename_coder_updates_owners(client, open_project, monkeypatch, tmp_path):
    """Renaming a coder moves their rows, the visibility registry and the
    per-machine settings."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")

    res = await client.post("/api/v1/coders", json={"name": "tester"})
    assert res.status_code == 201, res.text
    res = await client.put("/api/v1/coders/current", json={"name": "tester"})
    assert res.status_code == 200, res.text

    source = open_project / "documents" / "a.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")
    await client.post(
        "/api/v1/sources/import",
        files={"file": ("a.txt", "hello world", "text/plain")},
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    await client.post("/api/v1/codes", json={"name": "T", "owner": None, "catid": None})
    cid = (await client.get("/api/v1/codes")).json()[-1]["id"]
    await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )

    res = await client.patch("/api/v1/coders/tester", json={"new_name": "tess"})
    assert res.status_code == 200, res.text
    assert "tess" in [c["name"] for c in res.json()["coders"]]

    import sqlite3

    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        owner = conn.execute("SELECT owner FROM code_text LIMIT 1").fetchone()[0]
    assert owner == "tess"
    assert user_settings.get_codername() == "tess"

    res = await client.patch("/api/v1/coders/tess", json={"new_name": "tester"})
    assert res.status_code == 409


async def test_coder_stats_endpoint(client, open_project, monkeypatch, tmp_path):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")

    res = await client.get("/api/v1/coders/default/stats")
    assert res.status_code == 200, res.text
    assert res.json()["coder"] == "default"
    assert isinstance(res.json()["total"], int)
    assert any(row["entity"] == "Text codings" for row in res.json()["tables"])


async def test_create_and_switch_coder(client, monkeypatch, tmp_path):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")

    res = await client.post("/api/v1/coders", json={"name": "alice"})
    assert res.status_code == 201, res.text
    assert "alice" in [c["name"] for c in res.json()["coders"]]

    res = await client.post("/api/v1/coders", json={"name": "alice"})
    assert res.status_code == 409

    res = await client.put("/api/v1/coders/current", json={"name": "alice"})
    assert res.status_code == 200
    assert res.json()["current"] == "alice"
    assert user_settings.get_codername() == "alice"


async def test_owner_follows_current_coder(
    client, open_project, monkeypatch, tmp_path
):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    res = await client.post("/api/v1/coders", json={"name": "alice"})
    assert res.status_code == 201, res.text
    res = await client.put("/api/v1/coders/current", json={"name": "alice"})
    assert res.status_code == 200, res.text

    # Create a code and a coding WITHOUT an explicit owner — the backend
    # must attribute them to the current coder "alice".
    res = await client.post(
        "/api/v1/codes",
        json={"name": "T", "owner": None, "catid": None},
    )
    assert res.status_code == 201, res.text
    cid = res.json()["cid"]
    source = open_project / "documents" / "a.txt"
    import os

    os.makedirs(source.parent, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")
    await client.post(
        "/api/v1/sources/import",
        files={"file": ("a.txt", "hello world", "text/plain")},
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    res = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    assert res.status_code == 201, res.text
    assert res.json()["owner"] == "alice"

    # The coder list reflects the record counts.
    res = await client.get("/api/v1/coders")
    alice = next(c for c in res.json()["coders"] if c["name"] == "alice")
    assert alice["coding_count"] >= 1


async def test_delete_coder_requires_reassign_or_empty(
    client, open_project, monkeypatch, tmp_path
):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    await client.post("/api/v1/coders", json={"name": "bob"})

    # Cannot delete the CURRENT coder.
    res = await client.delete("/api/v1/coders/default")
    assert res.status_code == 409

    # Empty coder deletes fine after switching away.
    res = await client.put("/api/v1/coders/current", json={"name": "bob"})
    assert res.status_code == 200
    res = await client.delete("/api/v1/coders/default")
    assert res.status_code == 200
    assert "default" not in [c["name"] for c in res.json()["coders"]]
