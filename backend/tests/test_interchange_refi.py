"""API tests for the REFI-QDA interchange (.qdp) export and import."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.interchange import router as interchange_router
from qualcoder_api.main import app

app.include_router(interchange_router, prefix="/api/v1")

DOC_TEXT = "alpha beta gamma delta"


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "refi.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def seed_dataset(client) -> dict:
    """Top + Sub categories, a code in each, one text file, two codings, one case."""
    top = (
        await client.post("/api/v1/codes/categories", json={"name": "Top"})
    ).json()
    assert top["catid"] > 0
    sub = (
        await client.post(
            "/api/v1/codes/categories",
            json={"name": "Sub", "supercatid": top["catid"]},
        )
    ).json()
    code_sub = (
        await client.post(
            "/api/v1/codes",
            json={"name": "SubCode", "catid": sub["catid"], "color": "#FF0000"},
        )
    ).json()
    code_top = (
        await client.post(
            "/api/v1/codes", json={"name": "TopCode", "color": "#00FF00"}
        )
    ).json()

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("doc.txt", DOC_TEXT, "text/plain")},
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]

    for pos0, pos1, sel in ((0, 5, "alpha"), (6, 10, "beta")):
        coded = await client.post(
            "/api/v1/codings/text",
            json={"cid": code_top["cid"], "fid": fid, "seltext": sel, "pos0": pos0, "pos1": pos1},
        )
        assert coded.status_code == 201, coded.text

    case = (await client.post("/api/v1/cases", json={"name": "CaseOne"})).json()
    assert case["caseid"] > 0
    return {"fid": fid, "cids": {"sub": code_sub["cid"], "top": code_top["cid"]}}


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------

async def test_export_refi_qdp(project_client):
    client, _ = project_client
    await seed_dataset(client)

    res = await client.get("/api/v1/interchange/export/refi")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/xml")

    body = res.text
    assert "<QDAProject" in body
    assert "CodeBook" in body
    assert "SubCode" in body
    assert "TopCode" in body
    assert "Sub" in body
    assert "Top" in body
    assert "CaseOne" in body
    assert "CodedText" in body
    assert DOC_TEXT in body


# ----------------------------------------------------------------------
# Round-trip
# ----------------------------------------------------------------------

async def test_round_trip_import_into_second_project(project_client, tmp_path):
    client, _ = project_client
    await seed_dataset(client)

    exported = (await client.get("/api/v1/interchange/export/refi")).text

    second = await client.post(
        "/api/v1/projects", json={"project_path": str(tmp_path / "second.qda")}
    )
    assert second.status_code == 200, second.text

    res = await client.post(
        "/api/v1/interchange/import/refi",
        files={"file": ("export.qdp", exported.encode("utf-8"), "application/xml")},
        data={"codername": "importer"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["codes"] >= 2
    assert body["categories"] >= 2
    assert body["sources"] >= 1
    assert body["codings"] == 2
    assert body["cases"] == 1

    freq = (await client.get("/api/v1/reports/code-frequencies")).json()["rows"]
    by_name = {r["name"]: r for r in freq}
    assert by_name["TopCode"]["count"] == 2

    sources = (await client.get("/api/v1/sources")).json()
    assert len(sources) == 1
    assert sources[0]["name"] == "doc.txt"
    # The list endpoint omits fulltext; the detail endpoint carries it.
    assert sources[0]["fulltext"] is None
    detail = (await client.get(f"/api/v1/sources/{sources[0]['id']}")).json()
    assert detail["fulltext"] == DOC_TEXT


# ----------------------------------------------------------------------
# Error handling & robustness
# ----------------------------------------------------------------------

async def test_import_invalid_xml_rejected(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/refi",
        files={"file": ("bad.qdp", b"this is not xml at all", "application/xml")},
    )
    assert res.status_code == 422


async def test_codedtext_with_unknown_guid_skipped(project_client):
    client, _ = project_client
    xml = """<QDAProject xmlns="urn:QDA-XML:project:1.0">
  <CodeBook>
    <Codes>
      <Code guid="code-1" name="KnownCode" color="#FF0000"/>
    </Codes>
  </CodeBook>
  <Sources>
    <TextSource guid="src-1" name="known.txt" mediaType="TEXT">
      <Description><FullText>hello world</FullText></Description>
    </TextSource>
  </Sources>
  <CodedTexts>
    <CodedText guid="ct-1">
      <Description>
        <CodedSelection>
          <SourceRef targetGUID="missing-source"/>
          <TextRef start="0" end="5"/>
        </CodedSelection>
        <CodeRef targetGUID="code-1"/>
      </Description>
    </CodedText>
  </CodedTexts>
</QDAProject>"""
    res = await client.post(
        "/api/v1/interchange/import/refi",
        files={"file": ("refi.qdp", xml.encode("utf-8"), "application/xml")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["codes"] == 1
    assert body["sources"] == 1
    assert body["codings"] == 0

    sources = (await client.get("/api/v1/sources")).json()
    assert len(sources) == 1
    fid = sources[0]["id"]
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert codings == []
