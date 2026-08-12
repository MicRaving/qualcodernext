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
    # Hand-computed: kappa = -1/3, krippendorff (coincidence matrix) = -1/6,
    # AC1 = 0.2
    assert body["kappa"] == pytest.approx(-0.3333, abs=0.001)
    assert body["krippendorff"] == pytest.approx(-0.1667, abs=0.001)
    assert body["gwet_ac1"] == pytest.approx(0.2, abs=0.001)
    # New multi-coder fields: default coders = [alice, bob], alpha over both
    # equals the pair's Krippendorff, one pair, mean/min/max = the pair.
    assert body["coders"] == ["alice", "bob"]
    assert body["n_coders"] == 2
    assert body["alpha"] == pytest.approx(body["krippendorff"], abs=1e-6)
    assert len(body["pairs"]) == 1
    pair = body["pairs"][0]
    assert pair["coder_a"] == "alice"
    assert pair["coder_b"] == "bob"
    for key in ("both", "only_a", "only_b", "neither", "n_units", "n_categories"):
        assert pair[key] == body[key]
    for key in ("kappa", "krippendorff", "gwet_ac1"):
        assert pair[key] == body[key]
        assert body["pairwise_mean"][key] == pair[key]
        assert body["pairwise_min"][key] == pair[key]
        assert body["pairwise_max"][key] == pair[key]

    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "alice", "coder_b": "alice"},
    )
    assert res.status_code == 422

    await client.post("/api/v1/projects/close")


async def test_interrater_three_coders(client, tmp_path):
    """Three coders: alpha over all three, 3 pairs, per-pair contingency."""
    target = tmp_path / "irr3.qda"
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

    # alice: (f1,C1) (f1,C2) | bob: (f1,C1) (f2,C1) | carol: (f1,C1) (f2,C1)
    # Cell ratings over 4 cells: (f1,C1) 111, (f1,C2) 100, (f2,C1) 011, (f2,C2) 000.
    await code(fids[0], cids["C1"], "alice", "one")
    await code(fids[0], cids["C2"], "alice", "two")
    await code(fids[0], cids["C1"], "bob", "three")
    await code(fids[1], cids["C1"], "bob", "four")
    await code(fids[0], cids["C1"], "carol", "five")
    await code(fids[1], cids["C1"], "carol", "six")

    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "alice", "coder_b": "bob", "coders": ["alice", "bob", "carol"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["coders"] == ["alice", "bob", "carol"]
    assert body["n_coders"] == 3
    # Hand-computed coincidence matrix over the 4 cells x 3 coders:
    # o11=8, o00=8, o01=o10=4, N=24, m=3 -> alpha = 7/18.
    assert body["alpha"] == pytest.approx(7 / 18, abs=0.0001)
    assert len(body["pairs"]) == 3

    by_names = {(p["coder_a"], p["coder_b"]): p for p in body["pairs"]}
    assert set(by_names) == {("alice", "bob"), ("alice", "carol"), ("bob", "carol")}
    # bob and carol coded identically: perfect agreement, but with no
    # "absent" ratings the chance-corrected measures are undefined.
    perfect = by_names[("bob", "carol")]
    assert perfect["n_units"] == 2
    assert perfect["n_categories"] == 1
    assert perfect["n_pairs"] == 2
    assert perfect["both"] == 2
    assert perfect["only_a"] == 0
    assert perfect["only_b"] == 0
    assert perfect["neither"] == 0
    assert perfect["kappa"] is None
    assert perfect["krippendorff"] is None
    assert perfect["gwet_ac1"] == 1
    # alice vs bob: both=1, only_a=1, only_b=1, neither=1 -> kappa=0, AC1=0,
    # alpha (coincidence matrix) = 1/8.
    mixed = by_names[("alice", "bob")]
    assert (mixed["both"], mixed["only_a"], mixed["only_b"], mixed["neither"]) == (1, 1, 1, 1)
    assert mixed["kappa"] == pytest.approx(0, abs=0.001)
    assert mixed["krippendorff"] == pytest.approx(0.125, abs=0.001)
    assert mixed["gwet_ac1"] == pytest.approx(0, abs=0.001)

    assert body["pairwise_mean"]["kappa"] == pytest.approx(0, abs=0.001)
    assert body["pairwise_mean"]["krippendorff"] == pytest.approx(0.125, abs=0.001)
    assert body["pairwise_mean"]["gwet_ac1"] == pytest.approx(1 / 3, abs=0.001)
    assert body["pairwise_min"]["kappa"] == 0
    assert body["pairwise_max"]["kappa"] == 0
    assert body["pairwise_min"]["krippendorff"] == pytest.approx(0.125, abs=0.001)
    assert body["pairwise_max"]["krippendorff"] == pytest.approx(0.125, abs=0.001)
    # Anchor pair = the requested coder_a/coder_b contingency.
    assert body["coder_a"] == "alice"
    assert body["coder_b"] == "bob"
    assert (body["both"], body["only_a"], body["only_b"], body["neither"]) == (1, 1, 1, 1)

    # Two-coder request still works: same shape, single pair, alpha == pair.
    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "bob", "coder_b": "carol", "coders": ["bob", "carol"]},
    )
    assert res.status_code == 200, res.text
    body2 = res.json()
    assert body2["n_coders"] == 2
    assert len(body2["pairs"]) == 1
    assert body2["pairs"][0]["coder_a"] == "bob"
    assert body2["pairs"][0]["coder_b"] == "carol"
    assert body2["pairs"][0]["gwet_ac1"] == 1
    assert body2["kappa"] is None
    assert body2["krippendorff"] is None
    assert body2["alpha"] is None

    # Without `coders` the report defaults to every coder with codings.
    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "alice", "coder_b": "bob"},
    )
    assert res.status_code == 200, res.text
    defaulted = res.json()
    assert defaulted["n_coders"] == 3
    assert len(defaulted["pairs"]) == 3
    assert defaulted["alpha"] == pytest.approx(7 / 18, abs=0.0001)

    # Too few coders in the explicit list is rejected.
    res = await client.post(
        "/api/v1/reports/interrater",
        json={"coder_a": "alice", "coder_b": "bob", "coders": ["alice"]},
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
