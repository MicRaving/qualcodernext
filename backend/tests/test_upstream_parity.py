"""Tests for the upstream-parity features added in the integration pass:
sub-codes, bookmarks, image-rect updates, new reports (code segments,
summary, relations, word frequencies, charts, codebook), pseudonyms,
speakers, file replacement, bad links, references, codebook import,
survey qualitative columns and the MCP endpoint."""

from __future__ import annotations

import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from qualcoder_api.main import app
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodeRepository, CodingRepository


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project seeded with one code + one text file."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "parity.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        res = await c.post(
            "/api/v1/sources/import",
            files={"file": ("interview.txt", "old alpha beta\nMore text here.", "text/plain")},
            data={"owner": "tester"},
        )
        assert res.status_code == 200, res.text
        res = await c.post("/api/v1/codes", json={"name": "code_a", "owner": "tester"})
        assert res.status_code == 201, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def project_session(tmp_path):
    """Async session into a fresh project (mirrors test_coding_service)."""
    from qualcoder_api.services.project_service import ProjectService

    svc = ProjectService()
    await svc.create_project(str(tmp_path / "parity_session.qda"), codername="tester")
    assert svc.session_factory is not None
    async with svc.session_factory() as session:
        yield session
    await svc.close_project()


@pytest.fixture
async def project_db(project_client):
    """Async session into the API fixture's open project."""
    from qualcoder_api.main import service

    async with service.session_factory() as session:
        yield session


# ----------------------------------------------------------------------
# Sub-codes
# ----------------------------------------------------------------------


async def test_subcode_create_and_cycle_guard(project_session):
    session = project_session
    repo = CodeRepository(session)
    parent = await repo.add_code(name="parent", owner="tester")
    child = await repo.add_code(name="child", owner="tester", supercid=parent.cid)
    assert child.supercid == parent.cid
    with pytest.raises(ValueError, match="own sub-code"):
        await repo.set_supercid(parent.cid, child.cid)  # cycle
    with pytest.raises(ValueError, match="own parent"):
        await repo.set_supercid(child.cid, child.cid)  # self
    moved = await repo.set_supercid(child.cid, None)  # unlink ok
    assert moved.supercid is None


async def test_code_tree_marks_subcodes(project_client):
    client, _ = project_client
    from qualcoder_api.main import service

    async with service.session_factory() as session:
        parent = await CodeRepository(session).add_code(name="p", owner="tester")
        await CodeRepository(session).add_code(name="c", owner="tester", supercid=parent.cid)
    res = await client.get("/api/v1/codes")
    assert res.status_code == 200
    items = res.json()
    sub = next(item for item in items if item["name"] == "c")
    assert sub["subcode"] is True
    assert sub["parent_id"] == parent.cid


# ----------------------------------------------------------------------
# Bookmarks
# ----------------------------------------------------------------------


async def test_bookmarks_roundtrip(project_client):
    client, _ = project_client
    res = await client.put("/api/v1/bookmarks", json={"file_id": 1, "pos": 42})
    assert res.status_code == 200
    assert res.json()["bookmark_file_id"] == 1
    res = await client.put(
        "/api/v1/bookmarks/av", json={"file_id": 2, "msec": 1500, "textpos": 10}
    )
    assert res.status_code == 200
    assert res.json()["av_bookmark_msec"] == 1500
    res = await client.get("/api/v1/bookmarks")
    data = res.json()
    assert data["bookmark_file_id"] == 1
    assert data["av_bookmark_file_id"] == 2


# ----------------------------------------------------------------------
# Image coding update (move/resize rectangle)
# ----------------------------------------------------------------------


async def test_image_coding_patch(project_client, project_db):
    client, _ = project_client
    session = project_db
    coding = await CodingRepository(session).add_image_coding(
        id=1, x1=1, y1=2, width=3, height=4, cid=1, owner="tester"
    )
    res = await client.patch(
        f"/api/v1/codings/image/{coding.imid}",
        json={"x1": 5, "y1": 6, "width": 10, "height": 20},
    )
    assert res.status_code == 200
    body = res.json()
    assert (body["x1"], body["y1"], body["width"], body["height"]) == (5, 6, 10, 20)


# ----------------------------------------------------------------------
# New reports
# ----------------------------------------------------------------------


async def test_code_segments_report(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/reports/code-segments/1")
    assert res.status_code == 200
    assert isinstance(res.json()["rows"], list)


async def test_code_summary_report(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/reports/code-summary/1")
    assert res.status_code == 200
    assert res.json()["name"]
    res = await client.get("/api/v1/reports/code-summary/999999")
    assert res.status_code == 404


async def test_coder_file_comparison(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/reports/coder-file-comparison",
        json={"coder_a": "default", "coder_b": "other"},
    )
    assert res.status_code in (200, 422)
    if res.status_code == 200:
        assert "files" in res.json()


async def test_code_relations_report(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/reports/code-relations?owner=default")
    assert res.status_code == 200
    assert "relations" in res.json()


async def test_word_frequencies_report(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/reports/word-frequencies?limit=10")
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert isinstance(rows, list)
    assert all("word" in r and "count" in r for r in rows)


async def test_charts_endpoints(project_client):
    client, _ = project_client
    for kind in ("cumulative", "stacked-files", "stacked-cases", "bar-frequency",
                 "bar-volume", "heatmap-file-code", "heatmap-case"):
        res = await client.get(f"/api/v1/reports/charts?kind={kind}")
        assert res.status_code == 200, f"{kind}: {res.text}"
        assert res.json()["kind"] == kind
    res = await client.get("/api/v1/reports/charts?kind=bogus")
    assert res.status_code == 422


async def test_codebook_export(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/reports/codebook")
    assert res.status_code == 200
    assert ">>" in res.json()["text"] or res.json()["text"] != ""


# ----------------------------------------------------------------------
# Pseudonyms
# ----------------------------------------------------------------------


async def test_pseudonyms_crud(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    monkeypatch.setattr("qualcoder_api.services.pseudonyms.pseudonyms_path",
                        lambda p: tmp_path / "pseudonyms.json")
    res = await client.post("/api/v1/pseudonyms", json={"original": "Tom", "pseudonym": ""})
    assert res.status_code == 200
    entry = res.json()["pseudonym"]
    assert len(entry["pseudonym"]) == 6
    res = await client.get("/api/v1/pseudonyms")
    assert len(res.json()["pseudonyms"]) == 1
    res = await client.delete("/api/v1/pseudonyms/Tom")
    assert res.status_code == 200
    res = await client.get("/api/v1/pseudonyms")
    assert res.json()["pseudonyms"] == []


# ----------------------------------------------------------------------
# Speakers
# ----------------------------------------------------------------------


async def test_speakers_detect_and_mark(project_client, project_db):
    client, _ = project_client
    session = project_db
    # Seed a transcript with speaker markers.
    await session.execute(
        tables.source.insert().values(
            name="focus.txt", fulltext="Anna: Hello there.\nBob: Hi Anna.\n",
            mediapath="/docs/focus.txt", owner="tester", date="",
        )
    )
    await session.commit()
    res = await client.post(
        "/api/v1/speakers/detect", json={"identifiers": ["name"], "fid": 2}
    )
    assert res.status_code == 200
    body = res.json()
    assert {s["name"] for s in body["speakers"]} == {"Anna", "Bob"}
    res = await client.post(
        "/api/v1/speakers/mark", json={"identifiers": ["name"], "fid": 2}
    )
    assert res.status_code == 200
    assert res.json()["turns_marked"] == 2
    row = await session.execute(
        text("SELECT COUNT(*) FROM code_cat WHERE name = '📌 Speakers'")
    )
    assert row.scalar_one() == 1


# ----------------------------------------------------------------------
# Text file replacement
# ----------------------------------------------------------------------


async def test_replace_text_file(project_client, project_db, tmp_path):
    client, _ = project_client
    session = project_db
    await session.execute(
        tables.source.update().where(tables.source.c.id == 1).values(
            fulltext="old alpha beta", mediapath=None
        )
    )
    await session.commit()
    new_file = tmp_path / "new.txt"
    new_file.write_text("new alpha beta", encoding="utf-8")
    with open(new_file, "rb") as f:  # noqa: ASYNC230 - test fixture
        res = await client.post(
            "/api/v1/sources/1/replace",
            files={"file": ("new.txt", f, "text/plain")},
        )
    assert res.status_code == 200, res.text
    row = await session.execute(
        text("SELECT name, fulltext FROM source WHERE id = 1")
    )
    name, fulltext = row.first()
    assert name == "new.txt"
    assert fulltext == "new alpha beta"


# ----------------------------------------------------------------------
# Bad links
# ----------------------------------------------------------------------


async def test_bad_links(project_client, project_db):
    client, _ = project_client
    session = project_db
    await session.execute(
        text("UPDATE source SET mediapath = 'docs:C:/does/not/exist.txt' WHERE id = 1")
    )
    await session.commit()
    res = await client.get("/api/v1/sources/bad-links")
    assert res.status_code == 200
    assert any("does/not/exist" in link["path"] for link in res.json()["links"])


# ----------------------------------------------------------------------
# References + codebook import + survey qualitative
# ----------------------------------------------------------------------


async def test_references_roundtrip(project_client, project_db):
    client, _ = project_client
    session = project_db
    await session.execute(
        tables.ris.insert().values(risid=1, tag="TI", longtag="title", value="A book")
    )
    await session.execute(
        tables.ris.insert().values(risid=1, tag="AU", longtag="authors", value="Smith, J.")
    )
    await session.commit()
    res = await client.get("/api/v1/references")
    assert res.status_code == 200
    refs = res.json()["references"]
    assert len(refs) == 1
    assert refs[0]["title"] == "A book"
    res = await client.delete("/api/v1/references/1")
    assert res.status_code == 204


async def test_codebook_import(project_client):
    client, _ = project_client
    content = "Interviews>>Attitudes>>likes it\tthe user likes it\nAttitudes>>hates it\n"
    res = await client.post(
        "/api/v1/interchange/import/codebook",
        files={"file": ("codes.txt", io.BytesIO(content.encode()), "text/plain")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["categories"] == 2
    assert body["codes"] == 2


async def test_survey_qualitative_columns(project_client, project_db):
    client, _ = project_client
    session = project_db
    csv_data = "name,age,answer\nAnna,30,This is a long answer.\nBob,25,Another answer here.\n"
    res = await client.post(
        "/api/v1/interchange/import/survey",
        files={"file": ("s.csv", io.BytesIO(csv_data.encode()), "text/csv")},
        data={"qualitative_headers": "answer"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["qualitative_files"] == 2
    assert body["qualitative_codings"] == 2
    # A code named after the column exists and files are named case_field.
    row = await session.execute(
        text("SELECT COUNT(*) FROM code_name WHERE name = 'answer'")
    )
    assert row.scalar_one() == 1


# ----------------------------------------------------------------------
# Merge projects
# ----------------------------------------------------------------------


async def test_merge_projects(project_client, tmp_path):
    client, _ = project_client
    # Build a source project archive with a minimal QualCoder DB.
    import aiosqlite

    source_dir = tmp_path / "other.qda"
    source_dir.mkdir()
    conn = await aiosqlite.connect(source_dir / "data.qda")
    from qualcoder_api.persistence.schema import create_new_project_schema

    await create_new_project_schema(conn, app_version="QualCoder 4.0", codername="tester")
    cur = await conn.cursor()
    await cur.execute(
        "INSERT INTO code_name (name, memo, owner, date, color) VALUES ('merged_code', '', 'tester', '2026-01-01', '#ffffff')"
    )
    await cur.execute(
        "INSERT INTO source (name, fulltext, mediapath, owner, date) VALUES ('extra.txt', 'extra text', '/docs/extra.txt', 'tester', '2026-01-01')"
    )
    await conn.commit()
    await conn.close()
    archive = tmp_path / "other.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(source_dir / "data.qda", "data.qda")
    with open(archive, "rb") as f:  # noqa: ASYNC230 - test fixture
        res = await client.post(
            "/api/v1/interchange/import/merge",
            files={"file": ("other.zip", f, "application/zip")},
        )
    assert res.status_code == 200, res.text
    assert res.json()["codes"] == 1


# ----------------------------------------------------------------------
# MCP endpoint
# ----------------------------------------------------------------------


async def test_mcp_read_and_write_gate(project_client, project_db, monkeypatch, tmp_path):
    client, _ = project_client
    session = project_db
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    # read permission: tools/list works, write tool is rejected.
    res = await client.post(
        "/api/v1/ai/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert res.status_code == 200
    names = [t["name"] for t in res.json()["result"]["tools"]]
    assert "get_code_tree" in names
    assert "create_code" not in names

    res = await client.post(
        "/api/v1/ai/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "create_code", "arguments": {"name": "mcp-made"}},
        },
    )
    assert res.status_code == 200
    assert res.json()["error"]["code"] == -32004

    # With write permission, create_code works and is audit-logged.
    from qualcoder_api.services import user_settings

    settings = user_settings.load_settings()
    settings["ai"]["mcp_permissions"] = "write"
    user_settings.save_settings(settings)
    res = await client.post(
        "/api/v1/ai/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "create_code", "arguments": {"name": "mcp-made"}},
        },
    )
    assert res.status_code == 200
    assert res.json()["result"]["content"][0]["text"]
    row = await session.execute(
        text("SELECT COUNT(*) FROM audit_log WHERE action = 'code.create'")
    )
    assert row.scalar_one() >= 1

    res = await client.post(
        "/api/v1/ai/mcp",
        json={"jsonrpc": "2.0", "id": 4, "method": "resources/read",
              "params": {"uri": "qualcoder://codes"}},
    )
    assert res.status_code == 200
    assert res.json()["result"]["contents"][0]["mimeType"] == "application/json"


# ----------------------------------------------------------------------
# Graphs (code-map editor)
# ----------------------------------------------------------------------


async def test_graph_crud_and_items(project_client):
    client, _ = project_client
    res = await client.post("/api/v1/graphs", json={"name": "My map"})
    assert res.status_code == 201, res.text
    grid = res.json()["grid"]

    res = await client.post(
        "/api/v1/graphs",
        json={"name": "My map"},
    )
    assert res.status_code == 409  # graph names are unique (legacy constraint)

    res = await client.post(
        f"/api/v1/graphs/{grid}/items/cdct",
        json={"kind": "code", "ref_id": 1, "x": 100, "y": 50},
    )
    assert res.status_code == 201, res.text
    gtextid = res.json()["gtextid"]
    assert res.json()["displaytext"] == "code_a"

    res = await client.patch(
        f"/api/v1/graphs/{grid}/items/cdct/{gtextid}",
        json={"x": 200, "y": 300},
    )
    assert res.status_code == 200
    assert (res.json()["x"], res.json()["y"]) == (200, 300)

    res = await client.post(
        f"/api/v1/graphs/{grid}/items/cdct",
        json={"kind": "category", "ref_id": 1, "x": 10, "y": 10},
    )
    assert res.status_code == 201
    other = res.json()["gtextid"]

    res = await client.post(
        f"/api/v1/graphs/{grid}/lines/cdct",
        json={"from_node": gtextid, "to_node": other, "label": "is context for",
              "arrow_mode": "solid_with_arrow"},
    )
    assert res.status_code == 201, res.text

    res = await client.get(f"/api/v1/graphs/{grid}")
    assert res.status_code == 200
    data = res.json()
    assert len(data["cdct_items"]) == 2
    assert len(data["cdct_lines"]) == 1
    assert data["cdct_lines"][0]["label"] == "is context for"

    res = await client.post(
        f"/api/v1/graphs/{grid}/items/free",
        json={"x": 5, "y": 5, "free_text": "note"},
    )
    assert res.status_code == 201
    res = await client.post(
        f"/api/v1/graphs/{grid}/lines/entity",
        json={"from_kind": "free", "from_id": res.json()["freetextid"],
              "to_kind": "code", "to_id": 1},
    )
    assert res.status_code == 201, res.text

    # Deleting a node removes lines touching it.
    res = await client.delete(f"/api/v1/graphs/{grid}/items/cdct/{gtextid}")
    assert res.status_code == 204
    res = await client.get(f"/api/v1/graphs/{grid}")
    assert len(res.json()["cdct_lines"]) == 0

    res = await client.delete(f"/api/v1/graphs/{grid}")
    assert res.status_code == 204
    res = await client.get(f"/api/v1/graphs/{grid}")
    assert res.status_code == 404


async def test_graph_models_generate(project_client, project_db):
    client, _ = project_client
    session = project_db
    # Seed a second code, a coding pair for co-occurrence, and a case link
    # so the file/case models have data.
    await session.execute(
        text("INSERT INTO code_name (name, memo, owner, date, color) VALUES ('code_b', '', 'tester', '2026-01-01', '#ffffff')")
    )
    await session.execute(
        text("INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date) VALUES (2, 1, 'x', 0, 1, 'tester', '2026-01-01')")
    )
    await session.execute(
        text("INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date) VALUES (1, 1, 'y', 6, 7, 'tester', '2026-01-01')")
    )
    await session.execute(
        text("INSERT INTO cases (name, memo, owner, date) VALUES ('case_one', '', 'tester', '2026-01-01')")
    )
    await session.execute(
        text("INSERT INTO case_text (caseid, fid, pos0, pos1, owner, date) VALUES (1, 1, 0, 5, 'tester', '2026-01-01')")
    )
    await session.commit()
    for model in ("category-hierarchy", "file-hierarchy", "file-comparison",
                  "case-hierarchy", "case-comparison", "cooccurrence-network"):
        res = await client.post(
            "/api/v1/graphs/models",
            json={"model": model, "name": f"model {model}"},
        )
        assert res.status_code == 201, f"{model}: {res.text}"
        grid = res.json()["grid"]
        data = (await client.get(f"/api/v1/graphs/{grid}")).json()
        assert data["cdct_items"] or data["file_items"] or data["case_items"], model
    res = await client.post(
        "/api/v1/graphs/models", json={"model": "bogus", "name": "x"}
    )
    assert res.status_code == 422


# ----------------------------------------------------------------------
# Reference attachments
# ----------------------------------------------------------------------


async def test_reference_attach_and_detach(project_client, project_db):
    client, _ = project_client
    session = project_db
    await session.execute(
        tables.ris.insert().values(risid=1, tag="TI", longtag="title", value="Paper")
    )
    await session.commit()
    res = await client.post(
        "/api/v1/references/1/attach",
        files={"file": ("paper.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    source_id = res.json()["source_id"]
    row = await session.execute(
        text("SELECT risid FROM source WHERE id = :id"), {"id": source_id}
    )
    assert row.first()[0] == 1
    res = await client.delete(f"/api/v1/references/1/attach/{source_id}")
    assert res.status_code == 204
    row = await session.execute(
        text("SELECT risid FROM source WHERE id = :id"), {"id": source_id}
    )
    assert row.first()[0] is None


# ----------------------------------------------------------------------
# Code color scheme
# ----------------------------------------------------------------------


async def test_color_scheme_roundtrip(project_client, monkeypatch, tmp_path):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    client, _ = project_client
    res = await client.get("/api/v1/color-scheme")
    assert res.status_code == 200
    assert len(res.json()["colors"]) == 120
    custom = ["#112233", "#445566", "#778899", "#aabbcc", "#ddeeff", "#123456",
              "#abcdef", "#fedcba", "#010203", "#987654", "#555555", "#666666"]
    res = await client.put("/api/v1/color-scheme", json={"colors": custom})
    assert res.status_code == 200
    assert res.json()["colors"] == custom
    # New codes use colors from the custom palette.
    res = await client.post("/api/v1/codes", json={"name": "colored", "owner": "tester"})
    assert res.status_code == 201
    assert res.json()["color"] in custom
    res = await client.delete("/api/v1/color-scheme")
    assert res.status_code == 200
    assert len(res.json()["colors"]) == 120
