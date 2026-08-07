"""API tests for the reports endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the developer's real user settings out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "reports.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def report_dataset(project_client):
    """Open project seeded with a file, codes, codings, case, attribute."""
    client, _ = project_client

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("interview.txt", "alpha beta\ngamma", "text/plain")},
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]

    cat = await client.post("/api/v1/codes/categories", json={"name": "Top"})
    assert cat.status_code == 201, cat.text
    catid = cat.json()["catid"]

    code_a = await client.post(
        "/api/v1/codes",
        json={"name": "ThemeA", "catid": catid, "color": "#FF0000"},
    )
    assert code_a.status_code == 201, code_a.text
    code_b = await client.post(
        "/api/v1/codes",
        json={"name": "ThemeB", "color": "#00FF00"},
    )
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

    case = await client.post("/api/v1/cases", json={"name": "Report Case"})
    assert case.status_code == 201, case.text
    caseid = case.json()["caseid"]
    link = await client.post(
        f"/api/v1/cases/{caseid}/files", json={"fid": fid}
    )
    assert link.status_code == 201, link.text

    created = await client.post(
        "/api/v1/attributes/types",
        json={"name": "InterviewDate", "case_or_file": "file", "value_type": "text"},
    )
    assert created.status_code == 201, created.text
    setv = await client.put(
        f"/api/v1/attributes/values/InterviewDate?attr_type=file&entity_id={fid}",
        json={"value": "2024-01-01"},
    )
    assert setv.status_code == 200, setv.text

    return {"fid": fid, "cids": cids, "caseid": caseid}


# ----------------------------------------------------------------------
# Report endpoints
# ----------------------------------------------------------------------

async def test_code_frequencies(project_client, report_dataset):
    client, _ = project_client
    rows = (await client.get("/api/v1/reports/code-frequencies")).json()["rows"]
    by_name = {r["name"]: r for r in rows}
    assert by_name["ThemeA"]["count"] == 2
    assert by_name["ThemeA"]["category"] == "Top"
    assert by_name["ThemeB"]["count"] == 1


async def test_codes_by_segments(project_client, report_dataset):
    client, _ = project_client
    rows = (await client.get("/api/v1/reports/codes-by-segments")).json()["rows"]
    assert len(rows) == 3
    assert all(r["file_name"] == "interview.txt" for r in rows)
    names = sorted(r["code_name"] for r in rows)
    assert names == ["ThemeA", "ThemeA", "ThemeB"]


async def test_comparison_table(project_client, report_dataset):
    client, _ = project_client
    body = (await client.get("/api/v1/reports/comparison-table")).json()
    assert len(body["files"]) == 1
    assert body["files"][0]["name"] == "interview.txt"
    assert [c["name"] for c in body["codes"]] == ["ThemeA", "ThemeB"]
    assert body["counts"] == [[2, 1]]


async def test_cooccurrence(project_client, report_dataset):
    client, _ = project_client
    body = (await client.get("/api/v1/reports/co-occurrence")).json()
    assert [c["name"] for c in body["codes"]] == ["ThemeA", "ThemeB"]
    assert body["counts"] == [[1, 1], [1, 1]]


async def test_exact_matches(project_client, report_dataset):
    client, _ = project_client
    rows = (await client.get("/api/v1/reports/exact-matches")).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["seltext"] == "alpha"
    assert rows[0]["count"] == 2
    assert rows[0]["files"] == ["interview.txt"]


async def test_file_summary(project_client, report_dataset):
    client, _ = project_client
    rows = (await client.get("/api/v1/reports/file-summary")).json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "interview.txt"
    assert row["media_type"] == "text"
    assert row["codes_count"] == 2
    assert row["segments_count"] == 3
    assert row["cases"] == ["Report Case"]
    assert row["words"] == 3


async def test_coder_comparison(project_client, report_dataset):
    client, _ = project_client
    rows = (await client.get("/api/v1/reports/coder-comparison")).json()["rows"]
    default = next(r for r in rows if r["owner"] == "default")
    assert default["codings_count"] == 3
    assert default["files_count"] == 1


async def test_attributes_report(project_client, report_dataset):
    client, _ = project_client
    rows = (await client.get("/api/v1/reports/attributes")).json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "InterviewDate"
    assert row["value"] == "2024-01-01"
    assert row["entity_kind"] == "file"
    assert row["entity_name"] == "interview.txt"


async def test_reports_require_open_project(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/v1/reports/code-frequencies")
        assert res.status_code == 409
