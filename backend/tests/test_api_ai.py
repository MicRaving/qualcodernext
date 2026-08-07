"""AI feature gate API tests — status, settings roundtrip, chat, semantic search.

The router is mounted here directly (the orchestrator router.py will mount it
once merged) and the HTTP layer is faked by monkeypatching ``AsyncClient`` in
``qualcoder_api.services.ai_service`` — no network is ever touched.
"""

from __future__ import annotations

import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.ai import router as ai_router
from qualcoder_api.main import app
from qualcoder_api.services import ai_service as ai_service_module
from qualcoder_api.services import user_settings

app.include_router(ai_router, prefix="/api/v1")


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
    """The status tests assert the DEFAULTS — keep the developer's real
    AI settings (enabled provider, key) out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "ai.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def import_text(client, name: str = "ai.txt", text: str = "Hello world.") -> None:
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": (name, text, "text/plain")},
        data={"owner": "tester"},
    )
    assert res.status_code == 200, res.text


# ----------------------------------------------------------------------
# Status & settings
# ----------------------------------------------------------------------

async def test_status_defaults(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/ai/status")
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    assert body["configured"] is True
    assert body["reason"] == ""
    assert body["provider"] == "ollama"
    assert body["base_url"] == "http://localhost:11434/v1"
    assert body["model"] == "llama3.2"


async def test_cloud_provider_requires_api_key(project_client, tmp_path, monkeypatch):
    """Cloud providers without a key must report a clear reason instead of
    hitting the provider and surfacing a raw 400."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    client, _ = project_client
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "gemini",
            "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash",
            "api_key": "",
        },
    )
    assert res.status_code == 200, res.text
    res = await client.get("/api/v1/ai/status")
    body = res.json()
    assert body["configured"] is False
    assert "API key" in body["reason"]

    # A key present → configured again.
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "gemini",
            "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash",
            "api_key": "k",
        },
    )
    body = (await client.get("/api/v1/ai/status")).json()
    assert body["configured"] is True
    assert body["provider"] == "gemini"


async def test_settings_roundtrip(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "api_base": "http://localhost:9999/v1",
            "model": "m",
            "api_key": "k",
        },
    )
    assert res.status_code == 200, res.text
    stored = res.json()
    assert stored["enabled"] is True
    assert stored["api_base"] == "http://localhost:9999/v1"
    assert stored["model"] == "m"

    res = await client.get("/api/v1/ai/status")
    body = res.json()
    assert body["enabled"] is True
    assert body["model"] == "m"
    assert body["provider"] == "custom"
    assert body["base_url"] == "http://localhost:9999/v1"


async def test_settings_persist_to_disk(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "api_base": "http://localhost:1234/v1",
            "model": "persist-model",
        },
    )
    assert res.status_code == 200, res.text
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["ai"] == {
        "enabled": True,
        "provider": "custom",
        "api_base": "http://localhost:1234/v1",
        "model": "persist-model",
        "api_key": "",
        "mcp_permissions": "read",
    }


# ----------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------

async def test_chat_success(project_client, monkeypatch):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "Hi from fake"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "Hi from fake"
    assert body["model"] == "llama3.2"

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"].endswith("/chat/completions")
    assert "hello" in str(call["json"])
    assert call["json"]["messages"][1] == {"role": "user", "content": "hello"}


async def test_chat_with_context(project_client, monkeypatch):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hello", "context": "Some context"}
    )
    assert res.status_code == 200, res.text
    user_message = fake.calls[0]["json"]["messages"][1]
    assert user_message["content"] == "Some context\n\nhello"


async def test_chat_unreachable(project_client, monkeypatch):
    client, _ = project_client
    patch_client(monkeypatch, {"/chat/completions": httpx.ConnectError("boom")})
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 503
    assert "unreachable" in res.json()["detail"]


async def test_chat_backend_error(project_client, monkeypatch):
    client, _ = project_client
    patch_client(
        monkeypatch,
        {"/chat/completions": FakeResponse({"error": {"message": "model not found"}}, 404)},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 503
    assert "AI backend error 404" in res.json()["detail"]


# ----------------------------------------------------------------------
# Semantic search
# ----------------------------------------------------------------------

async def test_semantic_search_returns_matching_chunks(project_client, monkeypatch):
    client, _ = project_client
    await import_text(client, text="The quick brown fox jumps over the lazy dog.")
    query_vec = [1.0, 0.0]
    chunk_vec = [0.9, 0.1]
    fake = patch_client(
        monkeypatch,
        {"/embeddings": {"data": [{"embedding": query_vec}, {"embedding": chunk_vec}]}},
    )
    res = await client.post("/api/v1/ai/search", json={"query": "fox"})
    assert res.status_code == 200, res.text
    results = res.json()["results"]
    assert len(results) == 1
    assert results[0]["file_name"] == "ai.txt"
    assert results[0]["score"] > 0.9

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"].endswith("/embeddings")
    payload = call["json"]
    assert payload["model"] == "llama3.2"
    assert len(payload["input"]) == 2
    assert payload["input"][0] == "fox"


async def test_semantic_search_unreachable(project_client, monkeypatch):
    client, _ = project_client
    await import_text(client, text="The quick brown fox jumps over the lazy dog.")
    patch_client(monkeypatch, {"/embeddings": httpx.ConnectError("boom")})
    res = await client.post("/api/v1/ai/search", json={"query": "fox"})
    assert res.status_code == 503
    assert "unreachable" in res.json()["detail"]
    assert "embeddings" in res.json()["detail"]


async def test_semantic_search_empty_project(project_client, monkeypatch):
    client, _ = project_client
    patch_client(monkeypatch, {"/embeddings": {"data": []}})
    res = await client.post("/api/v1/ai/search", json={"query": "fox"})
    assert res.status_code == 200, res.text
    assert res.json()["results"] == []
