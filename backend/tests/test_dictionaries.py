"""Word dictionary tests — CRUD, autocoding, frequency matrix and import."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from qualcoder_api.main import app
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodeRepository, SourceRepository
from qualcoder_api.services import dictionary_service
from qualcoder_api.services.coding_service import autocode
from qualcoder_api.services.project_service import ProjectService


@pytest.fixture
async def project_session(tmp_path: Path):
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "dict.qda"), codername="tester")
    assert svc.session_factory is not None
    async with svc.session_factory() as session:
        yield session
    await svc.close_project()


@pytest.fixture
async def client():
    from qualcoder_api.api.v1.dictionaries import router as dictionaries_router

    # The supervisor wires the dictionaries router into router.py; tests
    # register it directly so the API layer is exercised standalone.
    if not any(
        getattr(r, "path", None) == "/api/v1/dictionaries" for r in app.routes
    ):
        app.include_router(dictionaries_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed(session, text: str, name: str = "doc.txt"):
    return await SourceRepository(session).add_source(
        name=name, mediapath=f"/docs/{name}", fulltext=text, owner="tester"
    )


async def _code(session, name: str) -> int:
    code = await CodeRepository(session).add_code(name=name, owner="tester")
    return code.cid


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_crud_roundtrip(project_session):
    session = project_session
    dictionary = await dictionary_service.create_dictionary(session, "Emotions", "tester")
    assert dictionary is not None
    assert dictionary["name"] == "Emotions"
    assert dictionary["owner"] == "tester"
    assert dictionary["entries"] == []

    entry = await dictionary_service.add_entry(session, dictionary["id"], "happy", "joy")
    assert entry is not None
    assert entry["code_name"] == "happy"
    assert entry["term"] == "joy"

    renamed = await dictionary_service.rename_dictionary(session, dictionary["id"], "Feelings")
    assert renamed is not None
    assert renamed["name"] == "Feelings"

    listed = {d["name"]: d for d in await dictionary_service.list_dictionaries(session)}
    assert "Feelings" in listed
    assert len(listed["Feelings"]["entries"]) == 1

    assert await dictionary_service.delete_dictionary(session, dictionary["id"]) is True
    assert await dictionary_service.delete_dictionary(session, dictionary["id"]) is False
    assert await dictionary_service.list_dictionaries(session) == []


async def test_duplicate_dictionary_name_rejected(project_session):
    session = project_session
    await dictionary_service.create_dictionary(session, "A", "tester")
    assert await dictionary_service.create_dictionary(session, "A", "tester") is None


async def test_rename_to_taken_name_rejected(project_session):
    session = project_session
    first = await dictionary_service.create_dictionary(session, "A", "tester")
    await dictionary_service.create_dictionary(session, "B", "tester")
    assert first is not None
    assert await dictionary_service.rename_dictionary(session, first["id"], "B") is None


async def test_entry_uniqueness(project_session):
    session = project_session
    dictionary = await dictionary_service.create_dictionary(session, "D", "tester")
    assert dictionary is not None
    assert await dictionary_service.add_entry(session, dictionary["id"], "c", "term1") is not None
    assert (
        await dictionary_service.add_entry(session, dictionary["id"], "c", "term1")
        == "duplicate"
    )
    # Same term under another code is still a duplicate (term is unique per dict).
    assert (
        await dictionary_service.add_entry(session, dictionary["id"], "other", "term1")
        == "duplicate"
    )
    assert await dictionary_service.add_entry(session, 9999, "c", "term2") is None
    assert await dictionary_service.remove_entry(session, 99999) is False


# ---------------------------------------------------------------------------
# Dictionary autocode
# ---------------------------------------------------------------------------


async def test_dictionary_autocode_matches_manual_autocode(project_session):
    """The dictionary run must produce exactly the codings a manual
    multi-term autocode over the same texts produces."""
    session = project_session
    source = await _seed(session, "cat dog cat bird cat", "a.txt")
    second = await _seed(session, "dog only here", "b.txt")
    cat_cid = await _code(session, "animal")
    bird_cid = await _code(session, "bird")

    # Manual equivalent: the dictionary matches each code's own terms
    # (the autocode engine applies every find_text to every code).
    manual_a = await autocode(
        session,
        fid=None,
        cids=[cat_cid],
        find_texts=["cat", "dog"],
        mode="all",
        owner="manual",
    )
    manual_b = await autocode(
        session,
        fid=None,
        cids=[bird_cid],
        find_texts=["bird"],
        mode="all",
        owner="manual",
    )
    assert manual_a["count"] + manual_b["count"] == 6  # catx3 + dogx2 + birdx1

    dictionary = await dictionary_service.create_dictionary(session, "Dict", "tester")
    assert dictionary is not None
    await dictionary_service.add_entry(session, dictionary["id"], "animal", "cat")
    await dictionary_service.add_entry(session, dictionary["id"], "animal", "dog")
    await dictionary_service.add_entry(session, dictionary["id"], "bird", "bird")

    result = await dictionary_service.dictionary_autocode(
        session, dictionary_id=dictionary["id"], owner="dict"
    )
    assert result is not None
    assert result["total"] == 6
    by_code = {r["code_name"]: r["count"] for r in result["per_code"]}
    assert by_code == {"animal": 5, "bird": 1}
    assert result["unmatched_codes"] == []
    assert result["skipped_terms"] == []

    # Identical coded spans (fid, pos0, pos1, cid) as the manual run.
    rows = (
        await session.execute(
            select(
                tables.code_text.c.owner, tables.code_text.c.fid, tables.code_text.c.pos0,
                tables.code_text.c.pos1, tables.code_text.c.cid,
            )
        )
    ).all()
    by_owner: dict[str, set[tuple[int, int, int, int]]] = {}
    for owner, fid, pos0, pos1, cid in rows:
        by_owner.setdefault(owner, set()).add((fid, pos0, pos1, cid))
    assert len(by_owner["manual"]) == len(by_owner["dict"]) == 6
    assert by_owner["manual"] == by_owner["dict"]
    assert {fid for fid, *_ in by_owner["dict"]} == {source.id, second.id}


async def test_dictionary_autocode_whole_word_case_insensitive(project_session):
    session = project_session
    await _seed(session, "Cat category CAT. cat.", "a.txt")
    await _code(session, "animal")
    dictionary = await dictionary_service.create_dictionary(session, "D", "tester")
    assert dictionary is not None
    await dictionary_service.add_entry(session, dictionary["id"], "animal", "Cat")

    result = await dictionary_service.dictionary_autocode(
        session, dictionary_id=dictionary["id"], owner="tester"
    )
    assert result is not None
    # "category" must NOT match; case-insensitive "Cat" -> "cat", "CAT", "cat".
    assert result["total"] == 3
    created = (
        await session.execute(
            select(tables.code_text).order_by(tables.code_text.c.pos0)
        )
    ).all()
    assert [c.seltext for c in created] == ["Cat", "CAT", "cat"]


async def test_dictionary_autocode_source_scope(project_session):
    session = project_session
    await _seed(session, "alpha beta", "a.txt")
    other = await _seed(session, "alpha beta", "b.txt")
    await _code(session, "c")
    dictionary = await dictionary_service.create_dictionary(session, "D", "tester")
    assert dictionary is not None
    await dictionary_service.add_entry(session, dictionary["id"], "c", "alpha")

    result = await dictionary_service.dictionary_autocode(
        session, dictionary_id=dictionary["id"], owner="tester", source_ids=[other.id]
    )
    assert result is not None
    assert result["total"] == 1
    coded = (await session.execute(select(tables.code_text))).all()
    assert [c.fid for c in coded] == [other.id]


async def test_dictionary_autocode_skips_missing_codes(project_session):
    session = project_session
    await _seed(session, "alpha beta", "a.txt")
    await _code(session, "real")
    dictionary = await dictionary_service.create_dictionary(session, "D", "tester")
    assert dictionary is not None
    await dictionary_service.add_entry(session, dictionary["id"], "real", "alpha")
    await dictionary_service.add_entry(session, dictionary["id"], "ghost", "beta")

    result = await dictionary_service.dictionary_autocode(
        session, dictionary_id=dictionary["id"], owner="tester"
    )
    assert result is not None
    assert result["total"] == 1
    assert result["unmatched_codes"] == ["ghost"]
    assert result["skipped_terms"] == ["beta"]

    assert await dictionary_service.dictionary_autocode(
        session, dictionary_id=9999, owner="tester"
    ) is None


# ---------------------------------------------------------------------------
# Frequency matrix
# ---------------------------------------------------------------------------


async def test_frequencies_counts_and_totals(project_session):
    session = project_session
    await _seed(session, "cat dog cat\ncat", "a.txt")
    await _seed(session, "dog", "b.txt")
    await _seed(session, "cat dog", "c.txt")
    dictionary = await dictionary_service.create_dictionary(session, "D", "tester")
    assert dictionary is not None
    await dictionary_service.add_entry(session, dictionary["id"], "c", "cat")
    await dictionary_service.add_entry(session, dictionary["id"], "c", "dog")
    await dictionary_service.add_entry(session, dictionary["id"], "c", "the")

    matrix = await dictionary_service.dictionary_frequencies(session, dictionary["id"])
    assert matrix is not None
    # "the" is an English stopword -> excluded by default.
    assert matrix["terms"] == ["cat", "dog"]
    assert matrix["total"] == 7  # catx4 + dogx3
    assert matrix["column_totals"] == [4, 3]
    by_file = {r["file"]: r for r in matrix["rows"]}
    assert by_file["a.txt"]["counts"] == [3, 1]
    assert by_file["a.txt"]["total"] == 4
    assert by_file["b.txt"]["counts"] == [0, 1]
    assert by_file["c.txt"]["counts"] == [1, 1]


async def test_frequencies_stopwords_off(project_session):
    session = project_session
    await _seed(session, "the cat", "a.txt")
    dictionary = await dictionary_service.create_dictionary(session, "D", "tester")
    assert dictionary is not None
    await dictionary_service.add_entry(session, dictionary["id"], "c", "the")
    matrix = await dictionary_service.dictionary_frequencies(
        session, dictionary["id"], use_stopwords=False
    )
    assert matrix is not None
    assert matrix["terms"] == ["the"]
    assert matrix["total"] == 1


async def test_frequencies_normalize_percent(project_session):
    session = project_session
    await _seed(session, "cat cat dog", "a.txt")
    dictionary = await dictionary_service.create_dictionary(session, "D", "tester")
    assert dictionary is not None
    await dictionary_service.add_entry(session, dictionary["id"], "c", "cat")
    await dictionary_service.add_entry(session, dictionary["id"], "c", "dog")

    matrix = await dictionary_service.dictionary_frequencies(
        session, dictionary["id"], normalize=True
    )
    assert matrix is not None
    row = matrix["rows"][0]
    assert row["counts"] == [66.7, 33.3]
    assert row["total"] == 100.0
    assert matrix["column_totals"] == [66.7, 33.3]
    assert matrix["total"] == 100.0

    assert await dictionary_service.dictionary_frequencies(session, 9999) is None


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def test_parse_dictionary_text():
    parsed = dictionary_service.parse_dictionary_text(
        "# comment\n\nanimal,cat,dog\n  bird,parrot\nplant,\ntree\n"
    )
    assert parsed == {"animal": ["cat", "dog"], "bird": ["parrot"], "plant": ["tree"]}


async def test_import_creates_and_extends_dictionary(project_session):
    session = project_session
    result = await dictionary_service.import_dictionary(
        session, "Imported", "animal,cat,dog\nbird,parrot", "tester"
    )
    assert result["created"] is True
    assert result["added"] == 3
    assert result["skipped"] == 0
    dict_id = result["dictionary"]["id"]

    again = await dictionary_service.import_dictionary(
        session, "Imported", "animal,cat\nbird,eagle", "tester"
    )
    assert again["created"] is False
    assert again["added"] == 1  # eagle
    assert again["skipped"] == 1  # cat duplicate
    entries = await dictionary_service.get_dictionary(session, dict_id)
    assert entries is not None
    assert [e["term"] for e in entries["entries"]] == ["cat", "dog", "parrot", "eagle"]


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------


async def test_api_crud_and_autocode(client, tmp_path):
    target = tmp_path / "api_dict.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
    )
    assert res.status_code == 200
    # Two codes…
    for name in ("animal", "bird"):
        assert (
            await client.post("/api/v1/codes", json={"name": name})
        ).status_code == 201
    # Two text sources…
    for fname, text in (("a.txt", "cat dog cat bird"), ("b.txt", "dog cat")):
        assert (
            await client.post(
                "/api/v1/sources/import",
                files={"file": (fname, io.BytesIO(text.encode()), "text/plain")},
            )
        ).status_code == 200

    # Dictionary CRUD.
    created = await client.post(
        "/api/v1/dictionaries", json={"name": "Dict"}
    )
    assert created.status_code == 201
    dict_id = created.json()["id"]

    dup = await client.post("/api/v1/dictionaries", json={"name": "Dict"})
    assert dup.status_code == 409

    e1 = await client.post(
        f"/api/v1/dictionaries/{dict_id}/entries",
        json={"code_name": "animal", "term": "cat"},
    )
    assert e1.status_code == 201
    e2 = await client.post(
        f"/api/v1/dictionaries/{dict_id}/entries",
        json={"code_name": "animal", "term": "dog"},
    )
    assert e2.status_code == 201
    assert (
        await client.post(
            f"/api/v1/dictionaries/{dict_id}/entries",
            json={"code_name": "bird", "term": "bird"},
        )
    ).status_code == 201
    # Duplicate term -> 409.
    dup_entry = await client.post(
        f"/api/v1/dictionaries/{dict_id}/entries",
        json={"code_name": "animal", "term": "cat"},
    )
    assert dup_entry.status_code == 409

    listed = await client.get("/api/v1/dictionaries")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert len(listed.json()[0]["entries"]) == 3

    renamed = await client.patch(f"/api/v1/dictionaries/{dict_id}", json={"name": "R"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "R"

    # Dictionary autocode via the API.
    auto = await client.post(
        "/api/v1/codings/dictionary-autocode",
        json={"dictionary_id": dict_id},
    )
    assert auto.status_code == 201, auto.text
    body = auto.json()
    assert body["total"] == 6  # catx3 + dogx2 + birdx1
    assert {c["code_name"]: c["count"] for c in body["per_code"]} == {
        "animal": 5,
        "bird": 1,
    }
    assert body["unmatched_codes"] == []

    # Frequencies endpoint.
    freq = await client.get(f"/api/v1/dictionaries/{dict_id}/frequencies")
    assert freq.status_code == 200
    assert freq.json()["total"] == 6
    assert freq.json()["terms"] == ["cat", "dog", "bird"]

    # 404s.
    assert (await client.get("/api/v1/dictionaries/999/frequencies")).status_code == 404
    assert (
        await client.post(
            "/api/v1/codings/dictionary-autocode", json={"dictionary_id": 999}
        )
    ).status_code == 404

    # Entry delete + dictionary delete.
    assert (
        await client.delete(f"/api/v1/dictionaries/entries/{e2.json()['id']}")
    ).status_code == 204
    assert (await client.delete(f"/api/v1/dictionaries/{dict_id}")).status_code == 204
    assert (await client.get("/api/v1/dictionaries")).json() == []


async def test_api_import_upload(client, tmp_path):
    target = tmp_path / "api_import.qda"
    assert (
        await client.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
    ).status_code == 200

    content = "# dictionary\nanimal,cat,dog\nbird,parrot\n"
    res = await client.post(
        "/api/v1/dictionaries/import",
        files={"file": ("words.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["created"] is True
    assert body["added"] == 3
    assert body["dictionary"]["name"] == "words"

    listed = await client.get("/api/v1/dictionaries")
    entries = listed.json()[0]["entries"]
    assert {e["term"] for e in entries} == {"cat", "dog", "parrot"}

    # Audit trail recorded.
    audit = await client.get("/api/v1/audit")
    actions = [a["action"] for a in audit.json()["rows"]]
    assert "dictionary.import" in actions
