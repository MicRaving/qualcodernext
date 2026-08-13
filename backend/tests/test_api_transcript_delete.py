"""API tests — transcript companion lifecycle (create empty / delete).

POST /sources/{id}/transcript creates an EMPTY companion for an audio/video
source and links it via av_text_id (the manual-transcription target);
DELETE /sources/{id}/transcript removes the companion and clears the link.
"""

from __future__ import annotations

import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path, monkeypatch):
    """API client with a fresh open project and isolated user settings
    (the developer's real coder name must not leak into audit rows)."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "transcript.qda"
        res = await c.post(
            "/api/v1/projects",
            json={"project_path": str(target), "codername": "tester"},
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def _import_media(client, name: str = "talk.mp3") -> dict:
    mime = "audio/mpeg" if name.endswith(".mp3") else "video/mp4"
    res = await client.post(
        "/api/v1/sources/import", files={"file": (name, b"ID3fake", mime)}
    )
    assert res.status_code == 200, res.text
    return res.json()


def _drop_companion(target, media_id: int) -> None:
    """Remove the automatic import-time companion and its av_text_id link,
    simulating a project without a transcript."""
    with sqlite3.connect(str(target / "data.qda")) as conn:
        row = conn.execute(
            "SELECT av_text_id FROM source WHERE id = ?", (media_id,)
        ).fetchone()
        if row and row[0] is not None:
            conn.execute("DELETE FROM source WHERE id = ?", (row[0],))
        conn.execute("UPDATE source SET av_text_id = NULL WHERE id = ?", (media_id,))
        conn.commit()


async def test_create_empty_transcript(project_client):
    client, target = project_client
    media = await _import_media(client)
    media_id = media["id"]
    _drop_companion(target, media_id)

    res = await client.post(f"/api/v1/sources/{media_id}/transcript", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == media_id
    assert body["av_text_id"] is not None

    companion = (await client.get(f"/api/v1/sources/{body['av_text_id']}")).json()
    assert companion["name"] == "talk.mp3.txt"
    assert companion["fulltext"] == ""
    assert companion["media_type"] == "text"

    # The companion is hidden from the file list (a companion, not a file).
    names = [s["name"] for s in (await client.get("/api/v1/sources")).json()]
    assert "talk.mp3.txt" not in names
    listed = next(s for s in (await client.get("/api/v1/sources")).json() if s["id"] == media_id)
    assert listed["has_transcript"] is False

    # The creation is audit-recorded against the media source.
    res = await client.get("/api/v1/audit", params={"action": "transcript.create"})
    rows = res.json()["rows"]
    assert len(rows) >= 1
    row = next(r for r in rows if r["entity_id"] == body["av_text_id"])
    assert row["source_id"] == media_id
    assert row["detail"]["name"] == "talk.mp3.txt"


async def test_create_transcript_idempotent(project_client):
    client, target = project_client
    media = await _import_media(client)
    media_id = media["id"]
    _drop_companion(target, media_id)

    first = await client.post(f"/api/v1/sources/{media_id}/transcript", json={})
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/v1/sources/{media_id}/transcript", json={})
    assert second.status_code == 200, second.text
    assert second.json()["av_text_id"] == first.json()["av_text_id"]

    names = [s["name"] for s in (await client.get("/api/v1/sources")).json()]
    assert "talk.mp3.txt" not in names


async def test_create_transcript_uses_requested_name(project_client):
    client, target = project_client
    media = await _import_media(client)
    media_id = media["id"]
    _drop_companion(target, media_id)

    res = await client.post(
        f"/api/v1/sources/{media_id}/transcript", json={"name": "notes.txt"}
    )
    assert res.status_code == 200, res.text
    companion = (await client.get(f"/api/v1/sources/{res.json()['av_text_id']}")).json()
    assert companion["name"] == "notes.txt"


async def test_create_transcript_rejects_text_source(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("note.txt", "hello", "text/plain")},
    )
    fid = res.json()["id"]
    res = await client.post(f"/api/v1/sources/{fid}/transcript", json={})
    assert res.status_code == 422


async def test_create_transcript_unknown_source_404(project_client):
    client, _ = project_client
    res = await client.post("/api/v1/sources/999999/transcript", json={})
    assert res.status_code == 404


async def test_delete_transcript_clears_link_and_removes_companion(project_client):
    client, _ = project_client
    media = await _import_media(client)
    media_id = media["id"]
    trans_id = media["av_text_id"]

    # A real transcript: give the companion some text first.
    res = await client.post(
        "/api/v1/codings/commit-edit",
        json={"fid": trans_id, "new_text": "[00:01] hello world"},
    )
    assert res.status_code == 200, res.text

    res = await client.delete(f"/api/v1/sources/{media_id}/transcript")
    assert res.status_code == 204, res.text

    # av_text_id is cleared; the companion row is gone.
    after = (await client.get(f"/api/v1/sources/{media_id}")).json()
    assert after["av_text_id"] is None
    res = await client.get(f"/api/v1/sources/{trans_id}")
    assert res.status_code == 404

    # Audit records the deletion with the media source id.
    res = await client.get("/api/v1/audit", params={"action": "transcript.delete"})
    rows = res.json()["rows"]
    assert rows, "expected a transcript.delete audit row"
    assert rows[0]["entity_id"] == trans_id
    assert rows[0]["source_id"] == media_id

    # The media source stays in the list and is re-transcriptable.
    listed = [s for s in (await client.get("/api/v1/sources")).json() if s["id"] == media_id]
    assert len(listed) == 1
    assert listed[0]["has_transcript"] is False


async def test_delete_transcript_404_without_transcript(project_client):
    client, target = project_client
    media = await _import_media(client)
    media_id = media["id"]
    _drop_companion(target, media_id)

    res = await client.delete(f"/api/v1/sources/{media_id}/transcript")
    assert res.status_code == 404

    res = await client.delete("/api/v1/sources/999999/transcript")
    assert res.status_code == 404
