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


async def build_transana_db(path, media_path) -> None:
    """Minimal Transana-3-style database (media, transcripts, keywords).

    Positions are stored as media timecodes (ms) — the same storage Transana
    uses for real projects.
    """
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE MediaFiles (
                MediaID INTEGER PRIMARY KEY, MediaFileName TEXT, MediaFilePath TEXT
            );
            CREATE TABLE Episodes (
                EpisodeID INTEGER PRIMARY KEY, EpisodeName TEXT,
                EpisodeFileName TEXT, EpisodeFilePath TEXT
            );
            CREATE TABLE Transcripts (
                TranscriptID INTEGER PRIMARY KEY, TranscriptName TEXT,
                TranscriptText TEXT, TranscriptNotes TEXT, EpisodeID INTEGER
            );
            CREATE TABLE Keywords (
                KeywordID INTEGER PRIMARY KEY, KeywordName TEXT,
                KeywordTypeID INTEGER, KeywordNotes TEXT
            );
            CREATE TABLE KeywordTypes (KeywordTypeID INTEGER PRIMARY KEY, KeywordTypeName TEXT);
            CREATE TABLE TranscriptKeywordAssignments (
                TranscriptKeywordAssignmentID INTEGER PRIMARY KEY,
                TranscriptID INTEGER, KeywordID INTEGER, StartTime INTEGER, EndTime INTEGER
            );
            CREATE TABLE EpisodeKeywordAssignments (
                EpisodeKeywordAssignmentID INTEGER PRIMARY KEY,
                EpisodeID INTEGER, KeywordID INTEGER, StartTime INTEGER, EndTime INTEGER
            );
            """
        )
        await db.execute(
            "INSERT INTO KeywordTypes (KeywordTypeID, KeywordTypeName) VALUES (1, 'Theme')"
        )
        await db.execute(
            "INSERT INTO Keywords (KeywordID, KeywordName, KeywordTypeID) "
            "VALUES (1, 'Positive', 1)"
        )
        await db.execute(
            "INSERT INTO MediaFiles (MediaID, MediaFileName, MediaFilePath) "
            "VALUES (1, 'sample.mp4', ?)",
            (media_path,),
        )
        await db.execute(
            "INSERT INTO Episodes (EpisodeID, EpisodeName, EpisodeFileName, EpisodeFilePath) "
            "VALUES (1, 'EpOne', 'sample.mp4', ?)",
            (media_path,),
        )
        await db.execute(
            "INSERT INTO Transcripts (TranscriptID, TranscriptName, TranscriptText, EpisodeID) "
            "VALUES (1, 'transcript1', 'Hello transana world', 1)"
        )
        await db.execute(
            "INSERT INTO TranscriptKeywordAssignments "
            "(TranscriptKeywordAssignmentID, TranscriptID, KeywordID, StartTime, EndTime) "
            "VALUES (1, 1, 1, 0, 500)"
        )
        await db.execute(
            "INSERT INTO EpisodeKeywordAssignments "
            "(EpisodeKeywordAssignmentID, EpisodeID, KeywordID, StartTime, EndTime) "
            "VALUES (1, 1, 1, 1000, 2000)"
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


async def test_import_auto_detects_rqda_and_survey(project_client):
    """The auto-detect import endpoint routes files by content — no format
    chooser needed."""
    client, tmp_path = project_client
    rqda_path = tmp_path / "sample.rqda"
    await build_rqda_db(rqda_path)
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("sample.rqda", rqda_path.read_bytes(), "application/octet-stream")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["sources"] == 1
    assert res.json()["codings"] == 1

    csv = "name,age,comment\nalice,42,hello world\nbob,33,second row\n"
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("survey.csv", csv.encode(), "text/csv")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cases"] == 2

    codebook = "Theme>>Subtheme>>code1\nTheme>>code2\n"
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("codebook.txt", codebook.encode(), "text/plain")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["codes"] == 2

    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("garbage.bin", b"\x00\x01\x02 not a format", "application/octet-stream")},
    )
    assert res.status_code == 422


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
# Transana
# ----------------------------------------------------------------------

async def test_import_transana(project_client):
    client, tmp_path = project_client
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    media_file = media_dir / "sample.mp4"
    media_file.write_bytes(b"fake mp4 bytes")
    tprd_path = tmp_path / "sample.tprd"
    await build_transana_db(tprd_path, str(media_file))
    res = await client.post(
        "/api/v1/interchange/import/transana",
        files={"file": ("sample.tprd", tprd_path.read_bytes(), "application/octet-stream")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["sources"] == 2  # transcript text source + media file source
    assert body["categories"] == 1
    assert body["codes"] == 1
    assert body["codings"] == 2  # 1 text coding + 1 AV coding
    assert body["skipped"] == 0

    sources = (await client.get("/api/v1/sources")).json()
    by_name = {s["name"]: s for s in sources}
    assert "transcript1" in by_name
    assert "sample.mp4" in by_name
    transcript_id = by_name["transcript1"]["id"]
    detail = (await client.get(f"/api/v1/sources/{transcript_id}")).json()
    assert detail["fulltext"] == "Hello transana world"

    # Timecode range 0-500ms projected onto the 20-char transcript.
    codings = (await client.get(f"/api/v1/codings/text/{transcript_id}")).json()
    assert len(codings) == 1
    assert codings[0]["pos0"] == 0
    assert codings[0]["pos1"] == 20
    assert codings[0]["seltext"] == "Hello transana world"

    # Episode assignment keeps its millisecond positions as an AV coding.
    av = (await client.get(f"/api/v1/codings/av/{by_name['sample.mp4']['id']}")).json()
    assert len(av) == 1
    assert av[0]["pos0"] == 1000
    assert av[0]["pos1"] == 2000


async def test_import_auto_detects_transana(project_client):
    """The auto-detect endpoint routes a .tprd database to the Transana importer."""
    client, tmp_path = project_client
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    media_file = media_dir / "sample.mp4"
    media_file.write_bytes(b"fake mp4 bytes")
    tprd_path = tmp_path / "sample.tprd"
    await build_transana_db(tprd_path, str(media_file))
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("sample.tprd", tprd_path.read_bytes(), "application/octet-stream")},
        data={"codername": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sources"] == 2
    assert body["codes"] == 1
    assert body["codings"] == 2


async def test_import_transana_partial_schema(project_client):
    """Only some Transana tables exist — the importer maps what is there.

    This variant has no media files and stores character offsets instead of
    timecodes, so positions are taken verbatim.
    """
    client, tmp_path = project_client
    path = tmp_path / "partial.tprd"
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE Transcripts (
                TranscriptID INTEGER PRIMARY KEY, TranscriptName TEXT, TranscriptText TEXT
            );
            CREATE TABLE Keywords (KeywordID INTEGER PRIMARY KEY, KeywordName TEXT);
            CREATE TABLE KeywordAssignments (
                AssignmentID INTEGER PRIMARY KEY,
                TranscriptID INTEGER, KeywordID INTEGER, StartChar INTEGER, EndChar INTEGER
            );
            """
        )
        await db.execute(
            "INSERT INTO Transcripts VALUES (1, 'doc.txt', 'The quick brown fox')"
        )
        await db.execute("INSERT INTO Keywords VALUES (1, 'Fox')")
        await db.execute("INSERT INTO KeywordAssignments VALUES (1, 1, 1, 4, 9)")
        await db.commit()
    res = await client.post(
        "/api/v1/interchange/import/transana",
        files={"file": ("partial.tprd", path.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["sources"] == 1
    assert body["codes"] == 1
    assert body["codings"] == 1
    assert body["categories"] == 0

    sources = (await client.get("/api/v1/sources")).json()
    fid = sources[0]["id"]
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert codings[0]["pos0"] == 4
    assert codings[0]["pos1"] == 9
    assert codings[0]["seltext"] == "quick"


async def test_import_transana_missing_tables_rejected(project_client):
    """A SQLite database without Transana tables is rejected with 422 —
    on the explicit endpoint and in auto-detection."""
    client, tmp_path = project_client
    path = tmp_path / "notransana.sqlite3"
    async with aiosqlite.connect(path) as db:
        await db.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, bar TEXT)")
        await db.commit()
    payload = {"file": ("x.sqlite3", path.read_bytes(), "application/octet-stream")}
    res = await client.post("/api/v1/interchange/import/transana", files=payload)
    assert res.status_code == 422
    res = await client.post("/api/v1/interchange/import/auto", files=payload)
    assert res.status_code == 422


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


async def test_import_transana_garbage_rejected(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/interchange/import/transana",
        files={
            "file": ("bad.tprd", b"not a sqlite database at all", "application/octet-stream")
        },
    )
    assert res.status_code == 422


# ----------------------------------------------------------------------
# Preview (sniff + sample, read-only)
# ----------------------------------------------------------------------

async def test_preview_survey(tmp_path):
    """The preview endpoint sniffs a CSV and samples header + rows + the
    detected qualitative columns — without a project being open."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csv_data = "Name,Age,Comment\nalice,42,hello world\nbob,33,second row\n"
        res = await c.post(
            "/api/v1/interchange/import/preview",
            files={"file": ("survey.csv", csv_data.encode(), "text/csv")},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["format"] == "survey"
        assert body["columns"] == ["Name", "Age", "Comment"]
        assert len(body["rows_sample"]) == 2
        assert body["rows_sample"][0] == ["alice", "42", "hello world"]
        # The case-name column is excluded; numeric columns are not qualitative.
        assert body["qual_columns"] == ["Comment"]
        assert body["lines"] is None


async def test_preview_codebook_lines(tmp_path):
    """Codebooks preview as their first lines."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        codebook = "Theme>>Subtheme>>code1\nTheme>>code2\n"
        res = await c.post(
            "/api/v1/interchange/import/preview",
            files={"file": ("codebook.txt", codebook.encode(), "text/plain")},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["format"] == "codebook"
        assert body["lines"] == ["Theme>>Subtheme>>code1", "Theme>>code2"]
        assert body["columns"] is None
        assert body["qual_columns"] is None


async def test_preview_unknown_format_rejected(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post(
            "/api/v1/interchange/import/preview",
            files={"file": ("garbage.bin", b"\x00\x01\x02 not a format", "application/octet-stream")},
        )
        assert res.status_code == 422


async def test_preview_force_kind_override(tmp_path):
    """A forced format re-interprets the file (CSV → codebook lines)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csv_data = "Name,Age\nalice,42\n"
        res = await c.post(
            "/api/v1/interchange/import/preview",
            files={"file": ("survey.csv", csv_data.encode(), "text/csv")},
            data={"force_kind": "codebook"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["format"] == "codebook"
        assert body["lines"] == ["Name,Age", "alice,42"]

        res = await c.post(
            "/api/v1/interchange/import/preview",
            files={"file": ("survey.csv", csv_data.encode(), "text/csv")},
            data={"force_kind": "nope"},
        )
        assert res.status_code == 422


# ----------------------------------------------------------------------
# Forced-format import (import/auto with force_kind)
# ----------------------------------------------------------------------

async def test_import_auto_force_kind(project_client):
    """force_kind routes the upload to the named importer, bypassing sniffing."""
    client, _ = project_client
    codebook = "Theme>>Subtheme>>code1\nTheme>>code2\n"
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("cb.txt", codebook.encode(), "text/plain")},
        data={"force_kind": "codebook"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["codes"] == 2

    # A forced survey CSV keeps the qualitative_headers option.
    csv_data = "Name,Age,Comment\nalice,42,hello world\nbob,33,second row\n"
    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("survey.csv", csv_data.encode(), "text/csv")},
        data={"force_kind": "survey", "qualitative_headers": "Comment"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cases"] == 2
    assert body["qualitative_files"] == 2

    res = await client.post(
        "/api/v1/interchange/import/auto",
        files={"file": ("cb.txt", codebook.encode(), "text/plain")},
        data={"force_kind": "zotero"},
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
