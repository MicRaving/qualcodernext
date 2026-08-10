"""API file-serving tests — source bytes and image/PDF thumbnails."""

from __future__ import annotations

import io
import wave

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "files.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


def make_png(size=(100, 60), color="red") -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_pdf() -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), "QualCoder test page")
    data = doc.tobytes()
    doc.close()
    return data


def make_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


# ----------------------------------------------------------------------
# GET /sources/{id}/file
# ----------------------------------------------------------------------

async def test_file_served_for_internal_png(project_client):
    client, _ = project_client
    png = make_png()
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("pic.png", png, "image/png")}
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    got = await client.get(f"/api/v1/sources/{sid}/file")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.content == png


async def test_file_served_for_external_link(project_client, tmp_path):
    client, _ = project_client
    external = tmp_path / "external.txt"
    payload = b"external file contents"
    external.write_bytes(payload)

    res = await client.post("/api/v1/sources/link", json={"path": str(external)})
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    got = await client.get(f"/api/v1/sources/{sid}/file")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("text/plain")
    assert got.content == payload


async def test_file_404_for_media_without_disk_file(project_client, tmp_path):
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/link", json={"path": str(tmp_path / "missing.txt")}
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    assert (await client.get(f"/api/v1/sources/{sid}/file")).status_code == 404


async def test_file_404_for_unknown_source(project_client):
    client, _ = project_client
    assert (await client.get("/api/v1/sources/99999/file")).status_code == 404


async def test_delete_source_clears_transcript_pointer(project_client):
    """Deleting a transcript source must clear the media source's av_text_id
    so re-transcription links a fresh transcript (no stale fold target)."""
    import sqlite3

    client, target = project_client
    media = await client.post(
        "/api/v1/sources/import", files={"file": ("clip.mp4", b"\x00" * 64, "video/mp4")}
    )
    assert media.status_code == 200, media.text
    media_id = media.json()["id"]
    tx = await client.post(
        "/api/v1/sources/import", files={"file": ("clip.txt", "hello transcript", "text/plain")}
    )
    assert tx.status_code == 200, tx.text
    tx_id = tx.json()["id"]

    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute("UPDATE source SET av_text_id = ? WHERE id = ?", (tx_id, media_id))
        conn.commit()

    assert (await client.delete(f"/api/v1/sources/{tx_id}")).status_code == 204

    with sqlite3.connect(str(target / "data.qda")) as conn:
        row = conn.execute("SELECT av_text_id FROM source WHERE id = ?", (media_id,)).fetchone()
    assert row[0] is None


async def test_traversal_rejected(project_client):
    client, target = project_client
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("safe.png", make_png(), "image/png")}
    )
    sid = res.json()["id"]
    (target.parent / "settings.json").write_text("TOP SECRET")

    conn = await aiosqlite.connect(target / "data.qda")
    try:
        await conn.execute(
            "UPDATE source SET mediapath = ? WHERE id = ?",
            ("/docs/../../settings.json", sid),
        )
        await conn.commit()
    finally:
        await conn.close()

    got = await client.get(f"/api/v1/sources/{sid}/file")
    assert got.status_code == 404


# ----------------------------------------------------------------------
# GET /sources/{id}/thumbnail
# ----------------------------------------------------------------------

async def test_image_thumbnail(project_client):
    client, _ = project_client
    from PIL import Image

    res = await client.post(
        "/api/v1/sources/import", files={"file": ("pic.png", make_png(), "image/png")}
    )
    sid = res.json()["id"]

    got = await client.get(f"/api/v1/sources/{sid}/thumbnail")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(got.content))
    assert img.size == (100, 60)

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("big.png", make_png(size=(1200, 800), color="blue"), "image/png")},
    )
    big_id = res.json()["id"]
    small = await client.get(f"/api/v1/sources/{big_id}/thumbnail?max_size=100")
    assert small.status_code == 200
    thumb = Image.open(io.BytesIO(small.content))
    assert max(thumb.size) <= 100


async def test_pdf_thumbnail(project_client):
    client, _ = project_client
    from PIL import Image

    pdf = make_pdf()
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("paper.pdf", pdf, "application/pdf")}
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    thumb = await client.get(f"/api/v1/sources/{sid}/thumbnail")
    assert thumb.status_code == 200, thumb.text
    assert thumb.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(thumb.content))
    assert max(img.size) <= 300

    got = await client.get(f"/api/v1/sources/{sid}/file")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/pdf"
    assert got.content == pdf


async def test_thumbnail_404_for_audio(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("tone.wav", make_wav(), "audio/wav")}
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    assert (await client.get(f"/api/v1/sources/{sid}/thumbnail")).status_code == 404
