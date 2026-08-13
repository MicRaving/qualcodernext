"""Segment weights (0-100) + the AV PATCH endpoint — text/image/AV codings.

Weights are MAXQDA-style segment weights: an integer 0-100 stored on
code_text/code_image/code_av (migration v27), accepted on create and
PATCH, and returned in GET responses. 0 = no weight.
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
        target = tmp_path / "weights.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def _code_and_text_source(client) -> tuple[int, int]:
    code = (await client.post("/api/v1/codes", json={"name": "w"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("t.txt", "hello world", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    return code["cid"], fid


async def test_text_weight_create_and_roundtrip(project_client):
    client, _ = project_client
    cid, fid = await _code_and_text_source(client)

    created = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5, "weight": 42},
    )
    assert created.status_code == 201, created.text
    assert created.json()["weight"] == 42

    listed = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert listed[0]["weight"] == 42

    created = await client.post(
        "/api/v1/codings/text",
        json={"cid": cid, "fid": fid, "seltext": "world", "pos0": 6, "pos1": 11},
    )
    assert created.status_code == 201, created.text
    assert created.json()["weight"] == 0


async def test_text_weight_patch_and_bounds(project_client):
    client, _ = project_client
    cid, fid = await _code_and_text_source(client)
    ctid = (
        await client.post(
            "/api/v1/codings/text",
            json={"cid": cid, "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
        )
    ).json()["ctid"]

    patched = await client.patch(f"/api/v1/codings/text/{ctid}", json={"weight": 7})
    assert patched.status_code == 200, patched.text
    assert patched.json()["weight"] == 7

    # weight 0 clears the weight (no weight)
    cleared = await client.patch(f"/api/v1/codings/text/{ctid}", json={"weight": 0})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["weight"] == 0

    # a memo patch keeps the weight
    with_weight = await client.patch(f"/api/v1/codings/text/{ctid}", json={"weight": 100})
    assert with_weight.status_code == 200
    memo = await client.patch(f"/api/v1/codings/text/{ctid}", json={"memo": "m"})
    assert memo.status_code == 200
    assert memo.json()["weight"] == 100

    for bad in (-1, 101):
        rejected = await client.patch(f"/api/v1/codings/text/{ctid}", json={"weight": bad})
        assert rejected.status_code == 422, f"weight {bad} must be rejected"


async def test_weight_validation_on_create(project_client):
    client, _ = project_client
    cid, fid = await _code_and_text_source(client)
    for bad in (-1, 101):
        rejected = await client.post(
            "/api/v1/codings/text",
            json={"cid": cid, "fid": fid, "seltext": "x", "pos0": 0, "pos1": 1, "weight": bad},
        )
        assert rejected.status_code == 422, f"weight {bad} must be rejected on create"


async def test_image_weight_roundtrip_and_patch(project_client):
    client, _ = project_client
    cid, _ = await _code_and_text_source(client)
    await client.post(
        "/api/v1/sources/import", files={"file": ("pic.png", b"\x89PNGfake", "image/png")}
    )
    sid = (await client.get("/api/v1/sources")).json()[0]["id"]

    created = await client.post(
        "/api/v1/codings/image",
        json={"id": sid, "x1": 1, "y1": 2, "width": 30, "height": 40, "cid": cid, "weight": 25},
    )
    assert created.status_code == 201, created.text
    imid = created.json()["imid"]
    assert created.json()["weight"] == 25

    listed = (await client.get(f"/api/v1/codings/image/{sid}")).json()
    assert listed[0]["weight"] == 25

    patched = await client.patch(f"/api/v1/codings/image/{imid}", json={"weight": 60})
    assert patched.status_code == 200, patched.text
    assert patched.json()["weight"] == 60

    rejected = await client.patch(f"/api/v1/codings/image/{imid}", json={"weight": 101})
    assert rejected.status_code == 422

    created = await client.post(
        "/api/v1/codings/image",
        json={"id": sid, "x1": 5, "y1": 5, "width": 10, "height": 10, "cid": cid},
    )
    assert created.status_code == 201
    assert created.json()["weight"] == 0


async def test_av_weight_roundtrip_and_patch_endpoint(project_client):
    client, _ = project_client
    cid, _ = await _code_and_text_source(client)
    await client.post(
        "/api/v1/sources/import", files={"file": ("clip.mp4", b"\x00" * 64, "video/mp4")}
    )
    sid = (await client.get("/api/v1/sources")).json()[0]["id"]

    created = await client.post(
        "/api/v1/codings/av",
        json={"id": sid, "pos0": 100, "pos1": 900, "cid": cid, "weight": 33},
    )
    assert created.status_code == 201, created.text
    avid = created.json()["avid"]
    assert created.json()["weight"] == 33

    listed = (await client.get(f"/api/v1/codings/av/{sid}")).json()
    assert listed[0]["weight"] == 33

    patched = await client.patch(f"/api/v1/codings/av/{avid}", json={"weight": 12})
    assert patched.status_code == 200, patched.text
    assert patched.json()["weight"] == 12

    memo = await client.patch(f"/api/v1/codings/av/{avid}", json={"memo": "av memo"})
    assert memo.status_code == 200, memo.text
    assert memo.json()["memo"] == "av memo"
    assert memo.json()["weight"] == 12

    rejected = await client.patch(f"/api/v1/codings/av/{avid}", json={"weight": -3})
    assert rejected.status_code == 422

    missing = await client.patch("/api/v1/codings/av/999999", json={"weight": 1})
    assert missing.status_code == 404

    created = await client.post(
        "/api/v1/codings/av",
        json={"id": sid, "pos0": 2000, "pos1": 3000, "cid": cid},
    )
    assert created.status_code == 201
    assert created.json()["weight"] == 0
