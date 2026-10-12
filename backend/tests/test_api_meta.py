"""Meta-analysis pipeline API tests (local-only v1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app, service
from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services.meta_extract import derive_dv_metrics
from qualcoder_api.services.meta_roles import role_map
from qualcoder_api.services.meta_scheme import normalise_codebook, study_fields

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


async def _import_two_hits(client: AsyncClient, tmp_path: Path) -> None:
    xml_path = tmp_path / "search.xml"
    xml_path.write_text(EBSCO_XML, encoding="utf-8")
    res = await client.post(
        "/api/v1/meta/hits/import",
        files={"file": ("search.xml", xml_path.read_bytes(), "text/xml")},
    )
    assert res.status_code == 200, res.text


async def test_criteria_v2_gating_and_classify(client, tmp_path):
    await _open_project(client, tmp_path, "meta_v2.qda")
    criteria = [
        {"position": 0, "key": "c1", "label": "Intervention", "prompt_text": "p"},
        {
            "position": 1,
            "key": "c2",
            "label": "Design",
            "prompt_text": "p",
            "kind": "classify",
            "options": ["rct", "quasi"],
            "pass_values": ["rct", "quasi"],
            "exclude_reason": "Not a controlled design",
        },
        {
            "position": 2,
            "key": "c3",
            "label": "Note",
            "prompt_text": "p",
            "kind": "verdict",
            "gating": 0,
            "exclude_reason": "informational",
        },
    ]
    res = await client.put("/api/v1/meta/criteria", json=criteria)
    assert res.status_code == 200, res.text

    got = (await client.get("/api/v1/meta/criteria")).json()
    assert got[1]["kind"] == "classify"
    assert got[1]["options"] == ["rct", "quasi"]
    assert got[1]["pass_values"] == ["rct", "quasi"]
    assert got[1]["exclude_reason"] == "Not a controlled design"
    assert got[2]["gating"] == 0

    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]

    # classify value passes case-insensitively; the informational criterion
    # fails but must not block inclusion.
    res = await client.put(
        "/api/v1/meta/screening",
        json={
            "hit_id": hit_id,
            "run_id": "r1",
            "verdicts": {
                "c1": {"applies": "Yes"},
                "c2": {"applies": "RCT"},
                "c3": {"applies": "No"},
            },
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "included"
    assert body["eligible"] is True
    assert body["failing"] == []

    # A failing classify criterion blocks; the reason derives from exclude_reason.
    res = await client.put(
        "/api/v1/meta/screening",
        json={
            "hit_id": hit_id,
            "run_id": "r1",
            "verdicts": {
                "c1": {"applies": "Yes"},
                "c2": {"applies": "observational"},
                "c3": {"applies": "No"},
            },
        },
    )
    body = res.json()
    assert body["status"] == "excluded"
    assert body["eligible"] is False
    assert body["failing"] == ["c2"]
    assert body["reason"] == "Not a controlled design"

    screens = (await client.get("/api/v1/meta/screening", params={"hit_id": hit_id})).json()
    assert screens[0]["reason"] == "Not a controlled design"
    assert screens[0]["stage"] == "abstract"


async def test_screening_stage_filter_and_extractions_owner(client, tmp_path):
    await _open_project(client, tmp_path, "meta_stage.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]

    res = await client.put(
        "/api/v1/meta/screening",
        json={
            "hit_id": hit_id,
            "run_id": "r1",
            "stage": "fulltext",
            "reason": "custom reason",
            "verdicts": {"c1": {"applies": "Yes"}},
        },
    )
    assert res.status_code == 200, res.text

    fulltext = (
        await client.get("/api/v1/meta/screening", params={"stage": "fulltext"})
    ).json()
    assert len(fulltext) == 1
    assert fulltext[0]["reason"] == "custom reason"
    assert (
        await client.get("/api/v1/meta/screening", params={"stage": "abstract"})
    ).json() == []

    res = await client.get("/api/v1/meta/extractions", params={"owner": "nobody"})
    assert res.status_code == 200
    assert res.json() == []


# ── analysis / agreement / reporting endpoints ───────────────────────────

META_CODEBOOK = {
    "version": 2,
    "category": "Meta",
    "groups": [{"name": "Study", "label": "Study"}],
    "fields": [
        {"name": "sid", "label": "Study id", "role": "study_id"},
        {
            "name": "design",
            "label": "Design",
            "role": "design",
            "editor": "select",
            "options": ["rct", "quasi"],
        },
    ],
    "metrics": {
        "enabled": True,
        "group": "metrics",
        "label": "Effect sizes",
        "fields": [
            {"name": "dv", "label": "Outcome", "role": "dv_name"},
            {
                "name": "domain",
                "label": "Domain",
                "role": "dv_domain",
                "editor": "select",
                "options": ["a", "b"],
            },
            {"name": "m1", "role": "m1"},
            {"name": "sd1", "role": "sd1"},
            {"name": "n1", "role": "n1"},
            {"name": "m2", "role": "m2"},
            {"name": "sd2", "role": "sd2"},
            {"name": "n2", "role": "n2"},
            {"name": "primary", "role": "eligible_primary", "type": "boolean"},
        ],
    },
    "effect_families": ["descriptives"],
}


async def _create_scheme(client: AsyncClient, name: str = "meta") -> int:
    res = await client.post(
        "/api/v1/meta/schemes", json={"name": name, "codebook": META_CODEBOOK}
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _records(sid: str, dv: str, domain: str, m1: float, m2: float) -> list[dict]:
    return [
        {
            "study": {"sid": sid, "design": "rct"},
            "metrics": [
                {
                    "dv": dv,
                    "domain": domain,
                    "m1": m1,
                    "sd1": 1.0,
                    "n1": 20,
                    "m2": m2,
                    "sd2": 1.0,
                    "n2": 20,
                    "primary": True,
                }
            ],
        }
    ]


async def _seed_extraction(
    hit_id: int, owner: str, records: list[dict], scheme: str = "meta"
) -> None:
    book = normalise_codebook(META_CODEBOOK)
    dv_metrics = derive_dv_metrics(records, role_map(study_fields(book)))
    async with service.session_factory() as session:
        repo = MetaRepository(session)
        await repo.upsert_extraction(
            hit_id=hit_id,
            owner=owner,
            scheme=scheme,
            study_vars={"records": records},
            dv_metrics=dv_metrics,
            status="extracted",
        )


async def _seed_screening(hit_id: int, owner: str, verdicts: dict) -> None:
    async with service.session_factory() as session:
        repo = MetaRepository(session)
        await repo.upsert_screening(
            hit_id=hit_id, owner=owner, run_id="r1", verdicts=verdicts
        )


async def test_screening_agreement_conflicts_and_resolve(client, tmp_path):
    await _open_project(client, tmp_path, "meta_agr.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    await _seed_screening(hit_id, "anna", {"c1": {"applies": "Yes"}})
    await _seed_screening(hit_id, "bob", {"c1": {"applies": "No"}})

    res = await client.get("/api/v1/meta/screening/agreement")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overall"]["ac1"] is not None
    assert {f["name"] for f in body["fields"]} == {"c1"}

    res = await client.get("/api/v1/meta/screening/conflicts")
    assert res.status_code == 200, res.text
    conflicts = res.json()
    assert conflicts["total"] == 1
    assert conflicts["rows"][0]["field"] == "c1"

    res = await client.post(
        "/api/v1/meta/screening/resolve",
        json={"hit_id": hit_id, "criterion_key": "c1", "value": "No", "master": "judge"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["value"] == "No"

    screens = (
        await client.get("/api/v1/meta/screening", params={"hit_id": hit_id})
    ).json()
    judge = next(s for s in screens if s["owner"] == "judge")
    assert judge["verdicts"]["c1"]["applies"] == "No"

    res = await client.post(
        "/api/v1/meta/screening/resolve",
        json={"hit_id": 99999, "criterion_key": "c1", "value": "No", "master": "judge"},
    )
    assert res.status_code == 422


async def test_extraction_agreement_conflicts_and_resolve(client, tmp_path):
    await _open_project(client, tmp_path, "meta_agr2.qda")
    await _create_scheme(client)
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]

    records_a = [{"study": {"sid": "S1", "design": "rct"}, "metrics": [
        {"dv": "X", "domain": "a"}, {"dv": "Y", "domain": "b"}]}]
    records_b = [{"study": {"sid": "S1", "design": "rct"}, "metrics": [
        {"dv": "Y", "domain": "b"}, {"dv": "X", "domain": "a"}]}]
    await _seed_extraction(hit_id, "anna", records_a)
    await _seed_extraction(hit_id, "bob", records_b)

    res = await client.get("/api/v1/meta/extraction/agreement", params={"scheme": "meta"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overall"]["ac1"] is not None

    # Reordered metrics do not create false conflicts.
    conflicts = (
        await client.get(
            "/api/v1/meta/extraction/conflicts", params={"scheme": "meta"}
        )
    ).json()
    assert conflicts["total"] == 0

    records_c = [{"study": {"sid": "S1", "design": "rct"}, "metrics": [
        {"dv": "Y", "domain": "a"}, {"dv": "X", "domain": "a"}]}]
    await _seed_extraction(hit_id, "cara", records_c)
    conflicts = (
        await client.get(
            "/api/v1/meta/extraction/conflicts", params={"scheme": "meta"}
        )
    ).json()
    assert conflicts["total"] == 1
    assert conflicts["rows"][0]["case"] == [hit_id, 0, "Y"]

    res = await client.post(
        "/api/v1/meta/extraction/resolve",
        json={
            "hit_id": hit_id,
            "field_name": "domain",
            "metric_key": "Y",
            "value": "b",
            "master": "judge",
            "scheme": "meta",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["value"] == "b"

    open_conflicts = (
        await client.get(
            "/api/v1/meta/extraction/conflicts",
            params={"scheme": "meta", "master": "judge", "status": "open"},
        )
    ).json()
    assert open_conflicts["total"] == 0
    settled = (
        await client.get(
            "/api/v1/meta/extraction/conflicts",
            params={"scheme": "meta", "master": "judge", "status": "settled"},
        )
    ).json()
    assert settled["total"] == 1


async def test_analysis_and_reporting_endpoints(client, tmp_path):
    await _open_project(client, tmp_path, "meta_analysis.qda")
    await _create_scheme(client)
    await _seed_extraction(1, "anna", _records("S1", "X", "a", 5.0, 4.0))
    await _seed_extraction(2, "anna", _records("S2", "Y", "b", 4.5, 4.0))
    await _seed_extraction(3, "anna", _records("S3", "Z", "b", 4.2, 4.0))

    res = await client.post("/api/v1/meta/analysis/pooled", json={"scheme": "meta"})
    assert res.status_code == 200, res.text
    pooled = res.json()
    assert pooled["k"] == 3
    assert pooled["estimate"] is not None
    assert pooled["k_total"] == 3

    res = await client.post(
        "/api/v1/meta/analysis/moderator",
        json={"scheme": "meta", "role": "domain", "terms": ["domain"]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["k"] == 3

    res = await client.post(
        "/api/v1/meta/analysis/subgroup", json={"scheme": "meta", "key": "domain"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["k_groups"] == 2

    res = await client.post("/api/v1/meta/analysis/egger", json={"scheme": "meta"})
    assert res.status_code == 200, res.text
    assert res.json()["k"] == 3

    res = await client.post(
        "/api/v1/meta/analysis/leave-one-out", json={"scheme": "meta"}
    )
    assert res.status_code == 200, res.text
    assert len(res.json()["rows"]) == 3

    res = await client.get("/api/v1/meta/analysis/forest", params={"scheme": "meta"})
    assert res.status_code == 200, res.text
    assert len(res.json()["rows"]) == 3

    res = await client.get("/api/v1/meta/prisma")
    assert res.status_code == 200, res.text
    prisma = res.json()
    assert prisma["inclusion"]["studies"] == 3
    assert prisma["inclusion"]["included"] == 3

    res = await client.get("/api/v1/meta/summary", params={"scheme": "meta"})
    assert res.status_code == 200, res.text
    summary = res.json()
    assert summary["n_studies"] == 3
    assert any(f["name"] == "domain" for f in summary["fields"])

    res = await client.post("/api/v1/meta/report", json={"scheme": "meta", "format": "md"})
    assert res.status_code == 200, res.text
    assert res.headers["content-disposition"].endswith('.md"')
    assert res.content.decode("utf-8").startswith("# Methods and Results")

    res = await client.post(
        "/api/v1/meta/report", json={"scheme": "meta", "format": "docx"}
    )
    assert res.status_code == 200, res.text
    assert res.content.startswith(b"PK")

    res = await client.post("/api/v1/meta/report", json={"scheme": "meta", "format": "pdf"})
    assert res.status_code == 422


async def test_analysis_moderator_interactions(client, tmp_path):
    await _open_project(client, tmp_path, "meta_interaction.qda")
    await _create_scheme(client)
    seeds = [
        ("S1", "X", "a", 1.0),
        ("S2", "X", "a", 2.0),
        ("S3", "X", "a", 3.0),
        ("S4", "Y", "b", 4.0),
        ("S5", "Y", "b", 5.0),
        ("S6", "Y", "b", 6.0),
    ]
    for hit_id, (sid, dv, domain, m1) in enumerate(seeds, start=1):
        await _seed_extraction(hit_id, "anna", _records(sid, dv, domain, m1, 4.0))

    res = await client.post(
        "/api/v1/meta/analysis/moderator",
        json={
            "scheme": "meta",
            "field": "m1",
            "terms": ["m1", "domain"],
            "interactions": [["m1", "domain"]],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["field"] == "m1"
    assert body["interactions"] == [["m1", "domain"]]
    terms = [c["term"] for c in body["coefficients"]]
    # ``a`` is the reference domain, so the numeric x dummy product is m1 x b.
    assert "m1 * domain:b" in terms


async def test_publication_bias_bayes_and_figure_endpoints(client, tmp_path):
    await _open_project(client, tmp_path, "meta_pb_bayes.qda")
    await _create_scheme(client)
    await _seed_extraction(1, "anna", _records("S1", "X", "a", 5.0, 4.0))
    await _seed_extraction(2, "anna", _records("S2", "Y", "b", 4.5, 4.0))
    await _seed_extraction(3, "anna", _records("S3", "Z", "b", 4.2, 4.0))

    res = await client.post(
        "/api/v1/meta/analysis/publication-bias", json={"scheme": "meta"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"k", "k_total", "egger", "pet_peese", "trim_and_fill", "p_curve"}
    assert set(body["egger"]) == {
        "intercept", "se", "t", "p", "slope", "slope_se", "slope_p"
    }
    assert set(body["pet_peese"]) == {"pet", "peese", "recommended"}
    assert set(body["pet_peese"]["pet"]) == {"intercept", "se", "t", "p"}
    assert set(body["trim_and_fill"]) == {
        "k0", "side", "estimate", "se", "ci_low", "ci_high"
    }
    assert set(body["p_curve"]) == {
        "n_significant", "n_p_lt_025", "p_half", "evidential", "note"
    }
    assert body["k"] == 3 and body["k_total"] == 3

    res = await client.post(
        "/api/v1/meta/analysis/bayes", json={"scheme": "meta", "mu_sd": 5.0}
    )
    assert res.status_code == 200, res.text
    bayes = res.json()
    assert set(bayes) == {
        "k", "k_total", "mu", "tau", "bf10", "bf01_tau0", "prior", "posterior",
        "sensitivity",
    }
    assert bayes["prior"]["mu_sd"] == 5.0
    assert len(bayes["sensitivity"]) == 20
    assert bayes["mu"]["ci_low"] <= bayes["mu"]["mean"] <= bayes["mu"]["ci_high"]
    assert bayes["bf10"] is not None and bayes["bf10"] > 0

    res = await client.get("/api/v1/meta/prisma.png")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG")

    res = await client.get("/api/v1/meta/analysis/forest.png", params={"scheme": "meta"})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG")

    res = await client.post(
        "/api/v1/meta/report", json={"scheme": "meta", "format": "pptx"}
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-disposition"].endswith('meta_report.pptx"')
    assert res.content.startswith(b"PK")


async def test_multiverse_audit_and_extra_figures(client, tmp_path):
    await _open_project(client, tmp_path, "meta_mv_audit.qda")
    await _create_scheme(client)
    await _seed_extraction(1, "anna", _records("S1", "X", "a", 5.0, 4.0))
    await _seed_extraction(2, "anna", _records("S2", "Y", "b", 4.5, 4.0))
    await _seed_extraction(3, "anna", _records("S3", "Z", "b", 4.2, 4.0))

    res = await client.post("/api/v1/meta/analysis/multiverse", json={"scheme": "meta"})
    assert res.status_code == 200, res.text
    multiverse = res.json()
    assert set(multiverse) == {"k_total", "n_specs", "dimensions", "specs", "summary"}
    assert multiverse["n_specs"] > 0
    assert len(multiverse["specs"]) == multiverse["n_specs"]
    assert {d["name"] for d in multiverse["dimensions"]} == {
        "primary", "estimator", "domain", "exclude_outliers"
    }
    assert multiverse["summary"]["n_ok"] == multiverse["summary"]["n_specs"]

    capped = await client.post(
        "/api/v1/meta/analysis/multiverse", json={"scheme": "meta", "max_specs": 4}
    )
    assert capped.status_code == 200, capped.text
    assert capped.json()["n_specs"] == 4

    for path in ("funnel.png", "spec-curve.png", "bayes.png"):
        res = await client.get(f"/api/v1/meta/analysis/{path}", params={"scheme": "meta"})
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "image/png"
        assert res.content.startswith(b"\x89PNG")

    res = await client.get("/api/v1/meta/audit", params={"scheme": "meta"})
    assert res.status_code == 200, res.text
    audit = res.json()
    assert set(audit) == {"n_extractions", "n_records", "n_metrics", "fields", "issues"}
    assert audit["n_extractions"] == 3
    assert audit["n_metrics"] == 3
    assert any(field["name"] == "dv" for field in audit["fields"])
    assert any(field["role"] == "dv_name" for field in audit["fields"])


async def test_scheme_clone_export_import(client, tmp_path):
    await _open_project(client, tmp_path, "meta_scheme_io.qda")
    scheme_id = await _create_scheme(client, "original")

    res = await client.post(
        f"/api/v1/meta/schemes/{scheme_id}/clone", json={"name": "copy"}
    )
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "copy"

    res = await client.post(
        f"/api/v1/meta/schemes/{scheme_id}/clone", json={"name": "copy"}
    )
    assert res.status_code == 409

    res = await client.get(f"/api/v1/meta/schemes/{scheme_id}/export")
    assert res.status_code == 200, res.text
    assert res.headers["content-disposition"].startswith("attachment")
    payload = res.json()
    assert payload["name"] == "original"
    assert payload["codebook"]["category"] == "Meta"

    res = await client.post(
        "/api/v1/meta/schemes/import",
        json={"name": "imported", "codebook": META_CODEBOOK},
    )
    assert res.status_code == 201, res.text
    assert res.json()["overwritten"] is False

    res = await client.post(
        "/api/v1/meta/schemes/import",
        json={"name": "imported", "codebook": META_CODEBOOK},
    )
    assert res.status_code == 409

    res = await client.post(
        "/api/v1/meta/schemes/import",
        json={"name": "imported", "label": "Replaced", "codebook": META_CODEBOOK, "overwrite": True},
    )
    assert res.status_code == 201, res.text
    assert res.json()["overwritten"] is True


async def test_manual_extraction_save(client, tmp_path):
    """The scheme-driven editor saves canonical records via PUT /meta/extractions."""
    await _open_project(client, tmp_path, "meta_save_ext.qda")
    await _create_scheme(client, "meta")
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    records = _records("StudyA", "accuracy", "credibility", 0.8, 0.5)

    res = await client.put(
        "/api/v1/meta/extractions",
        json={
            "hit_id": hit_id,
            "owner": "anna",
            "scheme": "meta",
            "study_vars": {"records": records},
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["owner"] == "anna"
    saved = body["extraction"]
    assert saved["status"] == "extracted"
    assert saved["study_vars"]["records"][0]["study"]["sid"] == "StudyA"
    flat = saved["dv_metrics"]
    assert flat and flat[0]["_record"] == 0 and flat[0]["sid"] == "StudyA"
    assert flat[0]["m1"] == 0.8

    # A second coder holds their own row (unique hit+owner).
    res = await client.put(
        "/api/v1/meta/extractions",
        json={
            "hit_id": hit_id,
            "owner": "bob",
            "scheme": "meta",
            "study_vars": {"records": records},
        },
    )
    assert res.status_code == 200, res.text
    res = await client.get("/api/v1/meta/extractions")
    assert len(res.json()) == 2
    res = await client.get("/api/v1/meta/extractions", params={"owner": "anna"})
    got = res.json()
    assert len(got) == 1 and got[0]["owner"] == "anna"

    # Unknown hit is a 404.
    res = await client.put(
        "/api/v1/meta/extractions",
        json={"hit_id": 999999, "study_vars": {"records": records}},
    )
    assert res.status_code == 404


# ── regression tests: screening stage, owner pooling, scheme scoping ──────


async def test_screening_stages_do_not_overwrite(client, tmp_path):
    """Abstract and full-text verdicts for the same hit/run coexist."""
    await _open_project(client, tmp_path, "meta_stage_coexist.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]

    await client.put(
        "/api/v1/meta/screening",
        json={
            "hit_id": hit_id,
            "run_id": "r1",
            "stage": "abstract",
            "verdicts": {"c1": {"applies": "Yes"}},
        },
    )
    res = await client.put(
        "/api/v1/meta/screening",
        json={
            "hit_id": hit_id,
            "run_id": "r1",
            "stage": "fulltext",
            "reason": "failed full text",
            "verdicts": {"c1": {"applies": "No"}},
        },
    )
    assert res.status_code == 200, res.text

    rows = (
        await client.get("/api/v1/meta/screening", params={"hit_id": hit_id})
    ).json()
    by_stage = {row["stage"]: row for row in rows}
    assert set(by_stage) == {"abstract", "fulltext"}
    assert by_stage["abstract"]["verdicts"]["c1"]["applies"] == "Yes"
    assert by_stage["fulltext"]["verdicts"]["c1"]["applies"] == "No"


async def test_analysis_pools_one_extraction_per_hit(client, tmp_path):
    """Two coders' extractions of the same hit must not double-count."""
    await _open_project(client, tmp_path, "meta_one_per_hit.qda")
    await _create_scheme(client)
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    records = _records("S1", "X", "a", 5.0, 4.0)
    await _seed_extraction(hit_id, "anna", records)
    await _seed_extraction(hit_id, "bob", records)

    pooled = (
        await client.post("/api/v1/meta/analysis/pooled", json={"scheme": "meta"})
    ).json()
    assert pooled["k"] == 1
    assert pooled["k_total"] == 1


def _codebook_named(names: dict[str, str]) -> dict:
    return {
        "version": 2,
        "groups": [{"name": "Study", "label": "Study"}],
        "fields": [{"name": names["sid"], "role": "study_id"}],
        "metrics": {
            "enabled": True,
            "group": "metrics",
            "fields": [
                {"name": names["dv"], "role": "dv_name"},
                {"name": names["m1"], "role": "m1"},
                {"name": names["sd1"], "role": "sd1"},
                {"name": names["n1"], "role": "n1"},
                {"name": names["m2"], "role": "m2"},
                {"name": names["sd2"], "role": "sd2"},
                {"name": names["n2"], "role": "n2"},
            ],
        },
        "effect_families": ["descriptives"],
    }


_ALPHA_NAMES = {
    "sid": "sid_a", "dv": "dv_a", "m1": "m1a", "sd1": "sd1a",
    "n1": "n1a", "m2": "m2a", "sd2": "sd2a", "n2": "n2a",
}
_BETA_NAMES = {
    "sid": "sid_b", "dv": "dv_b", "m1": "m1b", "sd1": "sd1b",
    "n1": "n1b", "m2": "m2b", "sd2": "sd2b", "n2": "n2b",
}


def _named_records(sid: str, names: dict[str, str], m1: float, m2: float) -> list[dict]:
    return [
        {
            "study": {names["sid"]: sid},
            "metrics": [
                {
                    names["dv"]: "outcome",
                    names["m1"]: m1,
                    names["sd1"]: 1.0,
                    names["n1"]: 20,
                    names["m2"]: m2,
                    names["sd2"]: 1.0,
                    names["n2"]: 20,
                }
            ],
        }
    ]


async def test_scheme_free_analysis_uses_each_codebook_and_dedupes_hits(client, tmp_path):
    """With no scheme, one extraction per HIT wins and each extraction is
    derived under its own scheme's codebook."""
    await _open_project(client, tmp_path, "meta_scheme_free.qda")
    await client.post(
        "/api/v1/meta/schemes",
        json={"name": "alpha", "codebook": _codebook_named(_ALPHA_NAMES)},
    )
    await client.post(
        "/api/v1/meta/schemes",
        json={"name": "beta", "codebook": _codebook_named(_BETA_NAMES)},
    )
    await _import_two_hits(client, tmp_path)
    hit_a = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    hit_b = (await client.get("/api/v1/meta/hits")).json()["hits"][1]["hit_id"]

    await _seed_extraction(
        hit_a, "anna", _named_records("S1", _ALPHA_NAMES, 5.0, 4.0), scheme="alpha"
    )
    # hit_b is coded under BOTH schemes: the later (beta) extraction must win,
    # and it must be derived with beta's field names.
    await _seed_extraction(
        hit_b, "anna", _named_records("S2", _ALPHA_NAMES, 4.5, 4.0), scheme="alpha"
    )
    await _seed_extraction(
        hit_b, "anna", _named_records("S2", _BETA_NAMES, 4.2, 4.0), scheme="beta"
    )

    pooled = (await client.post("/api/v1/meta/analysis/pooled", json={})).json()
    # 2 hits: not 3 (hit_b not double-counted) and not 1 (beta derived with its
    # own codebook rather than alpha's).
    assert pooled["k"] == 2, pooled
    assert pooled["n_studies"] == 2

    # Field-name moderation on an arbitrary scheme variable.
    moderator = (
        await client.post(
            "/api/v1/meta/analysis/moderator",
            json={"field": "m1b", "terms": ["m1b"]},
        )
    ).json()
    assert moderator["field"] == "m1b"
    assert moderator["role"] == "m1b"

    subgroup = (
        await client.post("/api/v1/meta/analysis/subgroup", json={"field": "m1b"})
    ).json()
    assert subgroup["key"] == "m1b"
    assert subgroup["field"] == "m1b"


async def test_moderators_catalogue_excludes_hidden_and_merges_schemes(client, tmp_path):
    await _open_project(client, tmp_path, "meta_moderators.qda")
    codebook_a = {
        "version": 2,
        "groups": [{"name": "Study", "label": "Study"}],
        "fields": [
            {
                "name": "design",
                "label": "Design",
                "role": "design",
                "editor": "select",
                "options": ["rct", "quasi"],
            },
            {"name": "hidden_field", "label": "Hidden", "moderator": False},
            {"name": "_internal", "label": "Internal"},
        ],
        "metrics": {
            "enabled": True,
            "group": "metrics",
            "fields": [{"name": "domain", "label": "Domain", "role": "dv_domain"}],
        },
        "effect_families": ["descriptives"],
    }
    codebook_b = {
        "version": 2,
        "groups": [{"name": "Study", "label": "Study"}],
        "fields": [{"name": "design", "label": "Design", "role": "design"}],
        "metrics": {"enabled": True, "group": "metrics", "fields": []},
    }
    assert (
        await client.post(
            "/api/v1/meta/schemes", json={"name": "alpha", "codebook": codebook_a}
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/v1/meta/schemes", json={"name": "beta", "codebook": codebook_b}
        )
    ).status_code == 201

    res = await client.get("/api/v1/meta/moderators")
    assert res.status_code == 200, res.text
    body = res.json()
    names = [m["name"] for m in body]
    assert "hidden_field" not in names
    assert "_internal" not in names
    # Sorted by group then label: metric group "metrics" precedes "Study".
    assert names == ["domain", "design"]

    design = next(m for m in body if m["name"] == "design")
    assert design["kind"] == "study"
    assert design["role"] == "design"
    assert design["group"] == "Study"
    assert design["editor"] == "select"
    assert design["schemes"] == ["alpha", "beta"]
    domain = next(m for m in body if m["name"] == "domain")
    assert domain["kind"] == "metric"
    assert domain["role"] == "dv_domain"
    assert domain["schemes"] == ["alpha"]

    scoped = (
        await client.get("/api/v1/meta/moderators", params={"scheme": "beta"})
    ).json()
    assert [m["name"] for m in scoped] == ["design"]


async def test_analysis_model_branch_and_domain_filter(client, tmp_path):
    await _open_project(client, tmp_path, "meta_model_domain.qda")
    await _create_scheme(client)
    await _seed_extraction(1, "anna", _records("S1", "X", "a", 5.0, 4.0))
    await _seed_extraction(2, "anna", _records("S2", "Y", "b", 4.5, 4.0))
    await _seed_extraction(3, "anna", _records("S3", "Z", "b", 4.2, 4.0))

    fixed = (
        await client.post(
            "/api/v1/meta/analysis/pooled", json={"scheme": "meta", "model": "fixed"}
        )
    ).json()
    assert fixed["model"] == "fixed" and fixed["k"] == 3

    two_level = (
        await client.post(
            "/api/v1/meta/analysis/pooled",
            json={"scheme": "meta", "model": "two_level"},
        )
    ).json()
    assert two_level["model"] == "two_level"
    assert two_level["k"] == 3
    assert "tau2_within" in two_level and "tau2_between" in two_level

    filtered = (
        await client.post(
            "/api/v1/meta/analysis/pooled", json={"scheme": "meta", "domain": "b"}
        )
    ).json()
    assert filtered["k_total"] == 2 and filtered["k"] == 2


async def test_extraction_upsert_is_scheme_scoped(client, tmp_path):
    await _open_project(client, tmp_path, "meta_scheme_scope.qda")
    await _create_scheme(client, "meta")
    alt_id = await _create_scheme(client, "alt")
    unused_id = await _create_scheme(client, "unused")
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    records = _records("S1", "X", "a", 5.0, 4.0)

    for scheme in ("meta", "alt"):
        res = await client.put(
            "/api/v1/meta/extractions",
            json={
                "hit_id": hit_id,
                "owner": "anna",
                "scheme": scheme,
                "study_vars": {"records": records},
            },
        )
        assert res.status_code == 200, res.text

    rows = (await client.get("/api/v1/meta/extractions")).json()
    anna_rows = [
        row for row in rows if row["owner"] == "anna" and row["hit_id"] == hit_id
    ]
    assert {row["scheme"] for row in anna_rows} == {"meta", "alt"}

    only_alt = (
        await client.get("/api/v1/meta/extractions", params={"scheme": "alt"})
    ).json()
    assert [row["scheme"] for row in only_alt] == ["alt"]

    # A referenced scheme cannot be deleted.
    assert (await client.delete(f"/api/v1/meta/schemes/{alt_id}")).status_code == 409
    # The unreferenced one still can.
    assert (await client.delete(f"/api/v1/meta/schemes/{unused_id}")).status_code == 204


async def test_conflict_rows_carry_resolvable_ids(client, tmp_path):
    await _open_project(client, tmp_path, "meta_conflict_ids.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    await _seed_screening(hit_id, "anna", {"c1": {"applies": "Yes"}})
    await _seed_screening(hit_id, "bob", {"c1": {"applies": "No"}})

    rows = (await client.get("/api/v1/meta/screening/conflicts")).json()["rows"]
    row = next(r for r in rows if r["field"] == "c1")
    assert row["key"] == f"screening:{hit_id}:c1"
    assert row["hit_id"] == hit_id
    assert row["criterion_key"] == "c1"
    assert row["field_name"] == "c1"
    assert row["values"] == {"anna": "Yes", "bob": "No"}
    assert row["settled"] is False

    await _create_scheme(client)
    records_a = [
        {"study": {"sid": "S1", "design": "rct"}, "metrics": [{"dv": "X", "domain": "a"}]}
    ]
    records_b = [
        {"study": {"sid": "S1", "design": "rct"}, "metrics": [{"dv": "X", "domain": "b"}]}
    ]
    await _seed_extraction(hit_id, "anna", records_a)
    await _seed_extraction(hit_id, "bob", records_b)
    rows = (
        await client.get("/api/v1/meta/extraction/conflicts", params={"scheme": "meta"})
    ).json()["rows"]
    metric_row = next(r for r in rows if r["field"] == "domain")
    assert metric_row["hit_id"] == hit_id
    assert metric_row["record_index"] == 0
    assert metric_row["metric_key"] == "X"
    assert metric_row["metric_index"] == 0
    assert metric_row["key"] == f"extraction:{hit_id}:0:X:domain"


async def test_screening_llm_excluded_list(client, tmp_path):
    await _open_project(client, tmp_path, "meta_llm_excluded.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    await _seed_screening(hit_id, "human", {"c1": {"applies": "Yes"}})
    async with service.session_factory() as session:
        repo = MetaRepository(session)
        await repo.upsert_screening(
            hit_id=hit_id,
            owner="model",
            run_id="r1",
            verdicts={"c1": {"applies": "No"}},
            origin="llm",
            stage="abstract",
            reason="model judged it irrelevant",
        )

    body = (await client.get("/api/v1/meta/screening/agreement")).json()
    entry = next(e for e in body["llm_excluded"] if e["hit_id"] == hit_id)
    assert entry["included_by"] == ["human"]
    assert entry["excluded_by"] == ["model"]
    assert entry["llm_reason"] == "model judged it irrelevant"


async def test_delete_hit_unlinks_acquired_source(client, tmp_path):
    await _open_project(client, tmp_path, "meta_delete_source.qda")
    await _import_two_hits(client, tmp_path)
    hits = (await client.get("/api/v1/meta/hits")).json()["hits"]
    target = next(h for h in hits if h["doi"] == "10.1000/aaaa")

    res = await client.post(
        "/api/v1/meta/downloads/assign-batch",
        files=[("files", ("10.1000_aaaa.pdf", b"%PDF-1.4 test", "application/pdf"))],
    )
    assert res.status_code == 200, res.text
    source_id = res.json()["assigned"][0]["source_id"]

    assert (await client.delete(f"/api/v1/meta/hits/{target['hit_id']}")).status_code == 204

    from sqlalchemy import text as _sql

    async with service.session_factory() as session:
        count = (
            await session.execute(
                _sql("SELECT COUNT(*) FROM source WHERE id = :i"), {"i": source_id}
            )
        ).first()
    assert count[0] == 0


async def test_hit_dedupe_title_authors_and_prisma_duplicates(client, tmp_path):
    await _open_project(client, tmp_path, "meta_dedupe.qda")
    async with service.session_factory() as session:
        repo = MetaRepository(session)
        assert await repo.add_hits(
            [{"title": "Hello, World!", "authors": "Doe, Jane"}]
        ) == 1
        # Casefold + punctuation/whitespace folding matches the first row.
        assert await repo.add_hits(
            [{"title": "hello world", "authors": "Doe Jane"}]
        ) == 0
        # Blank bibliographic rows are never deduped (title is NOT NULL, so
        # imports carry empty strings rather than NULL).
        assert await repo.add_hits([{"title": "", "authors": ""}]) == 1
        assert await repo.add_hits([{"title": "", "authors": ""}]) == 1

    # A stored duplicate (e.g. legacy data) is reported by PRISMA.
    from sqlalchemy import text as _sql

    async with service.session_factory() as session:
        for title in ("Dupe Title", "dupe title"):
            await session.execute(
                _sql(
                    "INSERT INTO meta_hit (title, authors, status, created, updated) "
                    "VALUES (:t, 'A B', 'imported', '', '')"
                ),
                {"t": title},
            )
        await session.commit()

    prisma = (await client.get("/api/v1/meta/prisma")).json()
    assert prisma["identification"]["duplicates"] == 1


async def test_report_owner_scope(client, tmp_path):
    await _open_project(client, tmp_path, "meta_report_owner.qda")
    await _create_scheme(client)
    await _seed_extraction(1, "anna", _records("S1", "X", "a", 5.0, 4.0))
    await _seed_extraction(2, "anna", _records("S2", "Y", "b", 4.5, 4.0))
    await _seed_extraction(3, "bob", _records("S3", "Z", "b", 4.2, 4.0))

    from qualcoder_api.services import meta_report

    async with service.session_factory() as session:
        ctx = await meta_report.build_report(session, scheme="meta", owner="anna")
    assert ctx["pooled"]["k"] == 2


async def test_resolve_extraction_accepts_field_alias(client, tmp_path):
    await _open_project(client, tmp_path, "meta_field_alias.qda")
    await _create_scheme(client)
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    records_a = [
        {"study": {"sid": "S1", "design": "rct"}, "metrics": [{"dv": "X", "domain": "a"}]}
    ]
    records_b = [
        {"study": {"sid": "S1", "design": "rct"}, "metrics": [{"dv": "X", "domain": "b"}]}
    ]
    await _seed_extraction(hit_id, "anna", records_a)
    await _seed_extraction(hit_id, "bob", records_b)

    res = await client.post(
        "/api/v1/meta/extraction/resolve",
        json={
            "hit_id": hit_id,
            "field": "domain",
            "metric_key": "X",
            "value": "a",
            "master": "judge",
            "scheme": "meta",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["field"] == "domain"


async def test_meta_only_coder_roster_rename_and_reassign(client, tmp_path):
    await _open_project(client, tmp_path, "meta_coder_roster.qda")
    # A second local coder so the delete guard ("cannot delete the last
    # coder") does not short-circuit before the reassign path runs.
    assert (await client.post("/api/v1/coders", json={"name": "helper"})).status_code == 201
    await _create_scheme(client)
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    await _seed_extraction(hit_id, "metacoder", _records("S1", "X", "a", 5.0, 4.0))

    coders = (await client.get("/api/v1/coders")).json()["coders"]
    assert "metacoder" in [c["name"] for c in coders]

    res = await client.patch(
        "/api/v1/coders/metacoder", json={"new_name": "renamed"}
    )
    assert res.status_code == 200, res.text
    names = [c["name"] for c in res.json()["coders"]]
    assert "renamed" in names and "metacoder" not in names
    rows = (await client.get("/api/v1/meta/extractions")).json()
    assert rows[0]["owner"] == "renamed"

    res = await client.request(
        "DELETE",
        "/api/v1/coders/renamed",
        json={"reassign_to": "meta-tester"},
    )
    assert res.status_code == 200, res.text
    rows = (await client.get("/api/v1/meta/extractions")).json()
    assert rows[0]["owner"] == "meta-tester"


async def test_download_pdf_validates_magic_and_size(tmp_path, monkeypatch):
    import httpx

    from qualcoder_api.services import meta_download

    monkeypatch.setattr(meta_download, "MAX_PDF_BYTES", 64)
    dest = tmp_path / "paper.pdf"

    def transport_for(body: bytes, ctype: str) -> httpx.MockTransport:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": ctype}, content=body)

        return httpx.MockTransport(handler)

    # Wrong magic bytes are rejected before the body is buffered.
    async with httpx.AsyncClient(
        transport=transport_for(b"<html>not a pdf</html>", "text/html")
    ) as c:
        assert await meta_download.download_pdf(c, "http://x/1", dest) is False
    assert not dest.exists()

    # A valid small PDF is written.
    async with httpx.AsyncClient(
        transport=transport_for(b"%PDF-1.4 hello", "application/pdf")
    ) as c:
        assert await meta_download.download_pdf(c, "http://x/2", dest) is True
    assert dest.read_bytes().startswith(b"%PDF-")

    # Oversized bodies abort past the cap even with a valid magic header.
    async with httpx.AsyncClient(
        transport=transport_for(b"%PDF-" + b"x" * 200, "application/pdf")
    ) as c:
        assert await meta_download.download_pdf(c, "http://x/3", dest) is False


# ── consensus analysis (no coder picker) + full-text stage isolation ─────

async def test_analysis_consensus_combines_coders_and_drops_conflicts(client, tmp_path):
    """Two owners + one unresolved conflict: pooled k reflects the drop, the
    consensus report counts it, and an explicit owner still scopes to it."""
    await _open_project(client, tmp_path, "meta_consensus.qda")
    await _create_scheme(client)
    await _import_two_hits(client, tmp_path)
    hits = (await client.get("/api/v1/meta/hits")).json()["hits"]
    hit_agree, hit_conflict = hits[0]["hit_id"], hits[1]["hit_id"]
    # Unanimous coding on the first hit survives the merge.
    await _seed_extraction(hit_agree, "anna", _records("S1", "X", "a", 5.0, 4.0))
    await _seed_extraction(hit_agree, "bob", _records("S1", "X", "a", 5.0, 4.0))
    # Effect-critical disagreement with no settled master on the second hit.
    await _seed_extraction(hit_conflict, "anna", _records("S2", "Y", "b", 4.5, 4.0))
    await _seed_extraction(hit_conflict, "bob", _records("S2", "Y", "b", 8.5, 4.0))

    pooled = (
        await client.post("/api/v1/meta/analysis/pooled", json={"scheme": "meta"})
    ).json()
    assert pooled["k"] == 1, pooled
    assert pooled["k_total"] == 1, pooled
    consensus = pooled["consensus"]
    assert consensus["n_consensus_units"] == 2
    assert consensus["n_dropped_conflicts"] == 1
    assert consensus["n_dropped_metrics"] == 1

    # A settled master value resolves instead of dropping.
    await _seed_extraction(hit_conflict, "master", _records("S2", "Y", "b", 6.0, 4.0))
    pooled = (
        await client.post("/api/v1/meta/analysis/pooled", json={"scheme": "meta"})
    ).json()
    assert pooled["k"] == 2, pooled
    assert pooled["consensus"]["n_master_resolved"] == 1
    assert pooled["consensus"]["n_dropped_conflicts"] == 0

    # An explicit owner still scopes to that coder (no consensus envelope).
    scoped = (
        await client.post(
            "/api/v1/meta/analysis/pooled", json={"scheme": "meta", "owner": "anna"}
        )
    ).json()
    assert scoped["k"] == 2, scoped
    assert "consensus" not in scoped


async def test_fulltext_verdicts_do_not_leak_into_screening_list(client, tmp_path):
    """The Screening tab stays abstract-only: a full-text exclusion must not
    rewrite the hit's abstract eligibility in the hits list."""
    await _open_project(client, tmp_path, "meta_fulltext_stage.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]

    res = await client.put(
        "/api/v1/meta/screening",
        json={"hit_id": hit_id, "stage": "abstract", "verdicts": {"c1": {"applies": "Yes"}}},
    )
    assert res.status_code == 200, res.text
    res = await client.put(
        "/api/v1/meta/screening",
        json={"hit_id": hit_id, "stage": "fulltext", "verdicts": {"c1": {"applies": "No"}}},
    )
    assert res.status_code == 200, res.text

    hits = (await client.get("/api/v1/meta/hits")).json()["hits"]
    row = next(h for h in hits if h["hit_id"] == hit_id)
    assert row["screened"] is True
    assert row["eligible"] is True


# ── CodingStudio folder import ───────────────────────────────────────────

_CS_SCHEMA = {
    "schema_version": "3.1",
    "groups": ["Metadata & Identification", "Sample"],
    "common_fields": [
        {"name": "Study_ID", "group": "Metadata & Identification", "type": "string", "editor": "text"},
        {"name": "Title", "group": "Metadata & Identification", "type": "string", "editor": "text"},
        {"name": "DOI", "group": "Metadata & Identification", "type": "string|null", "editor": "text"},
        {"name": "Authors", "group": "Metadata & Identification", "type": "string", "editor": "text"},
        {"name": "Year", "group": "Metadata & Identification", "type": "integer", "editor": "number"},
        {"name": "N_Analyzed", "group": "Sample", "type": "integer|null", "editor": "number"},
    ],
    "dv_fields": [
        {"name": "dv_name", "group": "Other", "type": "string", "editor": "text"},
        {"name": "n1i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "n2i", "group": "Other", "type": "number", "editor": "number"},
        {"name": "yi", "group": "Other", "type": "number", "editor": "number"},
        {"name": "vi", "group": "Other", "type": "number", "editor": "number"},
    ],
    "modules": {},
    "intervention_type_modules": {},
    "vocabularies": {"intervention_types": ["inoculation"]},
}

_CS_HEADER = [
    "an", "title", "abstract", "authors", "doi", "year", "source", "language",
    "C1_verdict", "C1_certainty", "C1_rationale", "C2_verdict", "C3_verdict", "C4_verdict",
    "Intervention_verdict", "Fulltext_Verdict", "Fulltext_Exclusion_Criterion", "Fulltext_Reason",
]


def _cs_record(study_id: str, title: str, doi: str) -> dict:
    return {
        "Study_ID": study_id,
        "Title": title,
        "DOI": doi,
        "Authors": "Doe, J",
        "Year": 2020,
        "N_Analyzed": 62,
        "DV_Metrics": [{"dv_name": "Accuracy", "n1i": 30, "n2i": 32, "yi": 0.25, "vi": 0.02}],
    }


def _write_cs_folder(root: Path) -> Path:
    from openpyxl import Workbook

    for sub in ("Papers", "Extraction", "Screening", "Scripts/coding_web"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "Scripts/coding_web/schema.json").write_text(json.dumps(_CS_SCHEMA), encoding="utf-8")
    (root / "Extraction/Study A.json").write_text(
        json.dumps([_cs_record("A2020_Exp1", "Study A: inoculation", "10.1000/aaaa")]),
        encoding="utf-8",
    )
    (root / "Screening/MF.json").write_text(
        json.dumps(
            {
                "an-a": {
                    "an": "an-a",
                    "criteria": {
                        "C1": {"verdict": "Yes", "certainty": "High", "rationale": ""},
                        "C2": {"verdict": "Yes", "certainty": "High", "rationale": ""},
                        "C3": {"verdict": "Yes", "certainty": "High", "rationale": ""},
                        "C4": {"verdict": "Yes", "certainty": "High", "rationale": ""},
                        "Intervention": {"verdict": "inoculation", "certainty": "High", "rationale": ""},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(_CS_HEADER)
    ws.append(["an-a", "Study A: inoculation", "Abstract A.", "Doe, J", "10.1000/aaaa", 2020, "J. Test", "eng",
               "Yes", "High", "", "Yes", "Yes", "Yes", "inoculation", "Include", "", ""])
    ws.append(["an-c", "Study C", "Abstract C.", "Poe, T", "10.1000/cccc", 2022, "J. Test", "eng",
               "Yes", "High", "", "Yes", "Yes", "Yes", "generic", "Exclude",
               "Not a primary experimental study (C4)", "observational"])
    wb.save(root / "master_dataset.xlsx")
    (root / "Papers/Study A.pdf").write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Size 4/Root 1 0 R>>\n%%EOF\n"
    )
    return root


async def test_codingstudio_preview_and_import(client, tmp_path):
    await _open_project(client, tmp_path, "meta_cs.qda")
    folder = _write_cs_folder(tmp_path / "cs")

    res = await client.post("/api/v1/meta/codingstudio/preview", json={"folder": str(folder)})
    assert res.status_code == 200, res.text
    preview = res.json()
    assert preview["exists"] is True
    assert preview["papers"] == 1
    assert preview["extraction_files"] == 1
    assert preview["workbook"]["rows"] == 2
    assert preview["schema_version"] == "3.1"
    assert preview["screenings"] == [{"coder": "MF", "rows": 1}]

    res = await client.post("/api/v1/meta/codingstudio/import", json={"folder": str(folder)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["hits_imported"] == 2
    assert body["extractions_imported"] == 1
    assert body["pdfs_linked"] == 1
    assert body["errors"] == []

    status = (await client.get("/api/v1/meta/status")).json()
    assert status["hits"] == 2
    assert status["screening_rows"] == 5  # 1 coder abstract + 2 base abstract + 2 full-text
    assert status["schemes"] == 1

    # Idempotent: nothing new appears on a second import.
    body2 = (await client.post("/api/v1/meta/codingstudio/import", json={"folder": str(folder)})).json()
    assert body2["hits_imported"] == 0
    assert body2["pdfs_linked"] == 0
    status2 = (await client.get("/api/v1/meta/status")).json()
    assert status2["hits"] == 2
    assert status2["screening_rows"] == 5
    assert status2["extracted"] == 1

    # A folder that does not exist previews as ``exists: false`` (200) but
    # cannot be imported (422).
    missing = str(tmp_path / "nowhere")
    preview_missing = await client.post("/api/v1/meta/codingstudio/preview", json={"folder": missing})
    assert preview_missing.status_code == 200
    assert preview_missing.json()["exists"] is False
    assert (await client.post("/api/v1/meta/codingstudio/import", json={"folder": missing})).status_code == 422

    # A folder with no workbook and no extractions is unusable (422).
    empty = tmp_path / "empty_cs"
    empty.mkdir()
    assert (await client.post("/api/v1/meta/codingstudio/import", json={"folder": str(empty)})).status_code == 422


# ── query-shape regressions (audit: redundant / unbounded loads) ──────────


async def test_status_loads_criteria_once(client, tmp_path, monkeypatch):
    """``/meta/status`` must not re-query the criteria it already holds."""
    await _open_project(client, tmp_path, "meta_status_once.qda")
    await client.put(
        "/api/v1/meta/criteria",
        json=[{"position": 0, "key": "c1", "label": "C1", "prompt_text": "p"}],
    )
    calls = {"n": 0}
    original = MetaRepository.list_criteria

    async def counted(self, *args, **kwargs):
        calls["n"] += 1
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(MetaRepository, "list_criteria", counted)
    res = await client.get("/api/v1/meta/status")
    assert res.status_code == 200, res.text
    assert res.json()["criteria"] == 1
    assert calls["n"] == 1


async def test_extraction_export_filters_status_in_query(client, tmp_path, monkeypatch):
    """Export restricts to extracted rows at the query, not after loading all."""
    await _open_project(client, tmp_path, "meta_export_status.qda")
    seen: dict = {}
    original = MetaRepository.list_extractions

    async def spy(self, *args, **kwargs):
        seen.update(kwargs)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(MetaRepository, "list_extractions", spy)
    res = await client.get("/api/v1/meta/extract/export", params={"fmt": "csv"})
    assert res.status_code == 200, res.text
    assert seen.get("status") == "extracted"


async def test_documents_and_extractions_do_not_load_every_hit(client, tmp_path, monkeypatch):
    """Titles are attached by id, never by loading the whole hit table."""
    await _open_project(client, tmp_path, "meta_no_full_hits.qda")
    await _create_scheme(client)
    await _import_two_hits(client, tmp_path)
    hit_id = (await client.get("/api/v1/meta/hits")).json()["hits"][0]["hit_id"]
    await _seed_extraction(hit_id, "anna", _records("S1", "X", "a", 5.0, 4.0))

    async def boom(self, *args, **kwargs):  # pragma: no cover - regression guard
        raise AssertionError("list_hits() must not be called for a page of rows")

    monkeypatch.setattr(MetaRepository, "list_hits", boom)

    res = await client.get("/api/v1/meta/extractions")
    assert res.status_code == 200, res.text
    rows = res.json()
    assert rows and rows[0]["title"].startswith("Study A")

    res = await client.get("/api/v1/meta/documents")
    assert res.status_code == 200, res.text
    assert res.json() == []


async def test_report_rederives_stale_dv_metrics(client, tmp_path):
    """The report re-derives effects under the live codebook, not the cache.

    A stale (empty) ``dv_metrics`` column must not zero the report's synthesis:
    the persisted column can lag a scheme role edit, exactly as it can for the
    Analyze tab.
    """
    await _open_project(client, tmp_path, "meta_report_refresh.qda")
    await _create_scheme(client)
    records = _records("S1", "X", "a", 5.0, 4.0)
    async with service.session_factory() as session:
        await MetaRepository(session).upsert_extraction(
            hit_id=1,
            owner="anna",
            scheme="meta",
            study_vars={"records": records},
            dv_metrics=[],  # stale cache
            status="extracted",
        )

    from qualcoder_api.services import meta_report

    async with service.session_factory() as session:
        ctx = await meta_report.build_report(session, scheme="meta")
    assert ctx["pooled"]["k"] == 1
    assert ctx["pooled"]["estimate"] is not None

