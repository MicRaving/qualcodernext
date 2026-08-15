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
    # The companion is created empty at import time, so the media file has
    # no REAL transcript yet and stays eligible for transcription.
    assert media["has_transcript"] is False


async def test_source_list_has_transcript_flag(project_client):
    """has_transcript is true only when the linked companion has text."""
    import sqlite3

    client, target = project_client
    media = await client.post(
        "/api/v1/sources/import",
        files={"file": ("clip.mp4", b"\x00" * 64, "video/mp4")},
    )
    assert media.status_code == 200, media.text
    media_id = media.json()["id"]

    # An empty companion stays "no real transcript" (re-transcription ok).
    listed = (await client.get("/api/v1/sources")).json()
    row = next(s for s in listed if s["id"] == media_id)
    assert row["av_text_id"] is not None
    assert row["has_transcript"] is False

    # Link a companion with real text -> has_transcript becomes true.
    tx = await client.post(
        "/api/v1/sources/import",
        files={"file": ("clip.txt", "hello transcript", "text/plain")},
    )
    assert tx.status_code == 200, tx.text
    tx_id = tx.json()["id"]
    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute("UPDATE source SET av_text_id = ? WHERE id = ?", (tx_id, media_id))
        conn.commit()
    listed = (await client.get("/api/v1/sources")).json()
    row = next(s for s in listed if s["id"] == media_id)
    assert row["has_transcript"] is True

    # A whitespace-only companion is not a real transcript either.
    blank = await client.post(
        "/api/v1/sources/import",
        files={"file": ("clip2.txt", "  \n\t ", "text/plain")},
    )
    assert blank.status_code == 200, blank.text
    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute("UPDATE source SET av_text_id = ? WHERE id = ?", (blank.json()["id"], media_id))
        conn.commit()
    listed = (await client.get("/api/v1/sources")).json()
    row = next(s for s in listed if s["id"] == media_id)
    assert row["has_transcript"] is False


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


async def test_pdf_text_locate_maps_selection_to_plain_text_offsets(project_client):
    """Selections made over a rendered PDF page resolve to offsets in the
    extracted plain text (whitespace differences included)."""
    import fitz

    client, _ = project_client

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello pdf world")
    pdf_bytes = doc.tobytes()

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("located.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    # Exact text (pdf.js reconstruction with spaces).
    r = await client.post(
        f"/api/v1/sources/{sid}/pdf-text-locate",
        json={"page": 1, "text": "hello pdf"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["seltext"] == "hello pdf"
    assert body["pos1"] == body["pos0"] + len("hello pdf")

    # Whitespace-differing selection still maps (word-sequence fallback).
    r2 = await client.post(
        f"/api/v1/sources/{sid}/pdf-text-locate",
        json={"page": 1, "text": "hello   pdf   world"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["seltext"] == "hello pdf world"

    # Out-of-range page / non-PDF source / empty selection are rejected.
    assert (
        await client.post(
            f"/api/v1/sources/{sid}/pdf-text-locate",
            json={"page": 99, "text": "hello"},
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/sources/{sid}/pdf-text-locate",
            json={"page": 1, "text": "   "},
        )
    ).status_code == 422


async def test_pdf_text_locate_normalized_fallbacks(project_client):
    """Selections whose pdf.js-side text differs from the extracted page
    text by case, ligatures, soft hyphens or line-break hyphenation still
    map onto the right offsets (normalized fallback)."""
    import fitz

    client, _ = project_client

    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="f0", fontfile="C:/Windows/Fonts/arial.ttf")
    page.insert_text((72, 80), "in\u00adter\u00adnet", fontname="f0")
    page.insert_text((72, 100), "some-")
    page.insert_text((72, 110), "thing")
    page.insert_text((72, 130), "fi fl ff ffi ffl")
    page.insert_text((72, 150), "Hello World Example")
    pdf_bytes = doc.tobytes()

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("normalized.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    def locate(text: str):
        return client.post(
            f"/api/v1/sources/{sid}/pdf-text-locate",
            json={"page": 1, "text": text},
        )

    # Soft hyphens in the extracted page text vs. plain letters in the
    # pdf.js-side selection (and vice versa).
    r = await locate("internet")
    assert r.status_code == 200, r.text
    assert r.json()["seltext"] == "in\u00adter\u00adnet"
    assert r.json()["confidence"] == "normalized"
    r = await locate("in\u00adter\u00adnet")
    assert r.status_code == 200, r.text
    assert r.json()["seltext"] == "in\u00adter\u00adnet"

    # Line-break hyphenation: pdf.js joins "some-" / "thing" as one word.
    r = await locate("something")
    assert r.status_code == 200, r.text
    assert r.json()["seltext"] == "some-\nthing"
    assert r.json()["confidence"] == "normalized"

    # Ligature glyphs (U+FB00..FB04) vs. expanded letter pairs.
    r = await locate("\ufb01 \ufb02 \ufb00 \ufb03 \ufb04")
    assert r.status_code == 200, r.text
    assert r.json()["seltext"] == "fi fl ff ffi ffl"
    assert r.json()["confidence"] == "normalized"
    # The reverse direction (page has the glyphs) is covered by the same
    # normalization; the page text here has the pairs, so a ligature
    # selection must map onto the whole line.
    assert r.json()["pos1"] == r.json()["pos0"] + len("fi fl ff ffi ffl")

    # Case-insensitive matching.
    r = await locate("hello world example")
    assert r.status_code == 200, r.text
    assert r.json()["seltext"] == "Hello World Example"
    assert r.json()["confidence"] == "normalized"


async def test_pdf_text_locate_fuzzy_anchor(project_client):
    """When even normalized matching fails (e.g. a typo in the selection or
    OCR-ish differences), a best-effort positional estimate is returned with
    ``confidence: "fuzzy"`` anchored on the page's first word."""
    import fitz

    client, _ = project_client

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "The quick brown fox jumps over the lazy dog")
    pdf_bytes = doc.tobytes()

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("fuzzy.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    r = await client.post(
        f"/api/v1/sources/{sid}/pdf-text-locate",
        json={"page": 1, "text": "The quick brovn fox"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confidence"] == "fuzzy"
    assert body["seltext"] == "The quick brown fox"
    assert body["pos1"] == body["pos0"] + len("The quick brown fox")

    # The exact/normalized paths still report their confidence levels.
    r = await client.post(
        f"/api/v1/sources/{sid}/pdf-text-locate",
        json={"page": 1, "text": "The quick"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["confidence"] == "exact"
    r = await client.post(
        f"/api/v1/sources/{sid}/pdf-text-locate",
        json={"page": 1, "text": "the   quick"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["confidence"] == "normalized"


async def test_pdf_text_locate_unanchorable_page_still_422(project_client):
    """A page with no extractable text cannot anchor anything — the fuzzy
    fallback has nothing to work with and the request still 422s."""
    import fitz

    client, _ = project_client

    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    page2 = doc[1]
    page2.insert_text((72, 100), "text on page two")
    pdf_bytes = doc.tobytes()

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("blank.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    sid = res.json()["id"]

    # Blank page 1: nothing to anchor on.
    r = await client.post(
        f"/api/v1/sources/{sid}/pdf-text-locate",
        json={"page": 1, "text": "anything at all"},
    )
    assert r.status_code == 422

    # Page 2 still locates normally (offsets include the blank page's zero
    # length, so the result stays consistent).
    r = await client.post(
        f"/api/v1/sources/{sid}/pdf-text-locate",
        json={"page": 2, "text": "text on page two"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["confidence"] == "exact"


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


async def test_delete_media_source_deletes_transcript_companion(project_client):
    """Deleting an audio/video source also deletes its transcript companion
    (``av_text_id``) — including the companion's own codings — and the audit
    records both deletes."""
    client, _ = project_client
    media = (
        await client.post(
            "/api/v1/sources/import", files={"file": ("talk.mp3", b"ID3fake", "audio/mpeg")}
        )
    ).json()
    media_id = media["id"]
    companion_id = media["av_text_id"]
    assert companion_id is not None

    # Add a coding to the transcript so the companion has data to cascade.
    code = (
        await client.post("/api/v1/codes", json={"name": "theme", "owner": "tester"})
    ).json()
    coding = await client.post(
        "/api/v1/codings/text",
        json={"cid": code["cid"], "fid": companion_id, "seltext": "hello",
              "pos0": 0, "pos1": 5, "owner": "tester"},
    )
    assert coding.status_code == 201, coding.text

    assert (await client.delete(f"/api/v1/sources/{media_id}")).status_code == 204

    # Both the media source and the companion are gone.
    assert (await client.get(f"/api/v1/sources/{media_id}")).status_code == 404
    assert (await client.get(f"/api/v1/sources/{companion_id}")).status_code == 404

    # The companion's codings are gone with it.
    codings = (await client.get(f"/api/v1/codings/text/{companion_id}")).json()
    assert codings == []

    # Audit records both deletes.
    rows = (await client.get("/api/v1/audit", params={"action": "source.delete"})).json()["rows"]
    ids = [r["entity_id"] for r in rows]
    assert media_id in ids
    assert companion_id in ids
    companion_row = next(r for r in rows if r["entity_id"] == companion_id)
    assert companion_row["source_id"] == media_id
    assert companion_row["detail"]["row"]["name"] == "talk.mp3.txt"


async def test_delete_media_source_without_transcript(project_client, tmp_path):
    """A media file whose companion was already removed deletes plainly —
    no orphan cleanup step and exactly one audit row."""
    import sqlite3

    client, target = project_client
    media = (
        await client.post(
            "/api/v1/sources/import", files={"file": ("clip.mp4", b"\x00" * 64, "video/mp4")}
        )
    ).json()
    media_id = media["id"]
    companion_id = media["av_text_id"]
    assert companion_id is not None

    # Simulate a project without a transcript: drop the companion and clear
    # the link (as DELETE /sources/{id}/transcript leaves it).
    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute("DELETE FROM source WHERE id = ?", (companion_id,))
        conn.execute("UPDATE source SET av_text_id = NULL WHERE id = ?", (media_id,))
        conn.commit()

    assert (await client.delete(f"/api/v1/sources/{media_id}")).status_code == 204
    assert (await client.get(f"/api/v1/sources/{media_id}")).status_code == 404

    rows = (await client.get("/api/v1/audit", params={"action": "source.delete"})).json()["rows"]
    assert [r["entity_id"] for r in rows] == [media_id]


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


async def test_attribute_type_value_labels_roundtrip(project_client):
    client, _ = project_client
    labels = {"m": "Male", "f": "Female", "d": "Diverse"}
    created = await client.post(
        "/api/v1/attributes/types",
        json={
            "name": "Gender", "owner": "tester", "case_or_file": "case",
            "value_type": "text", "value_labels": labels,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["value_labels"] == labels

    listed = (await client.get("/api/v1/attributes/types")).json()
    row = next(t for t in listed if t["name"] == "Gender")
    assert row["value_labels"] == labels

    # Types created without labels default to {}.
    plain = await client.post(
        "/api/v1/attributes/types",
        json={"name": "Age", "owner": "tester", "case_or_file": "case"},
    )
    assert plain.status_code == 201
    assert plain.json()["value_labels"] == {}


async def test_attribute_values_unaffected_by_value_labels(project_client):
    """Raw values stay as stored; labels are presentation-only."""
    client, _ = project_client
    created = await client.post(
        "/api/v1/attributes/types",
        json={
            "name": "Gender", "owner": "tester", "case_or_file": "case",
            "value_type": "text", "value_labels": {"m": "Male", "f": "Female"},
        },
    )
    assert created.status_code == 201, created.text

    case = (await client.post("/api/v1/cases", json={"name": "P1"})).json()
    setv = await client.put(
        f"/api/v1/attributes/values/Gender?attr_type=case&entity_id={case['caseid']}",
        json={"value": "m", "owner": "tester"},
    )
    assert setv.status_code == 200, setv.text
    assert setv.json()["value"] == "m"

    # A free-text value not in the list is stored raw too.
    setv = await client.put(
        f"/api/v1/attributes/values/Gender?attr_type=case&entity_id={case['caseid']}",
        json={"value": "prefer not to say", "owner": "tester"},
    )
    assert setv.status_code == 200, setv.text
    assert setv.json()["value"] == "prefer not to say"


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
        json={"fid": fid, "cids": [code["cid"]], "find_texts": ["cat"], "mode": "all"},
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
        json={"fid": fid, "cids": [code["cid"]], "find_texts": ["["], "use_regex": True},
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
