"""Meta-analysis pipeline API tests (local-only v1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app

EBSCO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<records>
  <record>
    <title>Study A: an inoculation experiment</title>
    <abstract>Participants were randomly assigned to an inoculation or control condition.</abstract>
    <contributors>Doe, Jane ; Smith, John</contributors>
    <doi>10.1000/aaaa</doi>
    <publicationDate>2020-05-01</publicationDate>
    <source>Journal of Misinformation</source>
    <language>eng</language>
  </record>
  <record>
    <title>Study B: media literacy training</title>
    <abstract>No abstract here.</abstract>
    <contributors>Ross, Pat</contributors>
    <doi>10.1000/bbbb</doi>
    <publicationDate>2021-03-15</publicationDate>
    <source>Media Studies</source>
    <language>eng</language>
  </record>
</records>
"""


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _open_project(client: AsyncClient, tmp_path: Path, name: str) -> None:
    res = await client.post(
        "/api/v1/projects",
        json={"project_path": str(tmp_path / name), "codername": "meta-tester"},
    )
    assert res.status_code == 200, res.text


async def test_meta_status_and_initial_state(client, tmp_path):
    await _open_project(client, tmp_path, "meta0.qda")
    res = await client.get("/api/v1/meta/status")
    assert res.status_code == 200
    body = res.json()
    assert body["hits"] == 0
    assert body["criteria"] == 0
    assert body["schemes"] == 0


async def test_import_hits_xml_dedupe_and_list(client, tmp_path):
    await _open_project(client, tmp_path, "meta1.qda")
    xml_path = tmp_path / "search.xml"
    xml_path.write_text(EBSCO_XML, encoding="utf-8")

    res = await client.post(
        "/api/v1/meta/hits/import",
        files={"file": ("search.xml", xml_path.read_bytes(), "text/xml")},
        data={"search_run": "run-a"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 2
    assert body["parsed"] == 2

    # Re-import dedupes on DOI.
    res = await client.post(
        "/api/v1/meta/hits/import",
        files={"file": ("search.xml", xml_path.read_bytes(), "text/xml")},
        data={"search_run": "run-a"},
    )
    assert res.json()["imported"] == 0
    assert res.json()["duplicates_skipped"] == 2

    res = await client.get("/api/v1/meta/hits", params={"search_run": "run-a"})
    assert res.status_code == 200
    body = res.json()
    hits = body["hits"]
    assert body["total"] == 2
    assert len(hits) == 2
    assert hits[0]["title"].startswith("Study A")
    assert hits[0]["eligible"] is False

    res = await client.get("/api/v1/meta/hits/search-runs")
    assert res.json() == ["run-a"]

    res = await client.get("/api/v1/meta/status")
    assert res.json()["hits"] == 2


async def test_criteria_replace_and_delete(client, tmp_path):
    await _open_project(client, tmp_path, "meta2.qda")
    res = await client.put(
        "/api/v1/meta/criteria",
        json=[
            {"position": 0, "key": "c1", "label": "Intervention", "prompt_text": "Targets misinformation?"},
            {"position": 1, "key": "c2", "label": "Control", "prompt_text": "Has a control group?"},
        ],
    )
    assert res.status_code == 200
    assert len(res.json()) == 2

    res = await client.get("/api/v1/meta/criteria")
    assert len(res.json()) == 2

    # Replace with a single custom criterion.
    res = await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "Custom", "prompt_text": "Is it relevant?"}],
    )
    assert res.status_code == 200
    replaced = res.json()
    assert len(replaced) == 1

    res = await client.delete(f"/api/v1/meta/criteria/{replaced[0]['id']}")
    assert res.status_code == 204


async def test_scheme_create_and_list(client, tmp_path):
    await _open_project(client, tmp_path, "meta3.qda")
    res = await client.post(
        "/api/v1/meta/schemes",
        json={
            "name": "inoculation",
            "label": "Inoculation",
            "prescreen_prompt": "pp",
            "coding_prompt": "cp",
            "codebook": {"groups": ["Sample"], "fields": [{"name": "Age_Mean"}]},
        },
    )
    assert res.status_code == 201, res.text

    res = await client.get("/api/v1/meta/schemes")
    schemes = res.json()
    assert [s["name"] for s in schemes] == ["inoculation"]
    assert schemes[0]["coding_prompt"] == "cp"
    assert schemes[0]["prescreen_prompt"] == "pp"

    # Duplicate names are rejected.
    res = await client.post("/api/v1/meta/schemes", json={"name": "inoculation"})
    assert res.status_code == 409


async def test_manual_screening_updates_eligibility(client, tmp_path):
    await _open_project(client, tmp_path, "meta4.qda")
    xml_path = tmp_path / "search.xml"
    xml_path.write_text(EBSCO_XML, encoding="utf-8")
    await client.post(
        "/api/v1/meta/hits/import",
        files={"file": ("search.xml", xml_path.read_bytes(), "text/xml")},
    )
    hits = (await client.get("/api/v1/meta/hits")).json()["hits"]
    hit_id = hits[0]["hit_id"]

    # All-yes verdicts -> included.
    res = await client.put(
        "/api/v1/meta/screening",
        json={
            "hit_id": hit_id,
            "run_id": "round1",
            "verdicts": {
                "criterion1": {"applies": "Yes", "certainty": "High"},
                "criterion2": {"applies": "Yes", "certainty": "Medium"},
                "criterion3": {"applies": "Yes", "certainty": "Low"},
            },
            "intervention_type": "inoculation",
            "rationale": "Meets criteria.",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "included"

    hits = (await client.get("/api/v1/meta/hits")).json()["hits"]
    first = next(h for h in hits if h["hit_id"] == hit_id)
    assert first["eligible"] is True

    screens = (await client.get("/api/v1/meta/screening", params={"hit_id": hit_id})).json()
    assert len(screens) == 1
    assert screens[0]["verdicts"]["criterion1"]["applies"] == "Yes"
    assert screens[0]["origin"] == "manual"

    # No verdict -> excluded.
    second_id = hits[1]["hit_id"]
    res = await client.put(
        "/api/v1/meta/screening",
        json={"hit_id": second_id, "run_id": "round1", "verdicts": {}},
    )
    assert res.json()["status"] == "excluded"


async def test_llm_screening_requires_ai(client, tmp_path):
    await _open_project(client, tmp_path, "meta5.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    res = await client.post("/api/v1/meta/screening/llm", json={})
    assert res.status_code == 422  # AI disabled in tests
    assert "AI is not enabled" in res.json()["detail"]


async def test_llm_screening_requires_criteria(client, tmp_path):
    await _open_project(client, tmp_path, "meta6.qda")
    res = await client.post("/api/v1/meta/screening/llm", json={})
    assert res.status_code == 422
    assert "criteria" in res.json()["detail"]


async def test_downloads_and_documents_empty_then_assign(client, tmp_path):
    await _open_project(client, tmp_path, "meta7.qda")
    res = await client.get("/api/v1/meta/documents")
    assert res.json() == []

    # Run with nothing eligible: job completes with zeros.
    res = await client.post("/api/v1/meta/downloads/run", json={"hit_ids": []})
    assert res.status_code == 200, res.text
    job_id = res.json()["job_id"]

    import asyncio

    for _ in range(50):
        job = (await client.get(f"/api/v1/meta/jobs/{job_id}")).json()
        if job["state"] in ("done", "error", "cancelled"):
            break
        await asyncio.sleep(0.05)
    assert job["state"] == "done"
    assert job["result"]["total"] == 0
    await client.delete(f"/api/v1/meta/jobs/{job_id}")


async def test_batch_pdf_assign_matches_by_doi(client, tmp_path):
    await _open_project(client, tmp_path, "meta7b.qda")
    xml_path = tmp_path / "search.xml"
    xml_path.write_text(EBSCO_XML, encoding="utf-8")
    await client.post(
        "/api/v1/meta/hits/import",
        files={"file": ("search.xml", xml_path.read_bytes(), "text/xml")},
    )
    hits = (await client.get("/api/v1/meta/hits")).json()["hits"]
    target = next(h for h in hits if h["doi"] == "10.1000/aaaa")

    res = await client.post(
        "/api/v1/meta/downloads/assign-batch",
        files=[
            ("files", ("10.1000_aaaa.pdf", b"%PDF-1.4 test", "application/pdf")),
            ("files", ("totally-unrelated-file.pdf", b"%PDF-1.4 test", "application/pdf")),
        ],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [a["hit_id"] for a in body["assigned"]] == [target["hit_id"]]
    assert body["unmatched"] == ["totally-unrelated-file.pdf"]

    docs = (await client.get("/api/v1/meta/documents")).json()
    assert next(d for d in docs if d["hit_id"] == target["hit_id"])["source_id"] is not None


async def test_extraction_export_empty_and_publish_422(client, tmp_path):
    await _open_project(client, tmp_path, "meta8.qda")
    res = await client.get("/api/v1/meta/extract/export", params={"fmt": "csv"})
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith("attachment")

    res = await client.get("/api/v1/meta/extract/export", params={"fmt": "xlsx"})
    assert res.status_code == 200
    assert res.content.startswith(b"PK")  # zip container

    res = await client.post(
        "/api/v1/meta/extract/publish",
        json={"hit_id": 1, "to_cases": True, "to_codes": True},
    )
    assert res.status_code == 422


async def test_job_control(client, tmp_path):
    await _open_project(client, tmp_path, "meta9.qda")
    res = await client.get("/api/v1/meta/jobs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    res = await client.get("/api/v1/meta/jobs/nope")
    assert res.status_code == 404

    # Create a job, then cancel + delete it.
    res = await client.post("/api/v1/meta/downloads/run", json={"hit_ids": []})
    job_id = res.json()["job_id"]
    res = await client.post(f"/api/v1/meta/jobs/{job_id}/control", params={"action": "cancel"})
    assert res.status_code == 200
    res = await client.delete(f"/api/v1/meta/jobs/{job_id}")
    assert res.status_code == 204
    res = await client.get(f"/api/v1/meta/jobs/{job_id}")
    assert res.status_code == 404


async def test_delete_hit_cascades(client, tmp_path):
    await _open_project(client, tmp_path, "meta10.qda")
    xml_path = tmp_path / "search.xml"
    xml_path.write_text(EBSCO_XML, encoding="utf-8")
    await client.post(
        "/api/v1/meta/hits/import",
        files={"file": ("search.xml", xml_path.read_bytes(), "text/xml")},
    )
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    await client.put(
        "/api/v1/meta/screening",
        json={"hit_id": hit_id, "verdicts": {"criterion1": {"applies": "Yes", "certainty": "High"}}},
    )

    res = await client.delete(f"/api/v1/meta/hits/{hit_id}")
    assert res.status_code == 204
    assert (await client.get("/api/v1/meta/screening", params={"hit_id": hit_id})).json() == []
    res = await client.delete(f"/api/v1/meta/hits/{hit_id}")
    assert res.status_code == 404

async def test_import_hits_xlsx(client, tmp_path):
    await _open_project(client, tmp_path, "meta_xlsx.qda")
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Title", "Abstract", "Authors", "DOI", "Publication Year"])
    ws.append(["Study A", "abs a", "Doe, Jane", "10.1000/xlsx-a", "2020"])
    ws.append(["Study B", "abs b", "Roe, Sam", "10.1000/xlsx-b", "2021"])
    path = tmp_path / "hits.xlsx"
    wb.save(path)

    res = await client.post(
        "/api/v1/meta/hits/import",
        files={
            "file": (
                "hits.xlsx",
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"search_run": "xl"},
    )
    print("XLSX IMPORT STATUS", res.status_code, res.text)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 2, body
    hits = (await client.get("/api/v1/meta/hits")).json()["hits"]
    assert len(hits) == 2
