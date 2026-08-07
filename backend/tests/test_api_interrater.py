"""API tests — interrater reliability report (Cohen's Kappa, Krippendorff's
Alpha, Gwet's AC1)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _setup(client, tmp_path) -> dict:
    """Two files, two codes; coders alice/bob with a KNOWN contingency:
    both=2, only_a=1, only_b=1, neither=0 over 4 unit x code pairs."""
    target = tmp_path / "irr.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text

    cids = {}
    for name in ("C1", "C2"):
        res = await client.post("/api/v1/codes", json={"name": name})
        cids[name] = res.json()["cid"]

    fids = []
    for name in ("a.txt", "b.txt"):
        res = await client.post(
            "/api/v1/sources/import",
            files={"file": (name, "x", "text/plain")},
        )
        fids.append(res.json()["id"])

    async def code(fid, cid, owner, text):
        res = await client.post(
            "/api/v1/codings/text",
            json={
                "cid": cid,
                "fid": fid,
                "seltext": text,
                "pos0": 0,
                "pos1": len(text),
                "owner": owner,
            },
        )
        assert res.status_code == 201, res.text

    # alice: (f1,C1) (f1,C2) (f2,C1) | bob: (f1,C1) (f2,C1) (f2,C2)
    await code(fids[0], cids["C1"], "alice", "alpha")
    await code(fids[0], cids["C2"], "alice", "beta")
    await code(fids[1], cids["C1"], "alice", "gamma")
    await code(fids[0], cids["C1"], "bob", "delta")
    await code(fids[1], cids["C1"], "bob", "epsilon")
    await code(fids[1], cids["C2"], "bob", "zeta")
    return {"target": target, "fids": fids}


async def test_interrater_metrics(client, tmp_path):
    await _setup(client, tmp_path)
    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "alice", "coder_b": "bob"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["n_units"] == 2
    assert body["n_categories"] == 2
    assert body["n_pairs"] == 4
    assert body["both"] == 2
    assert body["only_a"] == 1
    assert body["only_b"] == 1
    assert body["neither"] == 0
    # Hand-computed: kappa = -1/3, krippendorff = -1/3, AC1 = 0.2
    assert body["kappa"] == pytest.approx(-0.3333, abs=0.001)
    assert body["krippendorff"] == pytest.approx(-0.3333, abs=0.001)
    assert body["gwet_ac1"] == pytest.approx(0.2, abs=0.001)

    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "alice", "coder_b": "alice"},
    )
    assert res.status_code == 422

    await client.post("/api/v1/projects/close")


async def test_interrater_empty_project(client, tmp_path):
    target = tmp_path / "irr-empty.qda"
    await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "alice", "coder_b": "bob"},
    )
    assert res.status_code == 200
    assert res.json()["n_pairs"] == 0
    await client.post("/api/v1/projects/close")
