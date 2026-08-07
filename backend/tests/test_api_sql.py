"""API tests for ad-hoc SQL reports and saved-query management."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.sql_reports import router as sql_router
from qualcoder_api.main import app

app.include_router(sql_router, prefix="/api/v1")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "sql.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def sql_dataset(project_client):
    """Open project seeded with a text file and one text coding."""
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("interview.txt", "alpha beta gamma", "text/plain")},
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]
    code = await client.post("/api/v1/codes", json={"name": "Theme"})
    assert code.status_code == 201, code.text
    created = await client.post(
        "/api/v1/codings/text",
        json={"cid": code.json()["cid"], "fid": fid, "seltext": "alpha", "pos0": 0, "pos1": 5},
    )
    assert created.status_code == 201, created.text
    return client


# ----------------------------------------------------------------------
# /sql/run
# ----------------------------------------------------------------------

async def test_select_count(sql_dataset):
    res = await sql_dataset.post(
        "/api/v1/sql/run", json={"sql": "SELECT count(*) AS n FROM code_text"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["columns"] == ["n"]
    assert body["rows"] == [[1]]


async def test_select_join(sql_dataset):
    res = await sql_dataset.post(
        "/api/v1/sql/run",
        json={
            "sql": "SELECT source.name, code_text.seltext "
            "FROM source JOIN code_text ON code_text.fid = source.id"
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["columns"] == ["name", "seltext"]
    assert body["rows"] == [["interview.txt", "alpha"]]


async def test_non_select_rejected(sql_dataset):
    for sql in ("UPDATE code_text SET memo='x'", "DELETE FROM source"):
        res = await sql_dataset.post("/api/v1/sql/run", json={"sql": sql})
        assert res.status_code == 422, sql
        assert res.json()["detail"] == "Only read-only queries are allowed"


async def test_multi_statement_rejected(sql_dataset):
    res = await sql_dataset.post("/api/v1/sql/run", json={"sql": "SELECT 1; SELECT 2"})
    assert res.status_code == 422
    assert res.json()["detail"] == "Multiple statements are not allowed"


async def test_syntax_error_rejected(sql_dataset):
    res = await sql_dataset.post("/api/v1/sql/run", json={"sql": "SELECT * FROM no_such_table"})
    assert res.status_code == 422
    assert "no_such_table" in res.json()["detail"]


# ----------------------------------------------------------------------
# /sql/saved lifecycle
# ----------------------------------------------------------------------

async def test_saved_query_lifecycle(sql_dataset):
    payload = {"title": "q1", "ssql": "SELECT 1", "description": "", "grouper": ""}
    created = await sql_dataset.post("/api/v1/sql/saved", json=payload)
    assert created.status_code == 201, created.text

    duplicate = await sql_dataset.post("/api/v1/sql/saved", json=payload)
    assert duplicate.status_code == 409

    listed = await sql_dataset.get("/api/v1/sql/saved")
    assert listed.status_code == 200
    assert listed.json()["rows"] == [payload]

    deleted = await sql_dataset.delete("/api/v1/sql/saved/q1")
    assert deleted.status_code == 204

    listed = await sql_dataset.get("/api/v1/sql/saved")
    assert listed.json()["rows"] == []


async def test_saved_queries_require_open_project():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/v1/sql/saved")
        assert res.status_code == 409
