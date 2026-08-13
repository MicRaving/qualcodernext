"""API tests for the NVivo (.nvpx) interchange importer."""

from __future__ import annotations

import io
import zipfile

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.importers import router as importers_router
from qualcoder_api.main import app

app.include_router(importers_router, prefix="/api/v1")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "nvivo.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, tmp_path
        await c.post("/api/v1/projects/close")


def project_db(tmp_path) -> str:
    """Path of the open project's SQLite database file."""
    return str(tmp_path / "nvivo.qda" / "data.qda")


# ----------------------------------------------------------------------
# Synthetic .nvpx builders
# ----------------------------------------------------------------------

PROJECT_HEAD = """\
<?xml version="1.0" encoding="UTF-8"?>
<NvivoProject appVersion="12.0.0.123" projectVersion="12.0.0.123">
  <Project guid="proj-1"><Name>Sample</Name></Project>
  <Content>
    <Sources>
      <Documents>
        <Document guid="src-1" name="doc1">
          <Content>Hello <b>nvivo</b> world</Content>
          <Description>first memo</Description>
        </Document>
        <Document guid="src-2" name="doc2" type="audio"/>
      </Documents>
    </Sources>
    <Nodes>
      <Node guid="nd-1" name="Theme">
        <Description>a theme</Description>
        <Node guid="nd-2" name="Positive"/>
        <Node guid="nd-3" name="Negative"/>
      </Node>
      <Node guid="nd-4" name="Loose"/>
    </Nodes>
    <Coding>
      <Coding guid="cd-1" source="src-1" node="nd-2">
        <Position>
          <Start>0</Start>
          <End>5</End>
        </Position>
      </Coding>
      <Coding guid="cd-2" source="src-1" node="nd-4">
        <Position>
          <Start>6</Start>
          <End>11</End>
        </Position>
      </Coding>
      <Coding guid="cd-3" source="src-1" node="nd-1">
        <Position>
          <Begin>5</Begin>
          <End>6</End>
        </Position>
      </Coding>
    </Coding>
  </Content>
</NvivoProject>
"""


def build_nvpx() -> bytes:
    """A single-file .nvpx ZIP: NvivoProject.xml with documents, nodes, codings."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("NvivoProject.xml", PROJECT_HEAD)
    return buffer.getvalue()


def build_nvpx_split() -> bytes:
    """A split-bundle .nvpx ZIP: __nvivo/ with one XML file per section."""
    sources_xml = (
        "<Sources><Documents>"
        '<Document guid="src-1" name="split1">'
        "<Content>Split bundle <b>text</b></Content>"
        "</Document></Documents></Sources>"
    )
    nodes_xml = (
        "<Nodes><Node guid='nd-1' name='Theme'>"
        "<Node guid='nd-2' name='Positive'/></Node></Nodes>"
    )
    coding_xml = (
        "<Coding><Coding guid='cd-1' source='src-1' node='nd-2'>"
        "<Position><Start>6</Start><End>10</End></Position>"
        "</Coding></Coding>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("__nvivo/Sources.xml", sources_xml)
        archive.writestr("__nvivo/Nodes.xml", nodes_xml)
        archive.writestr("__nvivo/Coding.xml", coding_xml)
    return buffer.getvalue()


def build_plain_zip() -> bytes:
    """A zip archive that is not an NVivo project (no marker)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")
    return buffer.getvalue()


# ----------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------

async def test_import_nvivo(project_client):
    client, tmp_path = project_client
    res = await client.post(
        "/api/v1/interchange/import/nvivo",
        files={"file": ("sample.nvpx", build_nvpx(), "application/octet-stream")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["sources"] == 1  # doc2 is audio — no text, skipped
    assert body["categories"] == 1  # the "Theme" node folder
    assert body["codes"] == 4  # Positive + Negative + Loose + Theme (folder is coded too)
    assert body["codings"] == 3  # cd-1, cd-2 and the folder-coded cd-3
    assert body["skipped_codings"] == 0

    sources = (await client.get("/api/v1/sources")).json()
    assert len(sources) == 1
    fid = sources[0]["id"]
    detail = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert detail["fulltext"] == "Hello nvivo world"

    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert len(codings) == 3
    by_pos = {(c["pos0"], c["pos1"]): c["seltext"] for c in codings}
    assert by_pos[(0, 5)] == "Hello"
    assert by_pos[(6, 11)] == "nvivo"
    assert by_pos[(5, 6)] == " "

    async with aiosqlite.connect(project_db(tmp_path)) as db:
        cur = await db.execute("SELECT name FROM code_cat ORDER BY name")
        cats = [row[0] for row in await cur.fetchall()]
        cur = await db.execute("SELECT name, catid FROM code_name ORDER BY name")
        codes = {row[0]: row[1] for row in await cur.fetchall()}
    assert cats == ["Theme"]
    assert set(codes) == {"Positive", "Negative", "Loose", "Theme"}
    assert codes["Positive"] is not None  # under the Theme category
    assert codes["Theme"] is None  # folder-as-code, top level
    assert codes["Loose"] is None


async def test_import_nvivo_split_bundle(project_client):
    """The __nvivo split layout is detected and imported across its files."""
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/nvivo",
        files={"file": ("split.nvpx", build_nvpx_split(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sources"] == 1
    assert body["categories"] == 1
    assert body["codes"] == 1
    assert body["codings"] == 1


async def test_import_nvivo_coding_positions_unparseable(project_client):
    """Codings without parseable positions are skipped, never fatal."""
    client, _ = project_client
    xml = PROJECT_HEAD.replace(
        "<Position>\n          <Start>0</Start>\n          <End>5</End>\n        </Position>",
        "",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("NvivoProject.xml", xml)
    res = await client.post(
        "/api/v1/interchange/import/nvivo",
        files={"file": ("badpos.nvpx", buffer.getvalue(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["sources"] == 1
    assert body["categories"] == 1
    assert body["codes"] == 4
    assert body["codings"] == 2
    assert body["skipped_codings"] == 1


async def test_import_nvivo_garbage_rejected(project_client):
    client, _ = project_client
    payload = {
        "file": ("bad.nvpx", b"this is not a zip archive at all", "application/octet-stream")
    }
    res = await client.post("/api/v1/interchange/import/nvivo", files=payload)
    assert res.status_code == 422

    plain_zip = build_plain_zip()
    payload = {"file": ("plain.zip", plain_zip, "application/octet-stream")}
    res = await client.post("/api/v1/interchange/import/nvivo", files=payload)
    assert res.status_code == 422


# ----------------------------------------------------------------------
# Auto-detection
# ----------------------------------------------------------------------

async def test_import_auto_detects_nvivo(project_client):
    """The auto-detect endpoint routes an .nvpx ZIP to the NVivo importer."""
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("sample.nvpx", build_nvpx(), "application/octet-stream")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["sources"] == 1
    assert body["categories"] == 1
    assert body["codes"] == 4
    assert body["codings"] == 3


async def test_import_auto_detects_split_nvpx(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("split.nvpx", build_nvpx_split(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["sources"] == 1


async def test_import_auto_plain_zip_rejected(project_client):
    """A zip without the NVivo marker is not routed to NVivo."""
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("plain.zip", build_plain_zip(), "application/octet-stream")},
    )
    assert res.status_code == 422


async def test_import_nvivo_requires_open_project(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post(
            "/api/v1/interchange/import/nvivo",
            files={"file": ("x.nvpx", build_nvpx(), "application/octet-stream")},
        )
        assert res.status_code == 409
