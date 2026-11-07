"""Regression tests for the api/v1 audit (partition A) fixes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.interchange import _attachment_disposition
from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "研究.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c
        await c.post("/api/v1/projects/close")


async def test_patch_memo_keeps_subcode_parent(project_client):
    """A memo-only PATCH must not detach a sub-code (supercid was cleared
    because ``"supercid" in req.model_dump()`` is always true)."""
    client = project_client
    parent = (await client.post("/api/v1/codes", json={"name": "Parent"})).json()["cid"]
    child = (
        await client.post("/api/v1/codes", json={"name": "Child", "supercid": parent})
    ).json()
    assert child["supercid"] == parent

    res = await client.patch(f"/api/v1/codes/{child['cid']}", json={"memo": "note"})
    assert res.status_code == 200, res.text
    assert res.json()["supercid"] == parent
    assert res.json()["memo"] == "note"

    # An explicit null still detaches it.
    res = await client.patch(f"/api/v1/codes/{child['cid']}", json={"supercid": None})
    assert res.status_code == 200, res.text
    assert res.json()["supercid"] is None


async def test_refi_export_non_latin1_project_name(project_client):
    res = await project_client.get("/api/v1/interchange/export/refi")
    assert res.status_code == 200, res.text
    disposition = res.headers["content-disposition"]
    assert "filename*=UTF-8''%E7%A0%94%E7%A9%B6" in disposition


def test_attachment_disposition_escapes_quotes():
    value = _attachment_disposition('a"b\\c.qdp')
    assert value.startswith('attachment; filename="a_b_c.qdp"; ')
    value.encode("latin-1")  # must be header-encodable
