"""In-app help API tests — bundled topics, topic content, and search.

The router is mounted here directly (the orchestrator router.py will mount it
once merged). Help needs no project, so the plain app client is enough.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.help import router as help_router
from qualcoder_api.main import app

app.include_router(help_router, prefix="/api/v1")

TOPIC_IDS = ["ai", "cases", "coders", "files", "notes", "reports", "workspace"]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_topics_list_nonempty_with_all_ids(client):
    res = await client.get("/api/v1/help/topics")
    assert res.status_code == 200, res.text
    topics = res.json()["topics"]
    assert len(topics) >= len(TOPIC_IDS)
    assert {t["id"] for t in topics} == set(TOPIC_IDS)
    for topic in topics:
        assert topic["title"]
        assert topic["description"]


async def test_topic_returns_full_content_and_title(client):
    res = await client.get("/api/v1/help/topic/files")
    assert res.status_code == 200, res.text
    topic = res.json()["topic"]
    assert topic["id"] == "files"
    # Markdown escapes are resolved at load time so the docs render as
    # proper markdown (no literal ``\&``).
    assert topic["title"] == "Files & Import"
    assert topic["content"].startswith("# Files & Import")
    assert "Supported Primary Files" in topic["content"]


async def test_topic_unknown_is_404(client):
    res = await client.get("/api/v1/help/topic/nope")
    assert res.status_code == 404
    assert res.json()["detail"] == "unknown topic"


async def test_search_literal_returns_matching_topic_with_snippet(client):
    res = await client.get("/api/v1/help/search", params={"q": "whisper"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["query"] == "whisper"
    assert body["results"]
    ids = {r["id"] for r in body["results"]}
    assert "coders" in ids
    assert "whisper" in body["results"][0]["snippet"].lower()


async def test_search_literal_is_case_insensitive(client):
    res = await client.get("/api/v1/help/search", params={"q": "WHISPER"})
    assert res.status_code == 200, res.text
    ids = {r["id"] for r in res.json()["results"]}
    assert "coders" in ids


async def test_search_regex_uses_regex_semantics(client):
    res = await client.get(
        "/api/v1/help/search", params={"q": "wor[a-z]+", "regex": "true"}
    )
    assert res.status_code == 200, res.text
    ids = {r["id"] for r in res.json()["results"]}
    assert "workspace" in ids


async def test_search_empty_query_is_422(client):
    res = await client.get("/api/v1/help/search", params={"q": "   "})
    assert res.status_code == 422
    assert "empty" in res.json()["detail"]


async def test_search_invalid_regex_is_422(client):
    res = await client.get("/api/v1/help/search", params={"q": "[", "regex": "true"})
    assert res.status_code == 422
    assert "invalid regex" in res.json()["detail"]


async def test_search_unescaped_star_is_wildcard(client):
    """A bare ``*`` matches any run of characters (workspac* = "workspac" +
    anything), not a quantifier making the trailing char optional."""
    res = await client.get("/api/v1/help/search", params={"q": "workspac*", "regex": "true"})
    assert res.status_code == 200, res.text
    ids = {r["id"] for r in res.json()["results"]}
    assert "workspace" in ids


async def test_search_escaped_star_is_literal(client):
    """An escaped ``\\*`` stays a literal asterisk."""
    res = await client.get("/api/v1/help/search", params={"q": r"workspac\*", "regex": "true"})
    assert res.status_code == 200, res.text
    # No topic contains the literal "workspac*", so nothing matches.
    assert res.json()["results"] == []
