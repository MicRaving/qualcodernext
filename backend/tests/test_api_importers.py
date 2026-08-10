"""API tests for the interchange importers (RQDA, Taguette, RIS, Survey)."""

from __future__ import annotations

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
        target = tmp_path / "importers.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, tmp_path
        await c.post("/api/v1/projects/close")


def project_db(tmp_path) -> str:
    """Path of the open project's SQLite database file."""
    return str(tmp_path / "importers.qda" / "data.qda")


# ----------------------------------------------------------------------
# Fixture builders
# ----------------------------------------------------------------------

async def build_rqda_db(path) -> None:
    """Minimal RQDA-style database with the columns the importer reads."""
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE codecat (id INTEGER PRIMARY KEY, catname TEXT, parent INTEGER);
            CREATE TABLE freecode (id INTEGER PRIMARY KEY, name TEXT, color TEXT, category INTEGER);
            CREATE TABLE file (id INTEGER PRIMARY KEY, name TEXT, fulltext TEXT);
            CREATE TABLE coding (cid INTEGER, fid INTEGER, pos0 INTEGER, pos1 INTEGER,
                                 seltext TEXT, file TEXT);
            CREATE TABLE casename (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE caselinkage (caseid INTEGER, fid INTEGER);
            """
        )
        await db.execute("INSERT INTO codecat (id, catname, parent) VALUES (1, 'Theme', NULL)")
        await db.execute(
            "INSERT INTO freecode (id, name, color, category) VALUES (1, 'Positive', '#FF0000', 1)"
        )
        await db.execute(
            "INSERT INTO file (id, name, fulltext) VALUES (1, 'rq.txt', 'Hello rqda world')"
        )
        await db.execute(
            "INSERT INTO coding (cid, fid, pos0, pos1, seltext, file) "
            "VALUES (1, 1, 0, 5, 'Hello', 'Hello rqda world')"
        )
        await db.execute("INSERT INTO casename (id, name) VALUES (1, 'CaseOne')")
        await db.execute("INSERT INTO caselinkage (caseid, fid) VALUES (1, 1)")
        await db.commit()


async def build_taguette_db(path) -> None:
    """Minimal Taguette-style database with the columns the importer reads."""
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, contents TEXT);
            CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT, color TEXT);
            CREATE TABLE highlights (id INTEGER PRIMARY KEY, document INTEGER, tag INTEGER,
                                     start INTEGER, end INTEGER, text TEXT);
            """
        )
        await db.execute(
            "INSERT INTO documents (id, title, contents) "
            "VALUES (1, 'doc1', '<p>Hello <b>world</b></p>')"
        )
        await db.execute("INSERT INTO tags (id, name, color) VALUES (1, 'Pos', '#00FF00')")
        await db.execute(
            "INSERT INTO highlights (id, document, tag, start, end, text) "
            "VALUES (1, 1, 1, 6, 11, '<b>world</b>')"
        )
        await db.commit()


# ----------------------------------------------------------------------
# RQDA
# ----------------------------------------------------------------------

async def test_import_rqda(project_client):
    client, tmp_path = project_client
    rqda_path = tmp_path / "sample.rqda"
    await build_rqda_db(rqda_path)
    res = await client.post(
        "/api/v1/interchange/import/rqda",
        files={"file": ("sample.rqda", rqda_path.read_bytes(), "application/octet-stream")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["categories"] == 1
    assert body["codes"] == 1
    assert body["sources"] == 1
    assert body["codings"] == 1
    assert body["cases"] == 1

    sources = (await client.get("/api/v1/sources")).json()
    assert len(sources) == 1
    assert sources[0]["name"] == "rq.txt"
    assert sources[0]["fulltext"] is None  # the list omits fulltext
    fid = sources[0]["id"]
    detail = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert detail["fulltext"] == "Hello rqda world"

    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert len(codings) == 1
    assert codings[0]["seltext"] == "Hello"
    assert codings[0]["pos0"] == 0
    assert codings[0]["pos1"] == 5

    async with aiosqlite.connect(project_db(tmp_path)) as db:
        cur = await db.execute("SELECT color FROM code_name WHERE name = 'Positive'")
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "#FF0000"


async def test_import_rqda_twice_is_idempotent(project_client):
    """Re-importing the same RQDA file adds nothing (names are deduplicated)."""
    client, tmp_path = project_client
    rqda_path = tmp_path / "sample.rqda"
    await build_rqda_db(rqda_path)
    payload = {
        "file": ("sample.rqda", rqda_path.read_bytes(), "application/octet-stream"),
    }
    first = await client.post("/api/v1/interchange/import/rqda", files=payload)
    assert first.status_code == 200, first.text
    second = await client.post("/api/v1/interchange/import/rqda", files=payload)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["sources"] == 0
    assert body["categories"] == 0
    assert body["codes"] == 0
    assert body["codings"] == 0
    assert body["cases"] == 0


# ----------------------------------------------------------------------
# Taguette
# ----------------------------------------------------------------------

async def test_import_taguette(project_client):
    client, tmp_path = project_client
    tg_path = tmp_path / "sample.taguette.sqlite3"
    await build_taguette_db(tg_path)
    res = await client.post(
        "/api/v1/interchange/import/taguette",
        files={
            "file": ("sample.taguette.sqlite3", tg_path.read_bytes(), "application/octet-stream")
        },
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["sources"] == 1
    assert body["codes"] == 1
    assert body["codings"] == 1

    sources = (await client.get("/api/v1/sources")).json()
    assert len(sources) == 1
    assert sources[0]["fulltext"] is None
    fid = sources[0]["id"]
    detail = (await client.get(f"/api/v1/sources/{fid}")).json()
    assert detail["fulltext"] == "Hello world"

    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert len(codings) == 1
    assert codings[0]["seltext"] == "world"
    assert codings[0]["pos0"] == 6
    assert codings[0]["pos1"] == 11


# ----------------------------------------------------------------------
# RIS
# ----------------------------------------------------------------------

async def test_import_ris(project_client):
    client, tmp_path = project_client
    ris_path = tmp_path / "refs.ris"
    ris_path.write_text("TY  - JOUR\nTI  - Title\nAU  - Author\nPY  - 2020\nER  -\n", encoding="utf-8")
    res = await client.post(
        "/api/v1/interchange/import/ris",
        files={"file": ("refs.ris", ris_path.read_bytes(), "text/plain")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["references"] == 4
    assert body["entries"] == 1

    async with aiosqlite.connect(project_db(tmp_path)) as db:
        cur = await db.execute("SELECT tag, longtag, value FROM ris ORDER BY risid")
        rows = await cur.fetchall()
    assert len(rows) == 4
    by_longtag = {r[1]: r[2] for r in rows}
    assert by_longtag["type_of_reference"] == "JOUR"
    assert by_longtag["title"] == "Title"
    assert by_longtag["authors"] == "Author"
    assert by_longtag.get("publication_year", by_longtag.get("year")) == "2020"


# ----------------------------------------------------------------------
# Survey
# ----------------------------------------------------------------------

async def test_import_survey(project_client):
    client, tmp_path = project_client
    csv_path = tmp_path / "survey.csv"
    csv_path.write_text(
        "Name,Age,City\r\nAlice,34,Paris\r\nBob,41,Rome\r\n", encoding="utf-8-sig"
    )
    res = await client.post(
        "/api/v1/interchange/import/survey",
        files={"file": ("survey.csv", csv_path.read_bytes(), "text/csv")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["cases"] == 2
    assert body["attributes"] == 4

    cases = (await client.get("/api/v1/cases")).json()
    assert len(cases) == 2
    assert sorted(c["name"] for c in cases) == ["Alice", "Bob"]

    types = (await client.get("/api/v1/attributes/types")).json()
    assert {"Age", "City"} <= {t["name"] for t in types}

    values = (await client.get("/api/v1/attributes/values")).json()
    case_attrs = {(v["name"], v["value"]) for v in values if v["attr_type"] == "case"}
    assert ("Age", "34") in case_attrs
    assert ("City", "Rome") in case_attrs


async def test_import_survey_semicolon_delimiter(project_client):
    client, tmp_path = project_client
    csv_path = tmp_path / "survey.csv"
    csv_path.write_text("Name;Age;City\nAlice;34;Paris\n", encoding="utf-8")
    res = await client.post(
        "/api/v1/interchange/import/survey",
        files={"file": ("survey.csv", csv_path.read_bytes(), "text/csv")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["cases"] == 1

    types = (await client.get("/api/v1/attributes/types")).json()
    assert {"Age", "City"} <= {t["name"] for t in types}


# ----------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------

async def test_import_rqda_garbage_rejected(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/rqda",
        files={"file": ("bad.rqda", b"this is not a sqlite database at all", "application/octet-stream")},
    )
    assert res.status_code == 422


async def test_import_taguette_garbage_rejected(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/taguette",
        files={
            "file": ("bad.taguette.sqlite3", b"also not a sqlite database", "application/octet-stream")
        },
    )
    assert res.status_code == 422


async def test_import_requires_open_project(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post(
            "/api/v1/interchange/import/rqda",
            files={"file": ("x.rqda", b"whatever", "application/octet-stream")},
        )
        assert res.status_code == 409
