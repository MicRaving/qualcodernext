"""API tests — QTT workspace (worksheets, sections, items, send-segment)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.qtt import (
    CRESWELL_MIXED_SECTIONS,
    QUAL_DEFAULT_SECTIONS,
)
from qualcoder_api.api.v1.qtt import (
    router as qtt_router,
)
from qualcoder_api.main import app


def _ensure_qtt_wired() -> None:
    """Mount the qtt router when the v1 router does not carry it yet.

    The router is wired into ``api/v1/router.py`` by the supervisor; until
    then this test file mounts it itself so the suite runs standalone.
    """
    if any(getattr(route, "path", "") == "/api/v1/qtt" for route in app.router.routes):
        return
    app.include_router(qtt_router, prefix="/api/v1")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    _ensure_qtt_wired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "qtt.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def _one_source(client) -> int:
    """Import one text file and return its id."""
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("a.txt", "alpha beta gamma", "text/plain")}
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _make_sheet(client, name="Sheet", kind="qual"):
    res = await client.post("/api/v1/qtt", json={"name": name, "kind": kind, "owner": "tester"})
    assert res.status_code == 201, res.text
    return res.json()


async def test_qtt_sheet_crud(project_client):
    client, _ = project_client

    # Empty name → 422; bad kind → 422.
    assert (await client.post("/api/v1/qtt", json={"name": "  "})).status_code == 422
    assert (await client.post("/api/v1/qtt", json={"name": "x", "kind": "both"})).status_code == 422

    # Qual sheet seeds the single default section.
    qual = await _make_sheet(client, name="Insights Board", kind="qual")
    assert qual["kind"] == "qual"
    assert qual["sections"] == QUAL_DEFAULT_SECTIONS
    assert qual["counts"] == {"Insights": 0}

    # Mixed sheet seeds the Creswell 14-step section list.
    mixed = await _make_sheet(client, name="MM Study", kind="mixed")
    assert mixed["kind"] == "mixed"
    assert len(mixed["sections"]) == 14
    assert mixed["sections"] == CRESWELL_MIXED_SECTIONS
    assert set(mixed["counts"].keys()) == set(CRESWELL_MIXED_SECTIONS)

    # List both sheets with counts.
    listed = (await client.get("/api/v1/qtt")).json()
    assert [s["name"] for s in listed] == ["Insights Board", "MM Study"]

    # PATCH the header fields.
    patched = await client.patch(
        f"/api/v1/qtt/{qual['id']}",
        json={
            "name": "Renamed",
            "research_question": "RQ?",
            "purpose": "Purpose",
            "framework": "Creswell",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Renamed"
    assert body["research_question"] == "RQ?"
    assert body["purpose"] == "Purpose"
    assert body["framework"] == "Creswell"

    # Empty name on PATCH → 422; unknown sheet → 404.
    assert (await client.patch(f"/api/v1/qtt/{qual['id']}", json={"name": ""})).status_code == 422
    assert (await client.patch("/api/v1/qtt/9999", json={"name": "x"})).status_code == 404

    # DELETE removes the sheet.
    assert (await client.delete(f"/api/v1/qtt/{mixed['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/qtt/{mixed['id']}")).status_code == 404
    listed = (await client.get("/api/v1/qtt")).json()
    assert [s["name"] for s in listed] == ["Renamed"]


async def test_qtt_items_and_validation(project_client):
    client, _ = project_client
    fid = await _one_source(client)
    sheet = await _make_sheet(client, name="Board", kind="qual")

    # Note item.
    note = await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "note", "payload": {"text": "first thought"}},
    )
    assert note.status_code == 201, note.text
    assert note.json()["kind"] == "note"
    assert note.json()["payload"]["text"] == "first thought"
    assert note.json()["section"] == "Insights"

    # Segment item: span text is resolved from the source fulltext.
    seg = await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "segment", "payload": {"fid": fid, "pos0": 0, "pos1": 10}},
    )
    assert seg.status_code == 201, seg.text
    seg_body = seg.json()
    assert seg_body["payload"] == {"fid": fid, "pos0": 0, "pos1": 10, "text": "alpha beta"}
    assert seg_body["source_name"] == "a.txt"
    assert seg_body["source_text"] == "alpha beta"

    # Chart + link items.
    chart = await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "chart", "payload": {"report": "code-frequencies", "params": {"top": 5}}},
    )
    assert chart.status_code == 201, chart.text
    assert chart.json()["payload"] == {"report": "code-frequencies", "params": {"top": 5}}

    link = await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "link", "payload": {"url": "https://example.org/paper"}},
    )
    assert link.status_code == 201, link.text
    assert link.json()["payload"] == {"url": "https://example.org/paper"}

    # GET /qtt/{id}: items grouped by section; counts updated.
    detail = (await client.get(f"/api/v1/qtt/{sheet['id']}")).json()
    assert detail["name"] == "Board"
    assert set(detail["items"].keys()) == {"Insights"}
    assert len(detail["items"]["Insights"]) == 4
    assert detail["counts"]["Insights"] == 4
    listed = (await client.get("/api/v1/qtt")).json()
    assert listed[0]["counts"] == {"Insights": 4}

    # Validation: unknown kind, empty note, bad chart/link, bad span.
    bad = await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "memo", "payload": {"text": "x"}},
    )
    assert bad.status_code == 422
    assert (
        await client.post(
            f"/api/v1/qtt/{sheet['id']}/items",
            json={"section": "Insights", "kind": "note", "payload": {"text": "  "}},
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/qtt/{sheet['id']}/items",
            json={"section": "Insights", "kind": "chart", "payload": {"params": {}}},
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/qtt/{sheet['id']}/items",
            json={"section": "Insights", "kind": "link", "payload": {"url": ""}},
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/qtt/{sheet['id']}/items",
            json={"section": "Insights", "kind": "segment", "payload": {"fid": fid, "pos0": 0, "pos1": 999}},
        )
    ).status_code == 422
    # Unknown section → 422; unknown sheet → 404.
    assert (
        await client.post(
            f"/api/v1/qtt/{sheet['id']}/items",
            json={"section": "Nope", "kind": "note", "payload": {"text": "x"}},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/qtt/9999/items",
            json={"section": "Insights", "kind": "note", "payload": {"text": "x"}},
        )
    ).status_code == 404

    # PATCH: move between sections (mixed sheet has several) and edit payload.
    mixed = await _make_sheet(client, name="MM", kind="mixed")
    m_note = (
        await client.post(
            f"/api/v1/qtt/{mixed['id']}/items",
            json={"section": "Research Questions", "kind": "note", "payload": {"text": "old"}},
        )
    ).json()
    moved = await client.patch(
        f"/api/v1/qtt/items/{m_note['id']}",
        json={"section": "Qualitative Data Collection"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["section"] == "Qualitative Data Collection"
    edited = await client.patch(
        f"/api/v1/qtt/items/{m_note['id']}",
        json={"payload": {"text": "new"}},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["payload"]["text"] == "new"
    # Moving to a section that does not exist → 422; missing item → 404.
    assert (
        await client.patch(f"/api/v1/qtt/items/{m_note['id']}", json={"section": "Nope"})
    ).status_code == 422
    assert (await client.patch("/api/v1/qtt/items/9999", json={"section": "X"})).status_code == 404

    # DELETE item; double delete → 404.
    assert (await client.delete(f"/api/v1/qtt/items/{m_note['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/qtt/items/{m_note['id']}")).status_code == 404


async def test_qtt_send_segment(project_client):
    client, _ = project_client
    fid = await _one_source(client)
    mixed = await _make_sheet(client, name="MM", kind="mixed")

    # Default section = first section of the sheet.
    sent = await client.post(
        f"/api/v1/qtt/{mixed['id']}/send-segment",
        json={"fid": fid, "pos0": 0, "pos1": 5},
    )
    assert sent.status_code == 201, sent.text
    body = sent.json()
    assert body["kind"] == "segment"
    assert body["section"] == "Research Questions"
    assert body["payload"] == {"fid": fid, "pos0": 0, "pos1": 5, "text": "alpha"}
    assert body["source_name"] == "a.txt"

    # Explicit section.
    sent2 = await client.post(
        f"/api/v1/qtt/{mixed['id']}/send-segment",
        json={"fid": fid, "pos0": 6, "pos1": 10, "section": "Meta-Inferences"},
    )
    assert sent2.status_code == 201, sent2.text
    assert sent2.json()["section"] == "Meta-Inferences"
    assert sent2.json()["payload"]["text"] == "beta"

    # Out-of-range span → 422 (nothing stored).
    bad = await client.post(
        f"/api/v1/qtt/{mixed['id']}/send-segment",
        json={"fid": fid, "pos0": 0, "pos1": 500},
    )
    assert bad.status_code == 422
    bad2 = await client.post(
        f"/api/v1/qtt/{mixed['id']}/send-segment",
        json={"fid": 9999, "pos0": 0, "pos1": 5},
    )
    assert bad2.status_code == 422
    # Unknown sheet → 404; unknown section → 422.
    assert (
        await client.post("/api/v1/qtt/9999/send-segment", json={"fid": fid, "pos0": 0, "pos1": 5})
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/qtt/{mixed['id']}/send-segment",
            json={"fid": fid, "pos0": 0, "pos1": 5, "section": "Nope"},
        )
    ).status_code == 422

    # The two good sends landed in the sheet.
    detail = (await client.get(f"/api/v1/qtt/{mixed['id']}")).json()
    assert len(detail["items"]["Research Questions"]) == 1
    assert len(detail["items"]["Meta-Inferences"]) == 1


async def test_qtt_cascade_delete(project_client):
    client, _ = project_client
    fid = await _one_source(client)
    sheet = await _make_sheet(client, name="Board", kind="qual")
    await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "segment", "payload": {"fid": fid, "pos0": 0, "pos1": 5}},
    )
    await client.post(
        f"/api/v1/qtt/{sheet['id']}/items",
        json={"section": "Insights", "kind": "note", "payload": {"text": "keep?"}},
    )

    assert (await client.delete(f"/api/v1/qtt/{sheet['id']}")).status_code == 204
    # The sheet is gone …
    assert (await client.get(f"/api/v1/qtt/{sheet['id']}")).status_code == 404
    # … and its items were cascaded away (no orphan item rows remain).
    res = await client.get("/api/v1/qtt")
    assert res.json() == []


async def test_qtt_audit_rows(project_client):
    client, _ = project_client
    fid = await _one_source(client)
    sheet = await _make_sheet(client, name="Board", kind="qual")

    rows = (await client.get("/api/v1/audit", params={"action": "qtt.create"})).json()["rows"]
    assert len(rows) == 1
    create_row = rows[0]
    assert create_row["user"] == "tester"
    assert create_row["entity"] == "qtt_sheet"
    assert create_row["entity_id"] == sheet["id"]
    assert create_row["detail"]["kind"] == "qual"
    assert create_row["detail"]["sections"] == QUAL_DEFAULT_SECTIONS

    await client.patch(f"/api/v1/qtt/{sheet['id']}", json={"purpose": "test purpose"})
    rows = (await client.get("/api/v1/audit", params={"action": "qtt.update"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == sheet["id"]
    assert rows[0]["detail"]["purpose"] == "test purpose"

    sent = (
        await client.post(
            f"/api/v1/qtt/{sheet['id']}/send-segment",
            json={"fid": fid, "pos0": 0, "pos1": 5},
        )
    ).json()
    rows = (await client.get("/api/v1/audit", params={"action": "qtt.send_segment"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == sent["id"]
    assert rows[0]["source_id"] == fid
    assert rows[0]["detail"]["sheet_id"] == sheet["id"]

    await client.delete(f"/api/v1/qtt/items/{sent['id']}")
    rows = (await client.get("/api/v1/audit", params={"action": "qtt.item.delete"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == sent["id"]
    assert rows[0]["source_id"] == fid

    await client.delete(f"/api/v1/qtt/{sheet['id']}")
    rows = (await client.get("/api/v1/audit", params={"action": "qtt.delete"})).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["entity_id"] == sheet["id"]
    assert rows[0]["detail"]["item_count"] == 0  # the item was deleted before the sheet
