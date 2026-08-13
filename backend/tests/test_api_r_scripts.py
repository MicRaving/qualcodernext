"""API tests — R integration: saved R scripts (CRUD) + prepare-report."""

from __future__ import annotations

import csv

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.r_scripts import router as r_scripts_router
from qualcoder_api.main import app


def _ensure_r_scripts_wired() -> None:
    """Mount the r router when the v1 router does not carry it yet.

    The router is wired into ``api/v1/router.py`` by the supervisor; until
    then this test file mounts it itself so the suite runs standalone.
    """
    if any(getattr(route, "path", "") == "/api/v1/r/scripts" for route in app.router.routes):
        return
    app.include_router(r_scripts_router, prefix="/api/v1")


_ensure_r_scripts_wired()


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    _ensure_r_scripts_wired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "r.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def report_dataset(project_client):
    """Open project seeded with a file and codes/codings."""
    client, _ = project_client

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("interview.txt", "alpha beta\ngamma", "text/plain")},
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]

    code_a = await client.post("/api/v1/codes", json={"name": "ThemeA", "color": "#FF0000"})
    assert code_a.status_code == 201, code_a.text
    code_b = await client.post("/api/v1/codes", json={"name": "ThemeB", "color": "#00FF00"})
    assert code_b.status_code == 201, code_b.text
    cids = {"A": code_a.json()["cid"], "B": code_b.json()["cid"]}

    await client.post(
        "/api/v1/codings/text",
        json={"cid": cids["A"], "fid": fid, "seltext": "alpha", "pos0": 0, "pos1": 5},
    )
    await client.post(
        "/api/v1/codings/text",
        json={"cid": cids["B"], "fid": fid, "seltext": "beta", "pos0": 6, "pos1": 10},
    )
    await client.post(
        "/api/v1/codings/text",
        json={"cid": cids["A"], "fid": fid, "seltext": "alpha", "pos0": 11, "pos1": 16},
    )

    return {"fid": fid, "cids": cids}


# ----------------------------------------------------------------------
# Saved R scripts CRUD
# ----------------------------------------------------------------------

async def test_r_script_crud(project_client):
    client, _ = project_client

    created = await client.post(
        "/api/v1/r/scripts",
        json={"name": "My Script", "script": "df <- read.csv('x.csv')\nstr(df)", "owner": "tester"},
    )
    assert created.status_code == 201, created.text
    script = created.json()
    assert script["id"] > 0
    assert script["name"] == "My Script"
    assert script["script"].startswith("df <- read.csv")
    assert script["owner"] == "tester"
    assert script["created"] is not None
    assert script["updated"] is not None

    # List: newest first, list shape is (id, name, updated).
    listed = (await client.get("/api/v1/r/scripts")).json()
    assert listed[0]["id"] == script["id"]
    assert listed[0]["name"] == "My Script"
    assert set(listed[0]) == {"id", "name", "updated"}

    # GET single: full content.
    got = (await client.get(f"/api/v1/r/scripts/{script['id']}")).json()
    assert got["script"] == script["script"]
    assert got["owner"] == "tester"

    # PATCH name and script; updated timestamp moves.
    patched = await client.patch(
        f"/api/v1/r/scripts/{script['id']}",
        json={"name": "Renamed", "script": "print('hi')"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["script"] == "print('hi')"

    # PATCH with no fields is a no-op returning the current row.
    noop = await client.patch(f"/api/v1/r/scripts/{script['id']}", json={})
    assert noop.status_code == 200
    assert noop.json()["name"] == "Renamed"

    # Delete removes it; deleting twice yields 404; unknown ids 404.
    assert (await client.delete(f"/api/v1/r/scripts/{script['id']}")).status_code == 204
    assert (await client.get("/api/v1/r/scripts")).json() == []
    assert (await client.delete(f"/api/v1/r/scripts/{script['id']}")).status_code == 404
    assert (await client.get("/api/v1/r/scripts/9999")).status_code == 404
    assert (await client.patch("/api/v1/r/scripts/9999", json={"name": "x"})).status_code == 404


async def test_r_script_duplicate_name(project_client):
    client, _ = project_client

    res = await client.post("/api/v1/r/scripts", json={"name": "Plot", "script": "plot(1)"})
    assert res.status_code == 201, res.text

    # Same name, different case → 409.
    dup = await client.post("/api/v1/r/scripts", json={"name": "plot", "script": "plot(2)"})
    assert dup.status_code == 409

    # Empty name → 422.
    assert (await client.post("/api/v1/r/scripts", json={"name": "  ", "script": "x"})).status_code == 422

    # Rename onto the existing name → 409; renaming to its own name is fine.
    other = (await client.post("/api/v1/r/scripts", json={"name": "Other", "script": ""})).json()
    res = await client.patch(f"/api/v1/r/scripts/{other['id']}", json={"name": "PLOT"})
    assert res.status_code == 409
    res = await client.patch(f"/api/v1/r/scripts/{other['id']}", json={"name": "Other"})
    assert res.status_code == 200, res.text

    # Empty rename → 422.
    assert (await client.patch(f"/api/v1/r/scripts/{other['id']}", json={"name": " "})).status_code == 422


async def test_r_script_audit_rows(project_client):
    client, _ = project_client

    created = (await client.post(
        "/api/v1/r/scripts",
        json={"name": "Audited", "script": "summary(df)", "owner": "tester"},
    )).json()

    rows = (await client.get("/api/v1/audit", params={"action": "r_script.create"})).json()["rows"]
    assert len(rows) == 1
    create_row = rows[0]
    assert create_row["user"] == "tester"
    assert create_row["entity"] == "r_script"
    assert create_row["entity_id"] == created["id"]
    assert create_row["detail"]["name"] == "Audited"

    await client.patch(f"/api/v1/r/scripts/{created['id']}", json={"script": "table(df)"})
    rows = (await client.get("/api/v1/audit", params={"action": "r_script.update"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == created["id"]
    assert rows[0]["detail"]["script"] == "table(df)"

    await client.delete(f"/api/v1/r/scripts/{created['id']}")
    rows = (await client.get("/api/v1/audit", params={"action": "r_script.delete"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == created["id"]
    assert rows[0]["detail"]["name"] == "Audited"


# ----------------------------------------------------------------------
# Prepare report
# ----------------------------------------------------------------------

def _read_csv(project, report: str) -> list[dict]:
    path = project / "r_exchange" / "in" / f"{report}.csv"
    assert path.exists(), f"missing {path}"
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


async def test_prepare_report_code_frequencies(project_client, report_dataset):
    client, target = project_client

    res = await client.post("/api/v1/r/prepare-report", json={"report": "code-frequencies"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["files"]) == 1
    info = body["files"][0]
    assert info["name"] == "code-frequencies.csv"
    assert info["rows"] == 2
    assert info["cols"] == ["cid", "name", "color", "category", "count"]

    # The CSV was written into the project's r_exchange/in/.
    rows = _read_csv(target, "code-frequencies")
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["ThemeA"]["count"] == "2"
    assert by_name["ThemeB"]["count"] == "1"

    # The stub reads the file through QC_EXCHANGE and str()s it.
    assert "Sys.getenv(\"QC_EXCHANGE\")" in body["stub"]
    assert '"code-frequencies.csv"' in body["stub"]
    assert 'fileEncoding="UTF-8"' in body["stub"]
    assert body["stub"].count("\n") >= 1
    assert body["stub"].endswith("str(df)")


async def test_prepare_report_codes_by_segments(project_client, report_dataset):
    client, target = project_client

    res = await client.post("/api/v1/r/prepare-report", json={"report": "codes-by-segments"})
    assert res.status_code == 200, res.text
    info = res.json()["files"][0]
    assert info["name"] == "codes-by-segments.csv"
    assert info["rows"] == 3
    assert info["cols"] == ["ctid", "file_name", "code_name", "category", "seltext", "owner", "date"]

    rows = _read_csv(target, "codes-by-segments")
    assert len(rows) == 3
    assert all(r["file_name"] == "interview.txt" for r in rows)
    assert sorted(r["seltext"] for r in rows) == ["alpha", "alpha", "beta"]
    assert res.json()["stub"].startswith("df <- read.csv(file.path")


async def test_prepare_report_coder_comparison(project_client, report_dataset):
    client, target = project_client

    res = await client.post("/api/v1/r/prepare-report", json={"report": "coder-comparison"})
    assert res.status_code == 200, res.text
    info = res.json()["files"][0]
    assert info["name"] == "coder-comparison.csv"
    assert info["cols"] == ["owner", "codings_count", "files_count"]

    rows = _read_csv(target, "coder-comparison")
    assert len(rows) == 1
    assert rows[0]["codings_count"] == "3"
    assert rows[0]["files_count"] == "1"


async def test_prepare_report_summary_table(project_client, report_dataset):
    client, target = project_client

    res = await client.post(
        "/api/v1/r/prepare-report",
        json={"report": "summary-table", "fids": [report_dataset["fid"]]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    info = body["files"][0]
    assert info["name"] == "summary-table.csv"
    assert info["cols"] == ["id", "name", "ThemeA", "ThemeB"]
    assert info["rows"] == 1

    rows = _read_csv(target, "summary-table")
    assert len(rows) == 1
    assert rows[0]["name"] == "interview.txt"
    # Memos are empty for the seeded codings → blank cells, header intact.
    assert rows[0]["ThemeA"] == ""
    assert rows[0]["ThemeB"] == ""


async def test_prepare_report_errors(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # No project open → 409.
        res = await c.post("/api/v1/r/prepare-report", json={"report": "code-frequencies"})
        assert res.status_code == 409

        # Unknown report → 422 (also with a project open).
        target = tmp_path / "r.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        res = await c.post("/api/v1/r/prepare-report", json={"report": "word-cloud"})
        assert res.status_code == 422
        assert "word-cloud" in res.json()["detail"]
        await c.post("/api/v1/projects/close")
