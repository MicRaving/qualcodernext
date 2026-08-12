"""API domain tests — sources, codes, codings, cases, attributes, journals."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "domains.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


# ----------------------------------------------------------------------
# Sources & import
# ----------------------------------------------------------------------

async def test_import_text_file(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("interview.txt", "Hello world.\nSecond line.", "text/plain")},
        data={"owner": "tester"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "interview.txt"
    assert body["media_type"] == "text"
    assert body["mediapath"] == "/docs/interview.txt"
    assert "Hello world." in body["fulltext"]
    assert body["owner"] == "tester"


async def test_import_audio_creates_transcription(project_client):
    client, target = project_client
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("talk.mp3", b"ID3fake", "audio/mpeg")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["media_type"] == "audio"
    assert body["mediapath"] == "/audio/talk.mp3"
    assert body["av_text_id"] is not None
    assert (target / "audio" / "talk.mp3").exists()

    sources = (await client.get("/api/v1/sources")).json()
    names = [s["name"] for s in sources]
    # The transcript companion is hidden from the file list (the AV coder
    # shows it); the media source still links to it.
    assert "talk.mp3.txt" not in names
    media = next(s for s in sources if s["name"] == "talk.mp3")
    assert media["av_text_id"] is not None


async def test_import_duplicate_name_rejected(project_client):
    client, _ = project_client
    payload = {"file": ("dup.txt", "same name", "text/plain")}
    first = await client.post("/api/v1/sources/import", files=payload)
    assert first.status_code == 200
    second = await client.post("/api/v1/sources/import", files=payload)
    assert second.status_code == 409


async def test_link_external_file(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/link", json={"path": "C:/media/notes.txt", "owner": "tester"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["mediapath"] == "docs:C:/media/notes.txt"
    assert res.json()["media_type"] == "text"


async def test_pdf_source_reports_pdf_dispatch(project_client):
    """A .pdf under /docs/ is TEXT media type but dispatches to PDF coder."""
    from qualcoder_api.core.enums import is_pdf_filename

    client, _ = project_client
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("paper.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["media_type"] == "text"
    assert is_pdf_filename(body["name"]) is True


async def test_source_crud_via_api(project_client):
    client, _ = project_client
    await client.post(
        "/api/v1/sources/import", files={"file": ("a.txt", "content", "text/plain")}
    )
    listed = await client.get("/api/v1/sources")
    assert len(listed.json()) == 1
    sid = listed.json()[0]["id"]

    patched = await client.patch(f"/api/v1/sources/{sid}", json={"memo": "updated"})
    assert patched.json()["memo"] == "updated"

    got = await client.get(f"/api/v1/sources/{sid}")
    assert got.json()["memo"] == "updated"

    deleted = await client.delete(f"/api/v1/sources/{sid}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/sources/{sid}")).status_code == 404


async def test_import_creates_attribute_placeholders(project_client):
    client, _ = project_client
    await client.post(
        "/api/v1/attributes/types",
        json={"name": "Interviewee", "case_or_file": "file", "value_type": "text"},
    )
    await client.post(
        "/api/v1/sources/import", files={"file": ("b.txt", "content", "text/plain")}
    )
    values = (await client.get("/api/v1/attributes/values")).json()
    file_attrs = [v for v in values if v["attr_type"] == "file"]
    assert len(file_attrs) == 1
    assert file_attrs[0]["name"] == "Interviewee"
    assert file_attrs[0]["value"] == ""


# ----------------------------------------------------------------------
# Codes & categories
# ----------------------------------------------------------------------

async def test_code_tree_and_crud(project_client):
    client, _ = project_client
    cat = await client.post(
        "/api/v1/codes/categories", json={"name": "Theme", "owner": "tester"}
    )
    assert cat.status_code == 201
    catid = cat.json()["catid"]

    code = await client.post(
        "/api/v1/codes",
        json={"name": "sub", "owner": "tester", "catid": catid, "color": "#FF0000"},
    )
    assert code.status_code == 201, code.text
    cid = code.json()["cid"]

    tree = (await client.get("/api/v1/codes")).json()
    kinds = [(t["kind"], t["id"], t["parent_id"]) for t in tree]
    assert ("category", catid, None) in kinds
    assert ("code", cid, catid) in kinds

    patched = await client.patch(f"/api/v1/codes/{cid}", json={"name": "sub2"})
    assert patched.json()["name"] == "sub2"

    assert (await client.delete(f"/api/v1/codes/{cid}")).status_code == 204
    assert (await client.delete(f"/api/v1/codes/categories/{catid}")).status_code == 204
    assert (await client.get("/api/v1/codes")).json() == []


async def test_code_tree_detaches_cycles(project_client, tmp_path):
    """Legacy/imported data can contain self-referencing or looping parent
    chains; the tree response must detach such items instead of looping.
    Category and code ids use separate sequences (upstream legacy), so a
    code whose ``catid`` equals its own ``cid`` must NOT be treated as a
    cycle — it legitimately nests under the category with that id."""
    import sqlite3

    client, target = project_client
    cat = await client.post(
        "/api/v1/codes/categories", json={"name": "Top", "owner": "tester"}
    )
    assert cat.status_code == 201
    catid = cat.json()["catid"]
    code = await client.post(
        "/api/v1/codes",
        json={"name": "nested", "owner": "tester", "catid": catid},
    )
    assert code.status_code == 201
    cid = code.json()["cid"]
    assert cid == catid == 1

    tree = (await client.get("/api/v1/codes")).json()
    nested = next(t for t in tree if t["kind"] == "code" and t["id"] == cid)
    assert nested["parent_id"] == catid

    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute("UPDATE code_name SET supercid = ? WHERE cid = ?", (cid, cid))
        conn.commit()
    tree = (await client.get("/api/v1/codes")).json()
    self_ref = next(t for t in tree if t["kind"] == "code" and t["id"] == cid)
    assert self_ref["parent_id"] is None


async def test_merge_codes_via_api(project_client):
    client, _ = project_client
    c1 = (await client.post("/api/v1/codes", json={"name": "one"})).json()
    c2 = (await client.post("/api/v1/codes", json={"name": "two"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("m.txt", "aaa bbb", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]
    await client.post(
        "/api/v1/codings/text",
        json={"cid": c1["cid"], "fid": fid, "seltext": "aaa", "pos0": 0, "pos1": 3},
    )
    res = await client.post(f"/api/v1/codes/{c1['cid']}/merge", json={"target_cid": c2["cid"]})
    assert res.status_code == 200, res.text
    codings = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert len(codings) == 1
    assert codings[0]["cid"] == c2["cid"]


# ----------------------------------------------------------------------
# Codings
# ----------------------------------------------------------------------

async def test_text_coding_roundtrip(project_client):
    client, _ = project_client
    code = (await client.post("/api/v1/codes", json={"name": "c"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("t.txt", "hello world", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]

    created = await client.post(
        "/api/v1/codings/text",
        json={"cid": code["cid"], "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    assert created.status_code == 201, created.text
    ctid = created.json()["ctid"]

    listed = await client.get(f"/api/v1/codings/text/{fid}")
    assert len(listed.json()) == 1

    patched = await client.patch(f"/api/v1/codings/text/{ctid}", json={"memo": "m1"})
    assert patched.json()["memo"] == "m1"

    bad = await client.post(
        "/api/v1/codings/text",
        json={"cid": code["cid"], "fid": fid, "seltext": "x", "pos0": 5, "pos1": 2},
    )
    assert bad.status_code == 422

    assert (await client.delete(f"/api/v1/codings/text/{ctid}")).status_code == 204


async def test_text_coding_patch_rejects_invalid_positions(project_client):
    client, _ = project_client
    code = (await client.post("/api/v1/codes", json={"name": "p"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("t.txt", "hello world", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]

    created = await client.post(
        "/api/v1/codings/text",
        json={"cid": code["cid"], "fid": fid, "seltext": "hello", "pos0": 0, "pos1": 5},
    )
    assert created.status_code == 201, created.text
    ctid = created.json()["ctid"]

    bad = await client.patch(f"/api/v1/codings/text/{ctid}", json={"pos0": 4, "pos1": 2})
    assert bad.status_code == 422

    single = await client.patch(f"/api/v1/codings/text/{ctid}", json={"pos0": 3})
    assert single.status_code == 200

    ok = await client.patch(f"/api/v1/codings/text/{ctid}", json={"pos0": 0, "pos1": 3})
    assert ok.status_code == 200
    assert ok.json()["pos0"] == 0
    assert ok.json()["pos1"] == 3


async def test_image_and_av_codings(project_client):
    client, _ = project_client
    code = (await client.post("/api/v1/codes", json={"name": "img"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("pic.png", b"\x89PNGfake", "image/png")}
    )
    sid = (await client.get("/api/v1/sources")).json()[0]["id"]

    img = await client.post(
        "/api/v1/codings/image",
        json={"id": sid, "x1": 1, "y1": 2, "width": 30, "height": 40, "cid": code["cid"]},
    )
    assert img.status_code == 201, img.text
    assert (await client.get(f"/api/v1/codings/image/{sid}")).json()[0]["width"] == 30

    av = await client.post(
        "/api/v1/codings/av",
        json={"id": sid, "pos0": 100, "pos1": 900, "cid": code["cid"]},
    )
    assert av.status_code == 201, av.text
    assert (await client.get(f"/api/v1/codings/av/{sid}")).json()[0]["pos0"] == 100


# ----------------------------------------------------------------------
# Cases / attributes / journals / annotations
# ----------------------------------------------------------------------

async def test_case_lifecycle(project_client):
    client, _ = project_client
    case = (await client.post("/api/v1/cases", json={"name": "P1", "owner": "tester"})).json()
    assert case["caseid"] > 0

    await client.post(
        "/api/v1/sources/import", files={"file": ("case.txt", "content", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]

    link = await client.post(
        f"/api/v1/cases/{case['caseid']}/files", json={"fid": fid, "owner": "tester"}
    )
    assert link.status_code == 201

    files = (await client.get(f"/api/v1/cases/{case['caseid']}/files")).json()
    assert [f["id"] for f in files] == [fid]

    span = await client.post(
        f"/api/v1/cases/{case['caseid']}/spans",
        json={"fid": fid, "pos0": 0, "pos1": 3, "owner": "tester"},
    )
    assert span.status_code == 201

    assert (await client.delete(f"/api/v1/cases/{case['caseid']}/files/{fid}")).status_code == 204
    assert (await client.get(f"/api/v1/cases/{case['caseid']}/files")).json() == []


async def test_attribute_types_and_values(project_client):
    client, _ = project_client
    created = await client.post(
        "/api/v1/attributes/types",
        json={"name": "Age", "owner": "tester", "case_or_file": "case", "value_type": "number"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["value_type"] == "number"

    case = (await client.post("/api/v1/cases", json={"name": "P1"})).json()
    setv = await client.put(
        f"/api/v1/attributes/values/Age?attr_type=case&entity_id={case['caseid']}",
        json={"value": "34", "owner": "tester"},
    )
    assert setv.status_code == 200, setv.text
    assert setv.json()["value"] == "34"

    values = (await client.get("/api/v1/attributes/values")).json()
    assert any(v["value"] == "34" for v in values)

    assert (await client.delete("/api/v1/attributes/types/Age")).status_code == 204
    values = (await client.get("/api/v1/attributes/values")).json()
    assert all(v["name"] != "Age" for v in values)


async def test_journal_crud(project_client):
    client, _ = project_client
    created = await client.post(
        "/api/v1/journals", json={"name": "Day 1", "jentry": "text here", "owner": "tester"}
    )
    assert created.status_code == 201
    jid = created.json()["jid"]

    patched = await client.patch(f"/api/v1/journals/{jid}", json={"jentry": "edited"})
    assert patched.json()["jentry"] == "edited"

    listed = (await client.get("/api/v1/journals")).json()
    assert len(listed) == 1

    assert (await client.delete(f"/api/v1/journals/{jid}")).status_code == 204
    assert (await client.get("/api/v1/journals")).json() == []


async def test_annotation_crud(project_client):
    client, _ = project_client
    await client.post(
        "/api/v1/sources/import", files={"file": ("ann.txt", "some text", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]

    created = await client.post(
        "/api/v1/annotations",
        json={"fid": fid, "pos0": 0, "pos1": 4, "memo": "note", "owner": "tester"},
    )
    assert created.status_code == 201
    anid = created.json()["anid"]

    listed = (await client.get(f"/api/v1/annotations/{fid}")).json()
    assert len(listed) == 1

    patched = await client.patch(f"/api/v1/annotations/{anid}", json={"memo": "note2"})
    assert patched.json()["memo"] == "note2"

    assert (await client.delete(f"/api/v1/annotations/{anid}")).status_code == 204
    assert (await client.get(f"/api/v1/annotations/{fid}")).json() == []


async def test_annotation_patch_rejects_invalid_positions(project_client):
    client, _ = project_client
    await client.post(
        "/api/v1/sources/import", files={"file": ("ann.txt", "some text", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]

    created = await client.post(
        "/api/v1/annotations",
        json={"fid": fid, "pos0": 0, "pos1": 4, "memo": "note", "owner": "tester"},
    )
    assert created.status_code == 201
    anid = created.json()["anid"]

    bad = await client.patch(f"/api/v1/annotations/{anid}", json={"pos0": 6, "pos1": 3})
    assert bad.status_code == 422

    single = await client.patch(f"/api/v1/annotations/{anid}", json={"pos0": 2})
    assert single.status_code == 200

    ok = await client.patch(f"/api/v1/annotations/{anid}", json={"pos0": 1, "pos1": 4})
    assert ok.status_code == 200
    assert ok.json()["pos0"] == 1
    assert ok.json()["pos1"] == 4


# ----------------------------------------------------------------------
# Coding engine endpoints
# ----------------------------------------------------------------------

async def test_autocode_endpoint_roundtrip(project_client):
    client, _ = project_client
    code = (await client.post("/api/v1/codes", json={"name": "ac"})).json()
    await client.post(
        "/api/v1/sources/import", files={"file": ("a.txt", "cat dog cat", "text/plain")}
    )
    fid = (await client.get("/api/v1/sources")).json()[0]["id"]

    res = await client.post(
        "/api/v1/codings/autocode",
        json={"fid": fid, "cid": code["cid"], "find_texts": ["cat"], "mode": "all"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["count"] == 2
    assert [c["pos0"] for c in body["created"]] == [0, 8]

    listed = (await client.get(f"/api/v1/codings/text/{fid}")).json()
    assert len(listed) == 2
    assert [c["seltext"] for c in listed] == ["cat", "cat"]

    bad = await client.post(
        "/api/v1/codings/autocode",
        json={"fid": fid, "cid": code["cid"], "find_texts": ["["], "use_regex": True},
    )
    assert bad.status_code == 422


async def test_shift_positions_endpoint(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/codings/shift-positions",
        json={
            "prev_text": "I read books",
            "new_text": "I read big books",
            "codings": [{"ctid": 1, "pos0": 7, "pos1": 12}],
            "annotations": [],
            "case_text": [],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["codings"][0]["newpos0"] == 11
    assert body["codings"][0]["newpos1"] == 16
    assert body["deletions"] == {"code_text": [], "annotation": [], "case_text": []}


async def test_domains_require_open_project(tmp_path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/v1/sources")
        assert res.status_code == 409
        res = await c.get("/api/v1/codes")
        assert res.status_code == 409
