"""Regression tests for the core-services audit fixes."""
from __future__ import annotations

import math

import pytest

from qualcoder_api.interchange.nvivo_import import _build_node_tree
from qualcoder_api.services import stats_service


def test_exact_u_distribution_half_integer_ties():
    # Ranks 1, 2.5, 2.5, 4: picking two can give an odd doubled sum, i.e.
    # a half-integer U. Those subsets must be counted, not dropped.
    ranks = stats_service._rank_values([1.0, 2.0, 2.0, 3.0])
    dist = stats_service._exact_u_distribution(2, 2, ranks)
    assert sum(dist.values()) == math.comb(4, 2)
    assert any(u % 1 == 0.5 for u in dist)


def test_mann_whitney_all_tied_single_values():
    # Previously the whole distribution was dropped -> ZeroDivisionError.
    result = stats_service.mann_whitney_u([1.0], [1.0])
    assert result["method"] == "exact"
    assert result["u"] == 0.5
    assert result["p"] == 1.0


def test_mann_whitney_half_integer_p_matches_enumeration():
    x, y = [1.0, 2.0], [2.0, 3.0]
    result = stats_service.mann_whitney_u(x, y)
    # Enumerate the 6 equally likely splits of ranks [1, 2.5, 2.5, 4].
    from itertools import combinations

    ranks = stats_service._rank_values(x + y)
    us = [sum(ranks[i] for i in c) - 3 for c in combinations(range(4), 2)]
    u_obs = result["u"]
    p_lo = sum(1 for u in us if u <= u_obs) / len(us)
    p_hi = sum(1 for u in us if u >= u_obs) / len(us)
    assert result["p"] == min(1.0, 2 * min(p_lo, p_hi))


_CYCLIC_NODES = (
    "<Nodes><Node name='Root' guid='r'><Node name='A' guid='a'>"
    "<Node name='B' guid='b'><Node name='A' guid='a'/></Node>"
    "</Node></Node></Nodes>"
)


def test_nvivo_node_tree_can_contain_cycle():
    import xml.etree.ElementTree as etree

    recs = _build_node_tree([etree.fromstring(_CYCLIC_NODES)])
    by_name = {r.name: r for r in recs}
    # B lists A (its ancestor) as a child: the category import must cope.
    assert by_name["A"].key in by_name["B"].children


@pytest.fixture
async def nvivo_client(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from qualcoder_api.api.v1.importers import router as importers_router
    from qualcoder_api.main import app

    if not any(getattr(r, "path", "").endswith("/import/nvivo") for r in app.routes):
        app.include_router(importers_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        res = await c.post(
            "/api/v1/projects",
            json={"project_path": str(tmp_path / "audit.qda"), "codername": "tester"},
        )
        assert res.status_code == 200, res.text
        yield c
        await c.post("/api/v1/projects/close")


async def test_nvivo_import_survives_node_cycle(nvivo_client):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__nvivo/Nodes.xml", _CYCLIC_NODES)
    res = await nvivo_client.post(
        "/api/v1/interchange/import/nvivo",
        files={"file": ("cycle.nvpx", buffer.getvalue(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["categories"] == 3  # Root, A, B — each exactly once
