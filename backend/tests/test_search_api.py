"""Full-text search API tests — literal/regex scan with an optional category
filter, plus the category filter on the semantic search.

The AI layer is faked by monkeypatching ``AsyncClient`` in
``qualcoder_api.services.ai_service`` — no network is ever touched.
"""

from __future__ import annotations

import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import ai_service as ai_service_module


class FakeResponse:
    status_code = 200

    def __init__(self, payload, status_code=None):
        self._payload = payload
        if status_code is not None:
            self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeClient:
    """Records calls; serves payloads (or raises) per URL suffix."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                if isinstance(payload, Exception):
                    raise payload
                return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)
        return FakeResponse({"error": {"message": "no route matched"}})


def patch_client(monkeypatch, routes: dict[str, object]) -> FakeClient:
    fake = FakeClient(routes)
    monkeypatch.setattr(ai_service_module, "AsyncClient", lambda **kw: fake)
    return fake


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the developer's real AI settings out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "search.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def configured_ai(project_client):
    """A usable local AI provider — the lmstudio default has no pinned model,
    so semantic-search tests must set one explicitly."""
    client, _ = project_client
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": False,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "test-model",
            "api_key": "",
        },
    )
    assert res.status_code == 200, res.text
    return client


async def import_text(client, name: str, text: str) -> int:
    """Import one text source and return its id."""
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": (name, text, "text/plain")},
        data={"owner": "tester"},
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _create_category(client, name: str, supercatid: int | None = None) -> int:
    res = await client.post(
        "/api/v1/codes/categories", json={"name": name, "supercatid": supercatid}
    )
    assert res.status_code == 201, res.text
    return res.json()["catid"]


async def _create_code(client, name: str, catid: int) -> int:
    res = await client.post("/api/v1/codes", json={"name": name, "catid": catid})
    assert res.status_code == 201, res.text
    return res.json()["cid"]


def _insert_coding(target, cid: int, fid: int) -> None:
    """Insert a text coding row directly into the project DB."""
    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute(
            "INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date) "
            "VALUES (?,?,?,?,?,?,datetime('now'))",
            (cid, fid, "x", 0, 1, "tester"),
        )
        conn.commit()


async def search(client, query: str, **kwargs):
    return await client.post("/api/v1/search", json={"query": query, **kwargs})


# ----------------------------------------------------------------------
# Literal / regex full-text search
# ----------------------------------------------------------------------

async def test_search_literal_match(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "The quick brown fox jumps over the lazy dog.")
    res = await search(client, "fox")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["source_id"] == 1
    assert result["name"] == "alpha.txt"
    assert result["match_count"] == 1
    hit = result["hits"][0]
    assert hit["pos0"] == 16
    assert hit["pos1"] == 19
    assert "The quick brown fox jumps over the lazy dog." in hit["context"]
    # The match must be locatable inside the context slice (yellow highlight).
    assert hit["context"][hit["rel0"] : hit["rel1"]] == "fox"
    assert hit["rel1"] - hit["rel0"] == 3


async def test_search_literal_case_sensitive(project_client):
    """Literal mode is case-sensitive; a differently-cased match is ignored."""
    client, _ = project_client
    await import_text(client, "alpha.txt", "Hello world hello")
    res = await search(client, "hello")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["match_count"] == 1
    assert result["hits"][0]["pos0"] == 12


async def test_search_regex_case_insensitive_literal(project_client):
    """Regex mode with the ``(?i)`` inline flag gives a case-insensitive
    literal search."""
    client, _ = project_client
    await import_text(client, "alpha.txt", "Hello world hello")
    res = await search(client, r"(?i)hello", regex=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["match_count"] == 2
    assert [h["pos0"] for h in result["hits"]] == [0, 12]


async def test_search_regex(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "cat catalog scat")
    res = await search(client, r"\bc.t\b", regex=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["match_count"] == 1
    hit = result["hits"][0]
    assert hit["pos0"] == 0
    assert hit["pos1"] == 3
    assert hit["context"][hit["rel0"] : hit["rel1"]] == "cat"


async def test_search_unescaped_star_is_wildcard(project_client):
    """A bare ``*`` is a wildcard (LM* = "LM" + anything), so the M stays
    required instead of being an optional quantifier target."""
    client, _ = project_client
    await import_text(client, "alpha.txt", "LM star\nLM next\nL alone")
    res = await search(client, "LM*", regex=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    # "LM star" and "LM next" match; the standalone "L" (no M) must not.
    assert body["results"][0]["match_count"] == 2


async def test_search_escaped_star_is_literal(project_client):
    """An escaped ``\\*`` stays a literal asterisk."""
    client, _ = project_client
    await import_text(client, "alpha.txt", "a*b and ab")
    res = await search(client, r"a\*b", regex=True)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    # Only the literal "a*b" matches — "ab" (no star) is not included.
    assert body["results"][0]["match_count"] == 1


async def test_search_no_match(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "The quick brown fox.")
    res = await search(client, "missing")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 0
    assert body["results"] == []


async def test_search_hits_capped(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", " ".join(["needle"] * 7))
    res = await search(client, "needle")
    assert res.status_code == 200, res.text
    result = res.json()["results"][0]
    assert result["match_count"] == 7
    assert len(result["hits"]) == 5


async def test_search_pagination(project_client):
    client, _ = project_client
    for name in ("a.txt", "b.txt", "c.txt"):
        await import_text(client, name, f"term {name}")
    res = await search(client, "term", limit=2)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 3
    assert [r["name"] for r in body["results"]] == ["a.txt", "b.txt"]
    res = await search(client, "term", limit=2, offset=2)
    body = res.json()
    assert body["total"] == 3
    assert [r["name"] for r in body["results"]] == ["c.txt"]
    res = await search(client, "term", limit=0)
    assert res.status_code == 200, res.text
    assert len(res.json()["results"]) == 1


# ----------------------------------------------------------------------
# Category filter
# ----------------------------------------------------------------------

async def test_search_category_filter(project_client):
    client, target = project_client
    fid_a = await import_text(client, "alpha.txt", "needle in the haystack")
    fid_b = await import_text(client, "beta.txt", "needle somewhere else")
    cat = await _create_category(client, "Findings")
    subcat = await _create_category(client, "Findings:Sub", supercatid=cat)
    cid_a = await _create_code(client, "Code A", cat)
    cid_b = await _create_code(client, "Code B", subcat)
    _insert_coding(target, cid_a, fid_a)
    _insert_coding(target, cid_b, fid_b)

    res = await search(client, "needle")
    assert res.status_code == 200, res.text
    assert {r["name"] for r in res.json()["results"]} == {"alpha.txt", "beta.txt"}

    res = await search(client, "needle", category_id=cat)
    assert res.status_code == 200, res.text
    assert {r["name"] for r in res.json()["results"]} == {"alpha.txt", "beta.txt"}

    res = await search(client, "needle", category_id=subcat)
    assert res.status_code == 200, res.text
    assert [r["name"] for r in res.json()["results"]] == ["beta.txt"]

    other = await _create_category(client, "Other")
    res = await search(client, "needle", category_id=other)
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 0
    assert res.json()["results"] == []


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------

async def test_search_empty_query(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "some text")
    res = await search(client, "   ")
    assert res.status_code == 422
    assert "query" in res.json()["detail"]
    res = await search(client, "")
    assert res.status_code == 422


async def test_search_invalid_regex(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "some text")
    res = await search(client, "(", regex=True)
    assert res.status_code == 422
    assert "invalid regex" in res.json()["detail"]


# ----------------------------------------------------------------------
# Multi-entity search
# ----------------------------------------------------------------------

async def test_search_default_entities_scans_files(project_client):
    """Without an entities list the search covers every entity type; a plain
    project still returns the file match with the legacy shape (source_id)."""
    client, _ = project_client
    await import_text(client, "alpha.txt", "The quick brown fox jumps over the lazy dog.")
    res = await search(client, "fox")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["kind"] == "file"
    assert result["id"] == result["source_id"] == 1
    assert result["name"] == "alpha.txt"


async def test_search_entities_codes_and_categories(project_client):
    client, _ = project_client
    cat = await _create_category(client, "Findings")
    await _create_code(client, "Resilience", cat)
    await _create_code(client, "Coping", cat)

    res = await search(client, "Resilience", entities=["codes"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["kind"] == "code"
    assert result["name"] == "Resilience"
    assert result["source_id"] is None

    res = await search(client, "Findings", entities=["categories"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["kind"] == "category"
    assert result["name"] == "Findings"


async def test_search_entities_cases_and_journal(project_client):
    client, _ = project_client
    res = await client.post("/api/v1/cases", json={"name": "Interview A"})
    assert res.status_code == 201, res.text
    res = await client.post("/api/v1/journals", json={"name": "Day 1", "jentry": "raining heavily"})
    assert res.status_code == 201, res.text

    res = await search(client, "Interview", entities=["cases"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["results"][0]["kind"] == "case"
    assert body["results"][0]["name"] == "Interview A"

    res = await search(client, "raining", entities=["journal"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["results"][0]["kind"] == "journal"
    assert body["results"][0]["name"] == "Day 1"


async def test_search_entities_memos(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "some text")
    cid = await _create_code(client, "Resilience", None)
    res = await client.patch(f"/api/v1/codes/{cid}", json={"memo": "this is a code memo about strength"})
    assert res.status_code == 200, res.text

    res = await search(client, "strength", entities=["memos"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["kind"] == "memo"
    assert result["name"] == "Resilience (memo)"
    assert result["ref_kind"] == "code"
    assert result["ref_id"] == cid


async def test_search_entities_attributes_and_comments(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "some text")
    res = await client.post(
        "/api/v1/attributes/types",
        json={"name": "Age", "case_or_file": "case", "value_type": "number"},
    )
    assert res.status_code == 201, res.text
    res = await client.put(
        "/api/v1/attributes/values/Age",
        params={"attr_type": "case", "entity_id": 1},
        json={"value": "42"},
    )
    assert res.status_code == 200, res.text
    res = await client.post(
        "/api/v1/comments",
        json={"target_kind": "source", "target_id": 1, "body": "needs follow-up"},
    )
    assert res.status_code == 201, res.text

    res = await search(client, "42", entities=["attributes"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    assert body["results"][0]["kind"] == "attribute"
    assert "42" in body["results"][0]["name"]

    res = await search(client, "follow-up", entities=["comments"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    result = body["results"][0]
    assert result["kind"] == "comment"
    assert result["ref_kind"] == "source"
    assert result["ref_id"] == 1


async def test_search_entities_unknown_is_422(project_client):
    client, _ = project_client
    await import_text(client, "alpha.txt", "some text")
    res = await search(client, "x", entities=["bogus"])
    assert res.status_code == 422
    assert "unknown entity" in res.json()["detail"]


async def test_search_entities_result_order(project_client):
    """Results are ordered by entity type (stable order) then id."""
    client, _ = project_client
    await import_text(client, "zeta.txt", "needle file")
    await _create_code(client, "needle code", None)
    await _create_category(client, "needle category")

    res = await search(client, "needle")
    assert res.status_code == 200, res.text
    kinds = [r["kind"] for r in res.json()["results"]]
    assert kinds == ["file", "code", "category"]


# ----------------------------------------------------------------------
# Semantic search category filter
# ----------------------------------------------------------------------

async def test_ai_search_category_filter(project_client, monkeypatch, configured_ai):
    client, target = project_client
    fid_a = await import_text(client, "alpha.txt", "The quick brown fox jumps over the lazy dog.")
    fid_b = await import_text(client, "beta.txt", "A quick fox in the field.")
    cat = await _create_category(client, "Wildlife")
    cid = await _create_code(client, "Fox", cat)
    _insert_coding(target, cid, fid_a)

    query_vec = [1.0, 0.0]
    fake = patch_client(
        monkeypatch,
        {"/embeddings": {"data": [{"embedding": query_vec}, {"embedding": query_vec}]}},
    )
    res = await client.post(
        "/api/v1/ai/search", json={"query": "fox", "category_id": cat}
    )
    assert res.status_code == 200, res.text
    results = res.json()["results"]
    assert len(results) == 1
    assert results[0]["file_name"] == "alpha.txt"
    assert len(fake.calls) == 1
    payload = fake.calls[0]["json"]
    assert len(payload["input"]) == 2
    assert payload["input"][1] == "The quick brown fox jumps over the lazy dog."

    fake = patch_client(
        monkeypatch,
        {"/embeddings": {"data": [{"embedding": query_vec}, {"embedding": query_vec}]}},
    )
    res = await client.post(
        "/api/v1/ai/search",
        json={"query": "fox", "category_id": cat, "source_ids": [fid_a, fid_b]},
    )
    assert res.status_code == 200, res.text
    results = res.json()["results"]
    assert [r["file_name"] for r in results] == ["alpha.txt"]
    payload = fake.calls[0]["json"]
    assert len(payload["input"]) == 2

    other = await _create_category(client, "Other")
    fake = patch_client(
        monkeypatch,
        {"/embeddings": {"data": [{"embedding": query_vec}, {"embedding": query_vec}]}},
    )
    res = await client.post(
        "/api/v1/ai/search", json={"query": "fox", "category_id": other}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["results"] == []
    assert body["indexed"] is False
    assert fake.calls == []
