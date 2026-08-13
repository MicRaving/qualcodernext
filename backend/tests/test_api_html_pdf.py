"""API tests for GET /sources/{id}/pdf — HTML -> PDF export."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app

#: A realistic captured webpage: inline CSS (exercises the Story user_css
#: path) plus unicode text (exercises MuPDF's fallback fonts).
PAGE_HTML = """<!doctype html>
<html><head><title>Snapshot</title>
<style>body { font-family: sans-serif; color: #222; } h1 { color: #900; }</style>
</head><body>
<h1>Captured page</h1>
<p>Hello from the <b>snapshot</b> — gr\u00fcsse \u041f\u0440\u0438\u0432\u0435\u0442 \u4e16\u754c.</p>
</body></html>
"""


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "pdf.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def import_html(client: AsyncClient, name: str = "snapshot.html") -> int:
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": (name, PAGE_HTML.encode("utf-8"), "text/html")},
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def parse_pdf(data: bytes):
    import fitz

    return fitz.open(stream=data, filetype="pdf")


# ----------------------------------------------------------------------
# GET /sources/{id}/pdf
# ----------------------------------------------------------------------

async def test_html_source_exported_as_pdf(project_client):
    """The captured .html file renders through the Story path into a
    parseable PDF with the page content and its unicode intact."""
    client, _ = project_client
    sid = await import_html(client)

    got = await client.get(f"/api/v1/sources/{sid}/pdf")
    assert got.status_code == 200, got.text
    assert got.headers["content-type"] == "application/pdf"
    assert "snapshot.pdf" in got.headers.get("content-disposition", "")
    assert got.content.startswith(b"%PDF")

    with parse_pdf(got.content) as doc:
        assert doc.page_count >= 1
        text = "".join(page.get_text() for page in doc)
        assert "Captured page" in text
        assert "gr\u00fcsse" in text
        assert "\u041f\u0440\u0438\u0432\u0435\u0442" in text


async def test_text_fallback_when_html_render_fails(project_client, monkeypatch):
    """When the Story layout render fails, the extracted fulltext is turned
    into a text-only PDF — the export still succeeds and stays parseable."""
    import qualcoder_api.api.v1.sources as sources_mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("css boom")

    monkeypatch.setattr(sources_mod, "_story_pdf", boom)
    client, _ = project_client
    sid = await import_html(client)

    got = await client.get(f"/api/v1/sources/{sid}/pdf")
    assert got.status_code == 200, got.text
    assert got.content.startswith(b"%PDF")

    with parse_pdf(got.content) as doc:
        assert doc.page_count >= 1
        text = "".join(page.get_text() for page in doc)
        # The fallback renders the extracted plain text (import-time
        # html_to_text of PAGE_HTML), unicode included.
        assert "Captured page" in text
        assert "gr\u00fcsse" in text


async def test_pdf_422_for_non_html_source(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("notes.txt", b"plain", "text/plain")}
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    assert (await client.get(f"/api/v1/sources/{sid}/pdf")).status_code == 422


async def test_pdf_404_when_no_file_on_disk(project_client, tmp_path):
    """An html-named source with no file on disk (broken external link)
    returns 404 — mirroring the file-serving endpoint."""
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/link", json={"path": str(tmp_path / "missing.html")}
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    assert (await client.get(f"/api/v1/sources/{sid}/pdf")).status_code == 404


async def test_pdf_404_for_unknown_source(project_client):
    client, _ = project_client
    assert (await client.get("/api/v1/sources/99999/pdf")).status_code == 404
