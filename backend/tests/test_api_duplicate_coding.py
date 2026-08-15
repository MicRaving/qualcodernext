"""Duplicate text-coding inserts must answer 409, not 500.

code_text carries the unique constraint (cid, fid, pos0, pos1, owner) — a
repeated insert of the same segment (e.g. a stray create fired by a coder
on a view click) used to explode as an IntegrityError 500 with a traceback.
The create endpoint must translate it into a clean 409 and leave the
session usable for later requests.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "dupes.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c
        await c.post("/api/v1/projects/close")


async def _code_and_text_source(client) -> tuple[int, int]:
    code = (await client.post("/api/v1/codes", json={"name": "dup"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("t.txt", "hello world", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    return code["cid"], fid


async def test_duplicate_text_coding_returns_409(project_client):
    client = project_client
    cid, fid = await _code_and_text_source(client)
    body = {"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5}

    first = await client.post("/api/v1/codings/text", json=body)
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/codings/text", json=body)
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "This segment is already coded with this code"

    # The 409 must not poison the session: a distinct insert still works.
    third = await client.post(
        "/api/v1/codings/text",
        json={**body, "seltext": "world", "pos0": 6, "pos1": 11},
    )
    assert third.status_code == 201, third.text
    assert third.json()["pos0"] == 6

    listed = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert len(listed) == 2


async def test_duplicate_image_coding_still_allowed(project_client):
    """code_image has no unique constraint — equal rectangles are legal
    (legacy behavior), so the image create endpoint keeps answering 201."""
    client = project_client
    cid, _ = await _code_and_text_source(client)
    await client.post(
        "/api/v1/sources/import", files={"file": ("pic.png", b"\x89PNGfake", "image/png")}
    )
    sid = (await client.get("/api/v1/sources")).json()[0]["id"]
    body = {"id": sid, "x1": 1, "y1": 2, "width": 30, "height": 40, "cid": cid}

    first = await client.post("/api/v1/codings/image", json=body)
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/codings/image", json=body)
    assert second.status_code == 201, second.text
