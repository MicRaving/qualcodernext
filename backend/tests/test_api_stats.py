"""API tests for the statistical analysis suite endpoints.

Synthetic project: two files, three codes, codings with memos, three
cases (one file linked to two of them), case and file attributes.
"""

from __future__ import annotations

import math

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the developer's real user settings out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def stats_client(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "stats.qda"
        res = await c.post(
            "/api/v1/projects",
            json={"project_path": str(target), "codername": "tester"},
        )
        assert res.status_code == 200, res.text
        yield c
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def stats_dataset(stats_client):
    """Files a/b, codes C1..C3, three cases, case + file attributes."""
    client = stats_client

    async def import_file(name, text):
        res = await client.post(
            "/api/v1/sources/import",
            files={"file": (name, text, "text/plain")},
        )
        assert res.status_code == 200, res.text
        return res.json()["id"]

    f1 = await import_file("a.txt", "alpha beta\ngamma delta")
    f2 = await import_file("b.txt", "epsilon zeta\neta theta")

    cids = {}
    for name in ("C1", "C2", "C3"):
        res = await client.post("/api/v1/codes", json={"name": name})
        assert res.status_code == 201, res.text
        cids[name] = res.json()["cid"]

    async def code(fid, name, text, pos0, pos1, memo=""):
        res = await client.post(
            "/api/v1/codings/text",
            json={
                "cid": cids[name], "fid": fid, "seltext": text,
                "pos0": pos0, "pos1": pos1, "memo": memo,
            },
        )
        assert res.status_code == 201, res.text
        return res.json()["ctid"]

    # f1: C1 twice (two memos) + C2; f2: C1 + C3.
    ctid_a = await code(f1, "C1", "alpha", 0, 5, "first")
    await code(f1, "C1", "beta", 6, 10, "extra")
    await code(f1, "C2", "gamma", 11, 16, "second")
    await code(f2, "C1", "epsilon", 0, 7, "third")
    await code(f2, "C3", "zeta", 8, 12, "fourth")

    async def make_case(name, fid):
        res = await client.post("/api/v1/cases", json={"name": name})
        assert res.status_code == 201, res.text
        caseid = res.json()["caseid"]
        res = await client.post(f"/api/v1/cases/{caseid}/files", json={"fid": fid})
        assert res.status_code == 201, res.text
        return caseid

    case1 = await make_case("CaseOne", f1)
    case2 = await make_case("CaseTwo", f2)
    case3 = await make_case("CaseThree", f2)

    async def attr_type(name, case_or_file, value_type):
        res = await client.post(
            "/api/v1/attributes/types",
            json={"name": name, "case_or_file": case_or_file, "value_type": value_type},
        )
        assert res.status_code == 201, res.text

    async def attr_value(name, attr_type, entity_id, value):
        res = await client.put(
            f"/api/v1/attributes/values/{name}?attr_type={attr_type}&entity_id={entity_id}",
            json={"value": value},
        )
        assert res.status_code == 200, res.text

    await attr_type("Region", "case", "text")
    await attr_type("Age", "case", "number")
    await attr_type("Kind", "file", "text")

    await attr_value("Region", "case", case1, "North")
    await attr_value("Region", "case", case2, "South")
    await attr_value("Region", "case", case3, "South")
    await attr_value("Age", "case", case1, "30")
    await attr_value("Age", "case", case2, "40")
    await attr_value("Age", "case", case3, "50")
    await attr_value("Kind", "file", f1, "pdf")
    await attr_value("Kind", "file", f2, "text")

    return {"f1": f1, "f2": f2, "cids": cids, "ctid_a": ctid_a}


async def test_crosstab_case_scope(stats_client, stats_dataset):
    client = stats_client
    res = await client.get("/api/v1/reports/crosstab", params={"attr_name": "Region"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "case"
    assert body["units_total"] == 3
    assert body["units_with_value"] == 3
    assert body["values"] == ["North", "South"]
    assert [c["name"] for c in body["codes"]] == ["C1", "C2", "C3"]
    # C1 present in all three cases (CaseTwo + CaseThree share f2); C2 only
    # CaseOne; C3 only CaseTwo/CaseThree.
    assert body["counts"] == [[1, 2], [1, 0], [0, 2]]
    assert body["row_totals"] == [3, 1, 2]
    assert body["col_totals"] == [2, 4]
    # Hand-computed: expected [[1,2],[1/3,2/3],[2/3,4/3]], chi2 = 3.0,
    # df = 2, p = Q(1, 1.5) = e^-1.5.
    stats = body["stats"]
    assert stats["chi2"] == pytest.approx(3.0, abs=1e-9)
    assert stats["df"] == 2
    assert stats["p"] == pytest.approx(math.e**-1.5, rel=1e-6)
    assert stats["yates"] is False
    assert stats["cramers_v"] == pytest.approx(
        math.sqrt(3.0 / (6 * min(2, 1))), abs=1e-9
    )


async def test_crosstab_file_scope(stats_client, stats_dataset):
    client = stats_client
    res = await client.get("/api/v1/reports/crosstab-file", params={"attr_name": "Kind"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "file"
    assert body["values"] == ["pdf", "text"]
    assert body["counts"] == [[1, 1], [1, 0], [0, 1]]


async def test_crosstab_restricted_codes_and_422(stats_client, stats_dataset):
    client = stats_client
    cids = stats_dataset["cids"]
    res = await client.get(
        "/api/v1/reports/crosstab",
        params={"attr_name": "Region", "codes": [cids["C1"], cids["C2"]]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [c["name"] for c in body["codes"]] == ["C1", "C2"]
    assert body["counts"] == [[1, 2], [1, 0]]

    # The case-scope endpoint rejects a file-scope attribute.
    res = await client.get("/api/v1/reports/crosstab", params={"attr_name": "Kind"})
    assert res.status_code == 422
    assert "file-scope" in res.json()["detail"]


async def test_group_compare(stats_client, stats_dataset):
    client = stats_client
    cids = stats_dataset["cids"]
    res = await client.get(
        "/api/v1/reports/group-compare",
        params={"attr_name": "Age", "cid": cids["C2"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code_name"] == "C2"
    assert body["scope"] == "case"
    assert body["skipped_non_numeric"] == 0
    # C2 present only in CaseOne (Age 30); absent in CaseTwo/Three (40, 50).
    assert body["present"]["count"] == 1
    assert body["present"]["mean"] == 30.0
    assert body["absent"]["count"] == 2
    assert body["absent"]["mean"] == 45.0
    assert body["absent"]["min"] == 40.0
    assert body["absent"]["max"] == 50.0
    # Ranks [1, 2, 3], U = 0 for the lone present value; P(U <= 0) = 1/3,
    # two-tailed p = 2/3.
    u = body["u"]
    assert u["method"] == "exact"
    assert u["u"] == pytest.approx(0.0, abs=1e-9)
    assert u["u1"] == pytest.approx(0.0, abs=1e-9)
    assert u["u2"] == pytest.approx(2.0, abs=1e-9)
    assert u["p"] == pytest.approx(2 / 3, abs=1e-9)


async def test_code_by_variable(stats_client, stats_dataset):
    client = stats_client
    res = await client.get("/api/v1/reports/code-by-variable", params={"attr_name": "Region"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "case"
    assert body["values"] == ["North", "South"]
    assert [c["name"] for c in body["codes"]] == ["C1", "C2", "C3"]
    # North = CaseOne (C1 x2, C2 x1); South = CaseTwo + CaseThree
    # (C1 x1 each, C3 x1 each).
    assert body["counts"] == [[2, 1, 0], [2, 0, 2]]
    assert body["col_totals"] == [4, 1, 2]
    chart = body["chart"]
    assert chart["kind"] == "stacked-values"
    assert [label["value"] for label in chart["labels"]] == ["North", "South"]
    assert chart["series"][0] == [
        {"cid": c["cid"], "count": n}
        for c, n in zip(body["codes"], body["counts"][0], strict=True)
    ]
    assert chart["series"][1] == [
        {"cid": c["cid"], "count": n}
        for c, n in zip(body["codes"], body["counts"][1], strict=True)
    ]


async def test_summary_table_file_scope(stats_client, stats_dataset):
    client = stats_client
    res = await client.get("/api/v1/reports/summary-table", params={"scope": "file"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "file"
    assert [c["name"] for c in body["codes"]] == ["C1", "C2", "C3"]
    rows = {r["name"]: r for r in body["rows"]}

    a = rows["a.txt"]
    assert a["cells"][0]["memo"] == "first — extra"
    assert a["cells"][0]["memo_count"] == 2
    items = a["cells"][0]["items"]
    assert [item["memo"] for item in items] == ["first", "extra"]
    assert all(item["kind"] == "text" for item in items)
    assert a["cells"][1]["memo"] == "second"
    assert a["cells"][1]["memo_count"] == 1
    assert a["cells"][2]["memo"] == ""
    assert a["cells"][2]["memo_count"] == 0

    b = rows["b.txt"]
    assert b["cells"][0]["memo"] == "third"
    assert b["cells"][2]["memo"] == "fourth"


async def test_summary_table_case_scope_and_filters(stats_client, stats_dataset):
    client = stats_client
    cids = stats_dataset["cids"]
    res = await client.get(
        "/api/v1/reports/summary-table",
        params={"scope": "case", "cids": [cids["C1"]]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "case"
    assert [c["name"] for c in body["codes"]] == ["C1"]
    rows = {r["name"]: r for r in body["rows"]}
    assert rows["CaseOne"]["cells"][0]["memo"] == "first — extra"
    assert rows["CaseTwo"]["cells"][0]["memo"] == "third"
    assert rows["CaseThree"]["cells"][0]["memo"] == "third"

    # File-scope with a file filter keeps only that file.
    f1 = stats_dataset["f1"]
    res = await client.get(
        "/api/v1/reports/summary-table",
        params={"scope": "file", "fids": [f1]},
    )
    body = res.json()
    assert [r["name"] for r in body["rows"]] == ["a.txt"]


async def test_summary_table_memo_edit_reflected(stats_client, stats_dataset):
    """Patching a coding memo through the regular codings endpoint shows up
    in the summary table (cells reuse the stored memos, no new storage)."""
    client = stats_client
    ctid = stats_dataset["ctid_a"]
    res = await client.patch(
        f"/api/v1/codings/text/{ctid}", json={"memo": "edited"}
    )
    assert res.status_code == 200, res.text
    res = await client.get("/api/v1/reports/summary-table", params={"scope": "file"})
    body = res.json()
    row = next(r for r in body["rows"] if r["name"] == "a.txt")
    assert row["cells"][0]["memo"] == "edited — extra"


async def test_summary_table_bad_scope(stats_client):
    client = stats_client
    res = await client.get(
        "/api/v1/reports/summary-table", params={"scope": "bogus"}
    )
    assert res.status_code == 422
