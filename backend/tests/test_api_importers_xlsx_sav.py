"""API tests for the XLSX and SPSS .sav interchange importers."""

from __future__ import annotations

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.importers import router as importers_router
from qualcoder_api.main import app

app.include_router(importers_router, prefix="/api/v1")

pandas = pytest.importorskip("pandas")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "spreadsheet.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, tmp_path
        await c.post("/api/v1/projects/close")


def project_db(tmp_path) -> str:
    """Path of the open project's SQLite database file."""
    return str(tmp_path / "spreadsheet.qda" / "data.qda")


# ----------------------------------------------------------------------
# Fixture builders
# ----------------------------------------------------------------------

def build_xlsx(path) -> None:
    """Workbook with a survey sheet (header + rows) and a text sheet."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "survey"
    ws.append(["Name", "Age", "Comment"])
    ws.append(["Alice", 34, "hello world"])
    ws.append(["Bob", 41, "second row"])
    notes = wb.create_sheet("notes")
    notes.append(["Some transcript text"])
    notes.append(["More lines here"])
    wb.save(path)


def build_sav(path) -> None:
    """Tiny SPSS .sav file with numeric, text and qualitative variables."""
    df = pandas.DataFrame(
        {
            "id": [1.0, 2.0, 3.0],
            "age": [34, 41, None],
            "city": ["Paris", "Rome", "Berlin"],
            "comment": ["hello world", "second row", ""],
        }
    )
    import pyreadstat

    pyreadstat.write_sav(df, path)


# ----------------------------------------------------------------------
# XLSX
# ----------------------------------------------------------------------

async def test_import_xlsx(project_client):
    client, tmp_path = project_client
    xlsx_path = tmp_path / "surveywb.xlsx"
    build_xlsx(xlsx_path)
    res = await client.post(
        "/api/v1/interchange/import/xlsx",
        files={"file": ("surveywb.xlsx", xlsx_path.read_bytes(), "application/octet-stream")},
        data={"codername": "tester", "qualitative_headers": "Comment"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["cases"] == 2
    assert body["attributes"] == 2
    assert body["qualitative_files"] == 2
    assert body["qualitative_codings"] == 2
    assert body["sources"] == 1

    cases = (await client.get("/api/v1/cases")).json()
    assert sorted(c["name"] for c in cases) == ["Alice", "Bob"]

    types = (await client.get("/api/v1/attributes/types")).json()
    assert {"Age"} <= {t["name"] for t in types}

    values = (await client.get("/api/v1/attributes/values")).json()
    case_attrs = {(v["name"], v["value"]) for v in values if v["attr_type"] == "case"}
    assert ("Age", "34") in case_attrs
    assert ("Age", "41") in case_attrs

    sources = (await client.get("/api/v1/sources")).json()
    names = {s["name"] for s in sources}
    assert "surveywb-notes.txt" in names
    assert "Alice_Comment" in names
    assert "Bob_Comment" in names

    detail = {
        s["name"]: s
        for s in (await client.get("/api/v1/sources")).json()
    }
    notes_id = next(
        s["id"] for s in (await client.get("/api/v1/sources")).json()
        if s["name"] == "surveywb-notes.txt"
    )
    notes = (await client.get(f"/api/v1/sources/{notes_id}")).json()
    assert notes["fulltext"] == "Some transcript text\nMore lines here"

    alice_id = detail["Alice_Comment"]["id"]
    codings = (await client.get(f"/api/v1/codings/text/{alice_id}")).json()
    assert len(codings) == 1
    assert codings[0]["seltext"] == "hello world"

    async with aiosqlite.connect(project_db(tmp_path)) as db:
        cur = await db.execute("SELECT color FROM code_name WHERE name = 'Comment'")
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "#B8B8B8"


async def test_import_xlsx_auto_detected(project_client):
    client, tmp_path = project_client
    xlsx_path = tmp_path / "surveywb.xlsx"
    build_xlsx(xlsx_path)
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("surveywb.xlsx", xlsx_path.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cases"] == 2
    assert body["sources"] == 1


async def test_import_xlsx_garbage_rejected(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/xlsx",
        files={"file": ("bad.xlsx", b"this is not a spreadsheet", "application/octet-stream")},
    )
    assert res.status_code == 422


# ----------------------------------------------------------------------
# SPSS .sav
# ----------------------------------------------------------------------

async def test_import_sav(project_client):
    client, tmp_path = project_client
    sav_path = tmp_path / "sample.sav"
    build_sav(sav_path)
    res = await client.post(
        "/api/v1/interchange/import/sav",
        files={"file": ("sample.sav", sav_path.read_bytes(), "application/octet-stream")},
        data={"codername": "tester", "qualitative_headers": "comment"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["cases"] == 3
    assert body["attributes"] == 6
    assert body["qualitative_files"] == 2
    assert body["qualitative_codings"] == 2

    cases = (await client.get("/api/v1/cases")).json()
    assert sorted(c["name"] for c in cases) == ["1", "2", "3"]

    types = (await client.get("/api/v1/attributes/types")).json()
    assert {"age", "city"} <= {t["name"] for t in types}

    async with aiosqlite.connect(project_db(tmp_path)) as db:
        cur = await db.execute(
            "SELECT valuetype FROM attribute_type WHERE name IN ('age', 'city')"
        )
        stored_types = {row[0] for row in await cur.fetchall()}
    assert stored_types == {"number", "text"}

    values = (await client.get("/api/v1/attributes/values")).json()
    case_attrs = {(v["name"], v["value"]) for v in values if v["attr_type"] == "case"}
    assert ("age", "34") in case_attrs
    assert ("age", "41") in case_attrs
    assert ("city", "Paris") in case_attrs

    sources = (await client.get("/api/v1/sources")).json()
    names = {s["name"] for s in sources}
    assert "1_comment" in names
    assert "2_comment" in names
    assert "3_comment" not in names

    by_name_src = {s["name"]: s for s in sources}
    codings = (
        await client.get(f"/api/v1/codings/text/{by_name_src['1_comment']['id']}")
    ).json()
    assert len(codings) == 1
    assert codings[0]["seltext"] == "hello world"
    assert codings[0]["pos0"] == 0
    assert codings[0]["pos1"] == len("hello world") - 1


async def test_import_sav_auto_detected(project_client):
    client, tmp_path = project_client
    sav_path = tmp_path / "sample.sav"
    build_sav(sav_path)
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("sample.sav", sav_path.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cases"] == 3
    assert body["attributes"] == 9

    assert (
        await client.post(
            "/api/v1/interchange/import/auto",
            files={"file": ("sample.whatever", sav_path.read_bytes(), "application/octet-stream")},
        )
    ).status_code == 200


async def test_import_sav_empty_case_name_fallback(project_client):
    client, tmp_path = project_client
    sav_path = tmp_path / "sample.sav"
    df = pandas.DataFrame({"respondent": [None, None], "score": [1, 2]})
    import pyreadstat

    pyreadstat.write_sav(df, sav_path)
    res = await client.post(
        "/api/v1/interchange/import/sav",
        files={"file": ("sample.sav", sav_path.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cases"] == 2
    cases = (await client.get("/api/v1/cases")).json()
    assert sorted(c["name"] for c in cases) == ["Case 1", "Case 2"]


async def test_import_sav_garbage_rejected(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/sav",
        files={"file": ("bad.sav", b"definitely not spss data", "application/octet-stream")},
    )
    assert res.status_code == 422
