"""Tests for the document comparison chart.

Pure-algorithm tests on compare_service plus endpoint tests over a
synthetic project (two files with known codings — same setup style as
test_api_stats.py).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.core.models import Code, Coding
from qualcoder_api.main import app
from qualcoder_api.services.compare_service import (
    align,
    code_sequence,
    compare_documents,
    dice_coefficient,
    lcs_length,
    lcs_pairs,
)


@pytest.fixture(scope="session", autouse=True)
def _wire_compare_router():
    """The supervisor includes the compare router into api/v1/router.py;
    until that happens, wire it into the test app here so the endpoint
    tests run standalone (a no-op once router.py is updated)."""
    from qualcoder_api.api.v1.compare import router as compare_router

    def _paths(routes):
        found = set()
        for r in routes:
            path = getattr(r, "path", None)
            if isinstance(path, str):
                found.add(path)
            inner = getattr(r, "routes", None)
            if inner:
                found |= _paths(inner)
        return found

    if "/api/v1/compare" not in _paths(app.routes):
        app.include_router(compare_router, prefix="/api/v1")


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the developer's real user settings out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def compare_client(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "compare.qda"
        res = await c.post(
            "/api/v1/projects",
            json={"project_path": str(target), "codername": "tester"},
        )
        assert res.status_code == 200, res.text
        yield c
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def compare_dataset(compare_client):
    """Files a/b/c; a = [C1, C2, C1], b = [C2, C1], c uncoded."""
    client = compare_client

    async def import_file(name, text):
        res = await client.post(
            "/api/v1/sources/import",
            files={"file": (name, text, "text/plain")},
        )
        assert res.status_code == 200, res.text
        return res.json()["id"]

    f1 = await import_file("a.txt", "alpha beta\ngamma delta epsilon")
    f2 = await import_file("b.txt", "one two\nthree four")
    f3 = await import_file("c.txt", "nothing coded here")

    cids = {}
    for name in ("C1", "C2"):
        res = await client.post("/api/v1/codes", json={"name": name})
        assert res.status_code == 201, res.text
        cids[name] = res.json()["cid"]

    async def code(fid, name, text, pos0, pos1):
        res = await client.post(
            "/api/v1/codings/text",
            json={
                "cid": cids[name], "fid": fid, "seltext": text,
                "pos0": pos0, "pos1": pos1,
            },
        )
        assert res.status_code == 201, res.text
        return res.json()["ctid"]

    await code(f1, "C1", "alpha", 0, 5)
    await code(f1, "C2", "beta", 6, 10)
    await code(f1, "C1", "gamma", 11, 16)
    await code(f2, "C2", "one", 0, 3)
    await code(f2, "C1", "two", 4, 7)

    return {"f1": f1, "f2": f2, "f3": f3, "cids": cids}


# ----------------------------------------------------------------------
# Pure LCS / alignment algorithms
# ----------------------------------------------------------------------


def test_lcs_length_known_sequences():
    assert lcs_length([1, 2, 3], [2, 3]) == 2
    assert lcs_length([1, 2, 3], [1, 2, 3]) == 3
    assert lcs_length([1, 2, 3], [4, 5, 6]) == 0
    assert lcs_length([], [1]) == 0
    assert lcs_length([1, 1, 1], [1, 1]) == 2


def test_lcs_pairs_matches_length():
    for a, b in (
        ([1, 2, 3], [2, 3]),
        ([1, 2, 1], [2, 1]),
        ([1, 1, 2, 2, 1, 1], [1, 2, 1]),
        ([3, 1, 4, 1, 5], [1, 1, 4]),
    ):
        pairs = lcs_pairs(a, b)
        assert len(pairs) == lcs_length(a, b)
        # Matches are ordered and equal on both sides.
        assert [a[i] for i, _ in pairs] == [b[j] for _, j in pairs]
        assert [i for i, _ in pairs] == sorted(i for i, _ in pairs)
        assert [j for _, j in pairs] == sorted(j for _, j in pairs)


def test_align_shifts_unaligned_runs_into_gaps():
    pairs = lcs_pairs([1, 2, 3], [2, 3])
    rows = align([1, 2, 3], [2, 3], pairs)
    assert rows == [(0, None), (1, 0), (2, 1)]
    # Concatenating the non-None sides reproduces the inputs in order.
    assert [[1, 2, 3][i] for i, _ in rows if i is not None] == [1, 2, 3]
    assert [[2, 3][j] for _, j in rows if j is not None] == [2, 3]


def test_align_reproduces_sequences():
    a = [1, 2, 3, 4, 5]
    b = [2, 5, 4]
    rows = align(a, b, lcs_pairs(a, b))
    assert [a[i] for i, _ in rows if i is not None] == a
    assert [b[j] for _, j in rows if j is not None] == b
    aligned = [r for r in rows if r[0] is not None and r[1] is not None]
    assert aligned == [(1, 0), (3, 2)]


def test_dice_coefficient():
    assert dice_coefficient([1, 2], [2, 3]) == pytest.approx(0.5)  # 2*1/4
    assert dice_coefficient([1, 2], [3, 4]) == 0.0
    assert dice_coefficient([1, 2], [1, 2]) == 1.0
    assert dice_coefficient([1], [1, 1]) == 1.0  # sets, not multisets
    assert dice_coefficient([], []) == 0.0


# ----------------------------------------------------------------------
# Sequence construction (overlap handling)
# ----------------------------------------------------------------------


def _coding(ctid, cid, pos0, pos1):
    return Coding(
        ctid=ctid, cid=cid, fid=1, seltext="", pos0=pos0, pos1=pos1,
        owner="tester",
    )


def test_code_sequence_keeps_first_code_of_overlapping_run():
    codings = [
        _coding(1, 10, 0, 10),
        _coding(2, 20, 5, 20),   # overlaps (1) — skipped
        _coding(3, 30, 15, 25),  # overlaps (1) — skipped
        _coding(4, 40, 30, 40),  # new run
    ]
    seq = code_sequence(codings)
    assert [c.cid for c in seq] == [10, 40]
    assert [c.ctid for c in seq] == [1, 4]


def test_code_sequence_sorts_by_position():
    seq = code_sequence([_coding(1, 20, 20, 30), _coding(2, 10, 0, 10)])
    assert [c.cid for c in seq] == [10, 20]


# ----------------------------------------------------------------------
# Document-level assembly
# ----------------------------------------------------------------------


def test_compare_documents_shape():
    codes = {
        1: Code(cid=1, name="C1", color="#ff0000"),
        2: Code(cid=2, name="C2", color="#00ff00"),
    }
    a = [_coding(1, 1, 0, 5), _coding(2, 2, 6, 10), _coding(3, 1, 11, 16)]
    b = [_coding(4, 2, 0, 3), _coding(5, 1, 4, 7)]
    body = compare_documents(a, b, codes)

    assert [p["cid"] for p in body["seq1"]] == [1, 2, 1]
    assert [p["cid"] for p in body["seq2"]] == [2, 1]
    assert body["seq1"][0]["code_name"] == "C1"
    assert body["seq1"][0]["color"] == "#ff0000"
    assert body["seq1"][0]["aligned"] is False  # first C1 is unaligned
    assert body["seq1"][1]["aligned"] is True

    # Rows: unaligned run of a shifts into the gap before the match.
    assert [r["aligned"] for r in body["rows"]] == [False, True, True]
    assert body["rows"][0]["a"]["cid"] == 1
    assert body["rows"][0]["b"] is None
    assert body["rows"][1]["a"]["cid"] == 2
    assert body["rows"][1]["b"]["cid"] == 2
    assert body["rows"][2]["a"]["cid"] == 1
    assert body["rows"][2]["b"]["cid"] == 1

    assert body["similarity"]["dice"] == 1.0
    assert body["similarity"]["lcs"] == 2
    assert body["similarity"]["sequence"] == pytest.approx(2 * 2 / 5)

    by_cid = {e["cid"]: e for e in body["cooccurrence"]}
    assert by_cid[1]["count1"] == 2
    assert by_cid[1]["count2"] == 1
    assert by_cid[1]["matched"] == 1
    assert by_cid[2]["count1"] == 1
    assert by_cid[2]["count2"] == 1
    assert by_cid[2]["matched"] == 1


def test_compare_documents_unknown_code_falls_back():
    body = compare_documents(
        [_coding(1, 99, 0, 5)],
        [_coding(2, 99, 0, 5)],
        {},
    )
    assert body["seq1"][0]["code_name"] == ""
    assert body["seq1"][0]["color"] == "#ffffff"
    assert body["similarity"]["dice"] == 1.0


# ----------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------


async def test_compare_endpoint(compare_client, compare_dataset):
    client = compare_client
    res = await client.get(
        "/api/v1/compare",
        params={"fid1": compare_dataset["f1"], "fid2": compare_dataset["f2"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fid1"] == compare_dataset["f1"]
    assert body["fid2"] == compare_dataset["f2"]
    assert body["file1"] == "a.txt"
    assert body["file2"] == "b.txt"
    assert [p["code_name"] for p in body["seq1"]] == ["C1", "C2", "C1"]
    assert [p["code_name"] for p in body["seq2"]] == ["C2", "C1"]
    assert [r["aligned"] for r in body["rows"]] == [False, True, True]
    assert body["similarity"]["dice"] == 1.0
    assert body["similarity"]["lcs"] == 2
    assert body["similarity"]["sequence"] == pytest.approx(0.8)
    assert [e["name"] for e in body["cooccurrence"]] == ["C1", "C2"]


async def test_compare_endpoint_missing_fid(compare_client):
    client = compare_client
    res = await client.get("/api/v1/compare", params={"fid1": 1})
    assert res.status_code == 422


async def test_compare_endpoint_unknown_source(compare_client, compare_dataset):
    client = compare_client
    res = await client.get(
        "/api/v1/compare",
        params={"fid1": compare_dataset["f1"], "fid2": 9999},
    )
    assert res.status_code == 422
    assert "not found" in res.json()["detail"]


async def test_compare_endpoint_same_source(compare_client, compare_dataset):
    client = compare_client
    res = await client.get(
        "/api/v1/compare",
        params={"fid1": compare_dataset["f1"], "fid2": compare_dataset["f1"]},
    )
    assert res.status_code == 422


async def test_compare_endpoint_uncoded_source(compare_client, compare_dataset):
    client = compare_client
    res = await client.get(
        "/api/v1/compare",
        params={"fid1": compare_dataset["f1"], "fid2": compare_dataset["f3"]},
    )
    assert res.status_code == 422
    assert "no text codings" in res.json()["detail"]


async def test_compare_endpoint_reflects_new_codings(compare_client, compare_dataset):
    """A coding added after the first comparison shows up in the next one."""
    client = compare_client
    f3 = compare_dataset["f3"]
    cids = compare_dataset["cids"]
    res = await client.post(
        "/api/v1/codings/text",
        json={
            "cid": cids["C1"], "fid": f3, "seltext": "nothing",
            "pos0": 0, "pos1": 7,
        },
    )
    assert res.status_code == 201, res.text
    res = await client.get(
        "/api/v1/compare",
        params={"fid1": compare_dataset["f1"], "fid2": f3},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [p["code_name"] for p in body["seq2"]] == ["C1"]
