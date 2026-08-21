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
    """Records calls; serves payloads (or raises) per URL suffix.

    A route value may be a single payload/exception or a list of them served
    in order (used by the agentic-chat tests where one turn spans several
    model calls).
    """

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
                if isinstance(payload, list):
                    if not payload:
                        return FakeResponse({"error": {"message": "no more payloads"}})
                    payload = payload.pop(0)
                if isinstance(payload, Exception):
                    raise payload
                return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)
        return FakeResponse({"error": {"message": "no route matched"}})


class FakeGetClient(FakeClient):
    """FakeClient variant that answers GET requests (the /models listings)."""

    async def get(self, url: str, **kwargs):
        self.calls.append({"url": url, "headers": kwargs.get("headers", {})})
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


@pytest.fixture
async def configured_ai(project_client):
    """Configure a usable local AI provider (the lmstudio default has no
    pinned model, so chat/semantic tests must set one explicitly). ``enabled``
    stays off: it gates project-context injection in chat, and these tests
    assert on the exact request payloads."""
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
    assert body["configured"] is False
    assert body["reason"] != ""
    assert body["provider"] == "lmstudio"
    assert body["base_url"] == "http://127.0.0.1:1234/v1"
    assert body["model"] == ""
    # The wrapping prompt resolves to the built-in default when unset.
    assert body["wrapping_prompt"] == user_settings.DEFAULT_WRAPPING_PROMPT


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
        "auto_start_backend": True,
        "mcp_permissions": "read",
        "wrapping_prompt": "",
        "mcp_mode": "internal",
        "mcp_server_command": "",
        "mcp_server_args": [],
        "mcp_server_env": {},
    }


async def test_save_settings_empty_api_key_keeps_stored_key(
    project_client, tmp_path, monkeypatch
):
    """A blank api_key in the save request must not wipe the stored key —
    the settings UI never reads the key back, so blank means "unchanged"."""
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)

    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "api_base": "http://localhost:9999/v1",
            "model": "m",
            "api_key": "topsecret",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["api_key"] == "topsecret"

    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "api_base": "http://localhost:9999/v1",
            "model": "m2",
            "api_key": "",
        },
    )
    body = res.json()
    assert body["model"] == "m2"
    assert body["api_key"] == "topsecret"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["ai"]["api_key"] == "topsecret"

    # A real key still replaces the stored one.
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "api_base": "http://localhost:9999/v1",
            "model": "m",
            "api_key": "newkey",
        },
    )
    assert res.json()["api_key"] == "newkey"


async def test_wrapping_prompt_roundtrip_and_default(project_client):
    """The wrapping prompt defaults to the built-in text, saves a custom one,
    and a blank save resets it back to the default."""
    client, _ = project_client

    res = await client.get("/api/v1/ai/wrapping-prompt")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == user_settings.DEFAULT_WRAPPING_PROMPT
    assert body["default"] == user_settings.DEFAULT_WRAPPING_PROMPT

    res = await client.put(
        "/api/v1/ai/wrapping-prompt", json={"text": "Be very terse."}
    )
    assert res.status_code == 200, res.text
    assert res.json()["text"] == "Be very terse."

    res = await client.get("/api/v1/ai/wrapping-prompt")
    assert res.json()["text"] == "Be very terse."

    # Blank resets to the built-in default.
    res = await client.put("/api/v1/ai/wrapping-prompt", json={"text": "  "})
    assert res.status_code == 200, res.text
    assert res.json()["text"] == user_settings.DEFAULT_WRAPPING_PROMPT


async def test_wrapping_prompt_survives_settings_autosave(project_client):
    """The settings tab's auto-save (no wrapping_prompt key) must not clobber
    a custom wrapping prompt set in the template creator."""
    client, _ = project_client
    res = await client.put(
        "/api/v1/ai/wrapping-prompt", json={"text": "Keep it crisp."}
    )
    assert res.status_code == 200, res.text

    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "m",
            "api_key": "",
            "mcp_permissions": "read",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["wrapping_prompt"] == "Keep it crisp."

    res = await client.get("/api/v1/ai/wrapping-prompt")
    assert res.json()["text"] == "Keep it crisp."


async def test_chat_system_prompt_includes_wrapping(project_client, monkeypatch, configured_ai):
    """The wrapping prompt is appended to the mode persona in every chat turn."""
    client, _ = project_client
    await client.put(
        "/api/v1/ai/wrapping-prompt", json={"text": "Answer in one sentence."}
    )
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 200, res.text
    system = fake.calls[0]["json"]["messages"][0]["content"]
    assert system.startswith("You are a research assistant")
    assert "Answer in one sentence." in system


def test_save_ai_settings_blank_key_preserves_stored(monkeypatch, tmp_path):
    """Service-level: save_ai_settings keeps the stored key on a blank one."""
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    settings = {
        "ai": {
            "enabled": True,
            "provider": "custom",
            "api_base": "http://localhost:9999/v1",
            "model": "m",
            "api_key": "keepme",
            "mcp_permissions": "read",
        }
    }
    out = user_settings.save_ai_settings(
        {
            "enabled": True,
            "provider": "custom",
            "api_base": "http://localhost:9999/v1",
            "model": "m2",
            "api_key": "",
        },
        settings,
    )
    assert out["api_key"] == "keepme"


async def test_mcp_permissions_endpoint(project_client):
    """The AI-sidebar toggle changes only the MCP access level and persists."""
    client, _ = project_client

    res = await client.put(
        "/api/v1/ai/mcp-permissions", json={"mcp_permissions": "write"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["mcp_permissions"] == "write"

    status = await client.get("/api/v1/ai/status")
    assert status.json()["mcp_permissions"] == "write"

    res = await client.put(
        "/api/v1/ai/mcp-permissions", json={"mcp_permissions": "nope"}
    )
    assert res.status_code == 422


async def test_mcp_tools_endpoint(project_client):
    """The AI sidebar lists the MCP tools, gated by the access level."""
    client, _ = project_client

    # Read-only default: write tools present but flagged disabled.
    res = await client.get("/api/v1/ai/mcp-tools")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["permissions"] == "read"
    assert body["write_enabled"] is False
    assert body["read_tools"]
    assert any(t["name"] == "get_code_tree" for t in body["read_tools"])

    # Write access: write tools are enabled.
    await client.put("/api/v1/ai/mcp-permissions", json={"mcp_permissions": "write"})
    res = await client.get("/api/v1/ai/mcp-tools")
    assert res.json()["write_enabled"] is True
    assert any(t["name"] == "create_code" for t in res.json()["write_tools"])


# ----------------------------------------------------------------------
# Model listings & provider probes
# ----------------------------------------------------------------------

async def configure_gemini(client, monkeypatch, tmp_path, api_key="secret") -> None:
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "gemini",
            "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash",
            "api_key": api_key,
        },
    )
    assert res.status_code == 200, res.text


async def test_gemini_models_native_listing_and_filtering(
    project_client, tmp_path, monkeypatch
):
    """Gemini's models come from the NATIVE REST endpoint
    (``<native>/v1beta/models``) with the ``x-goog-api-key`` header — the
    openai-compat shim has no reliable /models list. The native
    ``models[].name`` ids (``models/`` prefix stripped) are filtered to chat
    models only."""
    client, _ = project_client
    await configure_gemini(client, monkeypatch, tmp_path)
    fake = FakeGetClient(
        {
            "/v1beta/models": {
                "models": [
                    {"name": "models/gemini-2.5-flash"},
                    {"name": "models/gemini-2.5-pro"},
                    {"name": "models/text-embedding-004"},
                ]
            }
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=gemini")
    assert res.status_code == 200, res.text
    assert res.json() == {"models": ["gemini-2.5-flash", "gemini-2.5-pro"]}
    assert len(fake.calls) == 1
    # The native host is derived from the configured openai-compat base.
    assert fake.calls[0]["url"].endswith("/v1beta/models")
    assert fake.calls[0]["headers"] == {"x-goog-api-key": "secret"}


async def test_gemini_models_key_query_fallback(project_client, tmp_path, monkeypatch):
    """When the native list rejects the ``x-goog-api-key`` header call, the
    ``?key=`` query-param variant (no auth header) is tried and its models
    are returned."""
    client, _ = project_client
    await configure_gemini(client, monkeypatch, tmp_path, api_key="sec ret")
    fake = FakeGetClient(
        {
            "/v1beta/models": httpx.ConnectError("refused"),
            "/v1beta/models?key=sec%20ret": {
                "models": [{"name": "models/gemini-2.5-flash"}]
            },
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=gemini")
    assert res.status_code == 200, res.text
    assert res.json() == {"models": ["gemini-2.5-flash"]}
    # call[0] is the failed header attempt; call[1] the successful ?key= one.
    assert fake.calls[0]["headers"] == {"x-goog-api-key": "sec ret"}
    assert fake.calls[1]["url"].endswith("/v1beta/models?key=sec%20ret")
    assert fake.calls[1]["headers"] == {}


async def test_claude_models_headers_and_listing(project_client, tmp_path, monkeypatch):
    """Claude's native list lives at ``<base>/models`` and needs ``x-api-key``
    plus ``anthropic-version`` (Bearer is rejected with 401)."""
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "claude",
            "api_base": "https://api.anthropic.com/v1",
            "model": "claude-sonnet-4-6",
            "api_key": "sk-ant-secret",
        },
    )
    assert res.status_code == 200, res.text
    fake = FakeGetClient(
        {
            "/models": {
                "data": [
                    {"id": "claude-sonnet-4-6"},
                    {"id": "claude-haiku-4-5"},
                ]
            }
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=claude")
    assert res.status_code == 200, res.text
    assert res.json() == {"models": ["claude-haiku-4-5", "claude-sonnet-4-6"]}
    assert len(fake.calls) == 1
    assert fake.calls[0]["url"].endswith("/v1/models")
    assert fake.calls[0]["headers"] == {
        "x-api-key": "sk-ant-secret",
        "anthropic-version": "2023-06-01",
    }


async def test_gpt_models_bearer_and_listing(project_client, tmp_path, monkeypatch):
    """GPT lists models at ``<base>/models`` with a plain Bearer header; the
    list is filtered to chat models of the current generation only."""
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "gpt",
            "api_base": "https://api.openai.com/v1",
            "model": "gpt-5.2",
            "api_key": "sk-secret",
        },
    )
    assert res.status_code == 200, res.text
    fake = FakeGetClient(
        {
            "/v1/models": {
                "data": [
                    {"id": "gpt-5.2"},
                    {"id": "gpt-4.1"},
                    {"id": "gpt-4o"},
                    {"id": "gpt-4.5-can-12345"},
                    {"id": "whisper-1"},
                    {"id": "gpt-image-1"},
                ]
            }
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=gpt")
    assert res.status_code == 200, res.text
    assert res.json() == {"models": ["gpt-4.1", "gpt-4o", "gpt-5.2"]}
    assert len(fake.calls) == 1
    assert fake.calls[0]["url"].endswith("/v1/models")
    assert fake.calls[0]["headers"] == {"Authorization": "Bearer sk-secret"}


async def test_models_all_urls_fail_returns_error_detail(
    project_client, tmp_path, monkeypatch
):
    """When every candidate URL fails, the list returns an empty array plus a
    sanitized error detail instead of a silent empty list."""
    client, _ = project_client
    await configure_gemini(client, monkeypatch, tmp_path, api_key="AIzaTopSecret")
    fake = FakeGetClient(
        {
            "/v1beta/models": httpx.ConnectError("All connection attempts failed"),
            "/v1beta/models?key=AIzaTopSecret": httpx.ConnectError("refused"),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=gemini")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["models"] == []
    assert "error" in body
    assert body["error"]
    assert "AIzaTopSecret" not in body["error"]


async def test_models_error_redacts_api_key_from_url(
    project_client, tmp_path, monkeypatch
):
    """httpx exceptions carry the request URL — the Gemini ``?key=`` fallback
    would leak the API key into the error detail, so it must be redacted.
    A 401 is mapped to a friendly "rejected the API key" message."""
    client, _ = project_client
    await configure_gemini(client, monkeypatch, tmp_path, api_key="AIzaSuperSecret")
    key_url = (
        "https://generativelanguage.googleapis.com/v1beta/models?key=AIzaSuperSecret"
    )
    request = httpx.Request("GET", key_url)
    fake = FakeGetClient(
        {
            "/v1beta/models": httpx.ConnectError("refused"),
            "/v1beta/models?key=AIzaSuperSecret": httpx.HTTPStatusError(
                "Client error '401 Unauthorized' for url '" + key_url + "'",
                request=request,
                response=FakeResponse({"error": {"message": "invalid key"}}, 401),
            ),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=gemini")
    body = res.json()
    assert body["models"] == []
    assert body["error"] == (
        "Gemini rejected the API key (401) — check the key in Settings."
    )
    assert "AIzaSuperSecret" not in body["error"]


async def test_gemini_models_requires_api_key_error(project_client, tmp_path, monkeypatch):
    """Gemini without an API key must say so instead of returning a silent
    empty model list."""
    client, _ = project_client
    await configure_gemini(client, monkeypatch, tmp_path, api_key="")
    fake = FakeGetClient({"/v1beta/models": {"models": []}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=gemini")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "models": [],
        "error": (
            "Gemini requires a valid API key before its models can be listed "
            "— enter your API key in Settings."
        ),
    }
    assert fake.calls == []  # no provider request was attempted


async def test_claude_models_rejected_api_key_403(project_client, tmp_path, monkeypatch):
    """Claude maps a 403 to the same friendly "rejected the API key" detail
    as 401."""
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "claude",
            "api_base": "https://api.anthropic.com/v1",
            "model": "claude-sonnet-4-6",
            "api_key": "sk-ant-secret",
        },
    )
    request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
    fake = FakeGetClient(
        {
            "/models": httpx.HTTPStatusError(
                "Client error '403 Forbidden' for url 'https://api.anthropic.com/v1/models'",
                request=request,
                response=FakeResponse({"error": {"message": "forbidden"}}, 403),
            )
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=claude")
    body = res.json()
    assert body["models"] == []
    assert body["error"] == (
        "Anthropic rejected the API key (403) — check the key in Settings."
    )


async def test_ollama_models_filter_and_dedupe(project_client, tmp_path, monkeypatch):
    """Ollama lists everything it has pulled, including embedding, speech
    and vision models — the /models list must keep chat models only. Tag
    variants ("llama3.2:latest" vs "llama3.2:3b") collapse to one entry,
    preferring ``:latest``; coder models stay."""
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "ollama",
            "api_base": "http://localhost:11434/v1",
            "model": "llama3.2",
            "api_key": "",
        },
    )
    assert res.status_code == 200, res.text
    fake = FakeGetClient(
        {
            "/v1/models": {
                "data": [
                    {"id": "llama3.2:latest"},
                    {"id": "llama3.2:3b"},
                    {"id": "nomic-embed-text"},
                    {"id": "whisper-large"},
                    {"id": "mistral:7b"},
                    {"id": "llava:7b"},
                    {"id": "qwen2.5-coder:7b"},
                    {"id": "llama3.2-vision:latest"},
                ]
            }
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=ollama")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "models": ["llama3.2:latest", "mistral:7b", "qwen2.5-coder:7b"]
    }


async def test_lmstudio_models_filter_and_quant_dedupe(
    project_client, tmp_path, monkeypatch
):
    """LM Studio quant suffixes ("llama-3.1-8b-instruct:q4_k_m") collapse to
    the bare base name; embedding / speech / vision-only ids are dropped."""
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "",
            "api_key": "",
        },
    )
    assert res.status_code == 200, res.text
    fake = FakeGetClient(
        {
            "/v1/models": {
                "data": [
                    {"id": "llama-3.1-8b-instruct:q4_k_m"},
                    {"id": "llama-3.1-8b-instruct:q8_0"},
                    {"id": "nomic-embed-text-v1.5"},
                    {"id": "whisper-small"},
                    {"id": "text-embedding-3-small"},
                    {"id": "qwen2.5-coder-7b-instruct:q4_k_m"},
                    {"id": "deepseek-vl2:q4_k_m"},
                ]
            }
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=lmstudio")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "models": ["llama-3.1-8b-instruct", "qwen2.5-coder-7b-instruct"]
    }


async def test_models_local_provider_failure_has_error_too(
    project_client, tmp_path, monkeypatch
):
    """Local providers report the failure detail as well (e.g. Ollama down)."""
    client, _ = project_client
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": True,
            "provider": "ollama",
            "api_base": "http://localhost:11434/v1",
            "model": "llama3.2",
            "api_key": "",
        },
    )
    assert res.status_code == 200, res.text
    fake = FakeGetClient(
        {
            "/v1/models": httpx.ConnectError("Connection refused"),
            "/models": httpx.ConnectError("Connection refused"),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/models?provider=ollama")
    body = res.json()
    assert body["models"] == []
    assert "error" in body
    assert body["error"]
    assert len(fake.calls) == 2  # both candidate URLs were tried
    assert fake.calls[0]["headers"] == {}


async def test_status_probe_gemini_hits_models_endpoint(
    project_client, tmp_path, monkeypatch
):
    """The Gemini status probe exercises the real native /v1beta/models
    endpoint (never a bare DNS touch), so it also validates the key."""
    client, _ = project_client
    await configure_gemini(client, monkeypatch, tmp_path)
    fake = FakeGetClient(
        {"/v1beta/models": {"models": [{"name": "models/gemini-2.5-flash"}]}}
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    res = await client.get("/api/v1/ai/status?probe=1")
    assert res.json()["reachable"] is True
    assert fake.calls[0]["url"].endswith("/v1beta/models")

    failing = FakeGetClient(
        {
            "/v1beta/models": httpx.ConnectError("refused"),
            "/v1beta/models?key=secret": httpx.ConnectError("refused"),
        }
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: failing)
    res = await client.get("/api/v1/ai/status?probe=1")
    assert res.json()["reachable"] is False


# ----------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------

async def test_chat_success(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "Hi from fake"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "Hi from fake"
    assert body["model"] == "test-model"

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"].endswith("/chat/completions")
    assert "hello" in str(call["json"])
    assert call["json"]["messages"][1] == {"role": "user", "content": "hello"}


async def test_chat_with_context(project_client, monkeypatch, configured_ai):
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


async def test_chat_unreachable(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    patch_client(monkeypatch, {"/chat/completions": httpx.ConnectError("boom")})

    async def no_start(self, ai):
        return False

    monkeypatch.setattr(ai_service_module.AiService, "_ensure_local_backend", no_start)
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 503
    assert "unreachable" in res.json()["detail"]


async def test_chat_backend_error(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    patch_client(
        monkeypatch,
        {"/chat/completions": FakeResponse({"error": {"message": "model not found"}}, 404)},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 503
    assert "AI backend error 404" in res.json()["detail"]


# ----------------------------------------------------------------------
# Memo chat (memo_analysis) & prompt ids
# ----------------------------------------------------------------------

async def add_source_with_memo(client, name: str, memo: str) -> int:
    await import_text(client, name=name, text=f"Body of {name}.")
    sources = (await client.get("/api/v1/sources")).json()
    sid = next(s["id"] for s in sources if s["name"] == name)
    res = await client.patch(f"/api/v1/sources/{sid}", json={"memo": memo})
    assert res.status_code == 200, res.text
    return sid


async def add_code_with_memo(client, name: str, memo: str) -> int:
    res = await client.post("/api/v1/codes", json={"name": name, "memo": memo})
    assert res.status_code == 201, res.text
    return res.json()["cid"]


async def test_chat_injects_selected_memos(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    sid = await add_source_with_memo(client, "alpha.txt", "Source memo text alpha.")
    cid = await add_code_with_memo(client, "Happiness", "Code memo text beta.")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "what do the memos say?", "mode": "memo_analysis", "memo_ids": [sid, cid]},
    )
    assert res.status_code == 200, res.text
    user_message = fake.calls[0]["json"]["messages"][1]
    content = user_message["content"]
    assert "# alpha.txt (file memo):\nSource memo text alpha." in content
    assert "# Happiness (code memo):\nCode memo text beta." in content
    assert content.endswith("\n\nwhat do the memos say?")
    assert fake.calls[0]["json"]["messages"][0]["role"] == "system"


async def test_chat_memo_analysis_mode_fetches_all_memos(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    await add_source_with_memo(client, "gamma.txt", "File memo.")
    await add_code_with_memo(client, "Sadness", "Code memo.")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "analyze", "mode": "memo_analysis"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "# gamma.txt (file memo):\nFile memo." in content
    assert "# Sadness (code memo):\nCode memo." in content


async def test_chat_memo_ids_filter_out_other_memos(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    sid = await add_source_with_memo(client, "keep.txt", "Keep memo.")
    await add_source_with_memo(client, "drop.txt", "Drop memo.")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hi", "mode": "memo_analysis", "memo_ids": [sid]}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "# keep.txt (file memo):\nKeep memo." in content
    assert "drop.txt" not in content


async def test_chat_memo_truncated_to_text_budget(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    long_memo = " ".join(f"word{i}" for i in range(800))  # ~4900 chars, budget is 2000
    await add_code_with_memo(client, "Long", long_memo)
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hi", "mode": "memo_analysis"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert long_memo[:100] in content
    assert long_memo[2500:] not in content
    # The injected block stays within the chunk budget plus its label.
    block = content.split("# Long (code memo):\n", 1)[1].split("\n\n", 1)[0]
    assert len(block) <= 2000


async def test_chat_empty_memo_ids_in_memo_mode_fetches_all_memos(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    await add_source_with_memo(client, "only.txt", "Only memo.")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hello", "mode": "memo_analysis", "memo_ids": []}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "# only.txt (file memo):\nOnly memo." in content


async def test_chat_empty_memo_ids_in_general_mode_sends_no_memo_context(
    project_client, monkeypatch, configured_ai
):
    client, _ = project_client
    await add_source_with_memo(client, "only.txt", "Only memo.")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hello", "mode": "general", "memo_ids": []}
    )
    assert res.status_code == 200, res.text
    assert fake.calls[0]["json"]["messages"][1]["content"] == "hello"


async def test_chat_prompt_id_resolves_from_catalog(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "rewritten"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "The cat sat.", "prompt_id": "instructions/paraphrase"},
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert content.startswith("Instructions:\n")
    assert "paraphrase the empirical data" in content
    assert content.endswith("\n\nThe cat sat.")

    res = await client.post(
        "/api/v1/ai/chat", json={"message": "Great!", "prompt_id": "sentiment"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[1]["json"]["messages"][1]["content"]
    assert "Classify the sentiment" in content
    # The sentiment instruction carries its own persona mode.
    system = fake.calls[1]["json"]["messages"][0]["content"]
    assert "sentiment" in system.lower()


async def test_chat_memo_analysis_mode_uses_memo_persona(project_client, monkeypatch, configured_ai):
    """memo_analysis without an instruction no longer injects a root prompt
    (the per-mode root libraries were consolidated into the instruction
    catalog); the memo persona still applies as the system prompt."""
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "analyze", "mode": "memo_analysis"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "Instructions:" not in content
    assert content == "analyze"
    system = fake.calls[0]["json"]["messages"][0]["content"]
    assert "memos" in system.lower()


async def test_chat_custom_template_prompt_is_resolved_from_db(project_client, monkeypatch, configured_ai):
    """A user-defined template (custom:<id>) is injected as the instruction."""
    client, _ = project_client
    res = await client.post(
        "/api/v1/ai/templates",
        json={"name": "My Focus", "description": "d", "text": "Focus only on the gaps."},
    )
    assert res.status_code == 201, res.text
    template_id = res.json()["id"]
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "go", "prompt_id": f"custom:{template_id}"},
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert content.startswith("Instructions:\n")
    assert "Focus only on the gaps." in content
    # Custom templates carry the general persona (no catalog mode).
    system = fake.calls[0]["json"]["messages"][0]["content"]
    assert "qualitative data analysis" in system.lower()


# ----------------------------------------------------------------------
# Auto mode + persistent chat history
# ----------------------------------------------------------------------

def test_derive_mode_auto_rules():
    from qualcoder_api.services.ai_service import derive_mode

    assert derive_mode("auto", None, None, None) == "general"
    assert derive_mode("auto", [1], None, None) == "memo_analysis"
    assert derive_mode("auto", None, [2], None) == "code_analysis"
    assert derive_mode("auto", None, None, None, source_id=3) == "text_analysis"
    assert derive_mode("auto", [1], [2], None) == "topic_exploration"
    assert derive_mode("auto", None, [2], [4]) == "topic_exploration"
    # Explicit modes are honored as-is.
    assert derive_mode("general", [1], None, None) == "general"
    assert derive_mode("code_analysis", None, None, None) == "code_analysis"


async def test_chat_auto_mode_persists_new_history(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "hi back"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "How do I start?"})
    assert res.status_code == 200, res.text
    chat_id = res.json()["chat_id"]
    assert chat_id > 0
    assert res.json()["reply"] == "hi back"

    listing = await client.get("/api/v1/ai/chats")
    chats = listing.json()["chats"]
    assert len(chats) == 1
    assert chats[0]["id"] == chat_id
    assert chats[0]["title"] == "How do I start?"

    detail = await client.get(f"/api/v1/ai/chats/{chat_id}")
    messages = detail.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["text"] == "How do I start?"
    assert messages[1]["text"] == "hi back"
    envelope = json.loads(messages[0]["request_json"])
    assert envelope["mode"] == "auto"
    assert envelope["mode_derived"] == "general"
    assert envelope["prompt_id"] is None


async def test_chat_continues_existing_chat(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    created = await client.post("/api/v1/ai/chats", json={"title": "Empty session"})
    chat_id = created.json()["id"]
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "again"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "more", "chat_id": chat_id}
    )
    assert res.status_code == 200, res.text
    assert res.json()["chat_id"] == chat_id

    detail = await client.get(f"/api/v1/ai/chats/{chat_id}")
    messages = detail.json()["messages"]
    assert len(messages) == 2

    missing = await client.post("/api/v1/ai/chat", json={"message": "x", "chat_id": 99999})
    assert missing.status_code == 404


async def test_chat_rename_and_delete(project_client, monkeypatch):
    client, _ = project_client
    created = await client.post("/api/v1/ai/chats", json={"title": "Session A"})
    chat_id = created.json()["id"]

    renamed = await client.patch(
        f"/api/v1/ai/chats/{chat_id}", json={"title": "Session B"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Session B"

    detail = await client.get(f"/api/v1/ai/chats/{chat_id}")
    assert detail.json()["title"] == "Session B"

    deleted = await client.delete(f"/api/v1/ai/chats/{chat_id}")
    assert deleted.status_code == 204
    gone = await client.get(f"/api/v1/ai/chats/{chat_id}")
    assert gone.status_code == 404


async def test_chat_rename_rejects_empty_title(project_client):
    client, _ = project_client
    created = await client.post("/api/v1/ai/chats", json={"title": "Session"})
    res = await client.patch(
        f"/api/v1/ai/chats/{created.json()['id']}", json={"title": "   "}
    )
    assert res.status_code == 422


# ----------------------------------------------------------------------
# Instruction templates + merged catalog
# ----------------------------------------------------------------------

async def test_template_crud(project_client):
    client, _ = project_client

    created = await client.post(
        "/api/v1/ai/templates",
        json={"name": "Gap Finder", "description": "Finds gaps", "text": "Find the gaps."},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    listing = await client.get("/api/v1/ai/templates")
    assert listing.status_code == 200
    assert [t["id"] for t in listing.json()["templates"]] == [template_id]

    updated = await client.put(
        f"/api/v1/ai/templates/{template_id}",
        json={"name": "Gap Finder 2", "description": "d", "text": "Find ALL the gaps."},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Gap Finder 2"
    assert updated.json()["text"] == "Find ALL the gaps."

    deleted = await client.delete(f"/api/v1/ai/templates/{template_id}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/ai/templates")).json()["templates"] == []


async def test_template_validation(project_client):
    client, _ = project_client
    no_name = await client.post(
        "/api/v1/ai/templates", json={"name": "  ", "description": "", "text": "x"}
    )
    assert no_name.status_code == 422
    no_text = await client.post(
        "/api/v1/ai/templates", json={"name": "X", "description": "", "text": "  "}
    )
    assert no_text.status_code == 422


async def test_prompts_merge_custom_templates_with_groups(project_client):
    client, _ = project_client
    await client.post(
        "/api/v1/ai/templates",
        json={"name": "My Template", "description": "d", "text": "Body."},
    )
    res = await client.get("/api/v1/ai/prompts")
    assert res.status_code == 200, res.text
    prompts = res.json()["prompts"]
    ids = {p["id"] for p in prompts}
    assert "instructions/summarize" in ids
    assert "instructions/compare" in ids
    assert "instructions/criticize" in ids
    assert "sentiment" in ids
    assert "specialized/reconstructive-srp-lieder-schaffer-2024" in ids
    custom = [p for p in prompts if p["custom"]]
    assert len(custom) == 1
    assert custom[0]["group"] == "custom"
    assert custom[0]["id"].startswith("custom:")
    by_id = {p["id"]: p for p in prompts}
    assert by_id["instructions/summarize"]["group"] == "analysis"
    assert by_id["sentiment"]["group"] == "analysis"
    assert by_id["specialized/reconstructive-srp-lieder-schaffer-2024"]["group"] == "specialized"
    # Display labels are friendlier than the slug ids.
    assert by_id["specialized/reconstructive-srp-lieder-schaffer-2024"]["label"] == "Reconstructive SRP"
    assert by_id["specialized/themes-generation-friese-2024"]["label"] == "Theme Generation (Friese, 2024)"


async def test_personas_roundtrip_and_default(project_client):
    """Personas list the built-in defaults, accept per-mode overrides, and
    a blank override restores the default."""
    from qualcoder_api.services.ai_prompts import MODE_SYSTEM_PROMPTS

    client, _ = project_client

    res = await client.get("/api/v1/ai/personas")
    assert res.status_code == 200, res.text
    personas = {p["mode"]: p for p in res.json()["personas"]}
    assert set(personas) == set(MODE_SYSTEM_PROMPTS)
    assert personas["general"]["default"] == MODE_SYSTEM_PROMPTS["general"]
    assert personas["general"]["text"] == MODE_SYSTEM_PROMPTS["general"]

    res = await client.put(
        "/api/v1/ai/personas",
        json={"personas": {"general": "You are a concise research assistant."}},
    )
    assert res.status_code == 200, res.text

    res = await client.get("/api/v1/ai/personas")
    personas = {p["mode"]: p for p in res.json()["personas"]}
    assert personas["general"]["text"] == "You are a concise research assistant."

    # Blank restores the built-in default.
    res = await client.put("/api/v1/ai/personas", json={"personas": {"general": "  "}})
    assert res.status_code == 200, res.text
    res = await client.get("/api/v1/ai/personas")
    personas = {p["mode"]: p for p in res.json()["personas"]}
    assert personas["general"]["text"] == MODE_SYSTEM_PROMPTS["general"]


async def test_persona_override_applied_in_chat(project_client, monkeypatch, configured_ai):
    """A saved persona override replaces the mode's system prompt."""
    client = configured_ai
    await client.put(
        "/api/v1/ai/personas",
        json={"personas": {"general": "You are the whisperer of concision."}},
    )
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 200, res.text
    system = fake.calls[0]["json"]["messages"][0]["content"]
    assert system.startswith("You are the whisperer of concision.")


async def test_builtin_template_override_and_reset(project_client):
    """Built-in templates are editable app-wide and reset to their shipped text."""
    client, _ = project_client

    res = await client.get("/api/v1/ai/templates/all")
    assert res.status_code == 200, res.text
    by_id = {t["id"]: t for t in res.json()["templates"]}
    summarize = by_id["instructions/summarize"]
    assert summarize["scope"] == "builtin"
    assert summarize["default"] == summarize["text"]

    res = await client.put(
        "/api/v1/ai/templates/all",
        json={
            "id": "instructions/summarize",
            "name": summarize["name"],
            "description": summarize["description"],
            "text": "Summarize in exactly three bullets.",
        },
    )
    assert res.status_code == 200, res.text

    res = await client.get("/api/v1/ai/templates/all")
    by_id = {t["id"]: t for t in res.json()["templates"]}
    assert by_id["instructions/summarize"]["text"] == "Summarize in exactly three bullets."
    assert by_id["instructions/summarize"]["default"] == summarize["default"]

    res = await client.post("/api/v1/ai/templates/all/reset", json={"id": "instructions/summarize"})
    assert res.status_code == 200, res.text

    res = await client.get("/api/v1/ai/templates/all")
    by_id = {t["id"]: t for t in res.json()["templates"]}
    assert by_id["instructions/summarize"]["text"] == summarize["default"]


async def test_builtin_template_override_applied_in_chat(project_client, monkeypatch, configured_ai):
    """Chatting with an overridden built-in template uses the custom body."""
    client = configured_ai
    await client.put(
        "/api/v1/ai/templates/all",
        json={
            "id": "instructions/summarize",
            "name": "Summarize",
            "description": "",
            "text": "CUSTOM SUMMARY INSTRUCTIONS",
        },
    )
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "hello", "prompt_id": "instructions/summarize"},
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][-1]["content"]
    assert "CUSTOM SUMMARY INSTRUCTIONS" in content


async def test_global_template_crud_and_catalog(project_client):
    """App-wide templates appear in the picker catalog and support CRUD."""
    client, _ = project_client

    created = await client.post(
        "/api/v1/ai/templates/global",
        json={"name": "Global Finder", "description": "App-wide", "text": "Find globally."},
    )
    assert created.status_code == 200, created.text
    global_id = created.json()["id"]

    res = await client.get("/api/v1/ai/prompts")
    assert res.status_code == 200, res.text
    prompts = {p["id"]: p for p in res.json()["prompts"]}
    entry = prompts[f"global:{global_id}"]
    assert entry["custom"] is True
    assert entry["global"] is True
    assert entry["group"] == "custom"

    res = await client.put(
        "/api/v1/ai/templates/all",
        json={
            "id": f"global:{global_id}",
            "name": "Global Finder 2",
            "description": "App-wide",
            "text": "Find globally everywhere.",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["text"] == "Find globally everywhere."

    res = await client.get("/api/v1/ai/templates/all")
    by_id = {t["id"]: t for t in res.json()["templates"]}
    assert by_id[f"global:{global_id}"]["scope"] == "app"
    assert by_id[f"global:{global_id}"]["text"] == "Find globally everywhere."

    deleted = await client.delete(f"/api/v1/ai/templates/global/{global_id}")
    assert deleted.status_code == 204
    res = await client.get("/api/v1/ai/prompts")
    assert f"global:{global_id}" not in {p["id"] for p in res.json()["prompts"]}


async def test_editor_save_updates_project_custom_template(project_client):
    """The editor's save endpoint updates a project-scoped custom template."""
    client, _ = project_client
    created = await client.post(
        "/api/v1/ai/templates",
        json={"name": "Project One", "description": "d", "text": "Body."},
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    res = await client.put(
        "/api/v1/ai/templates/all",
        json={
            "id": f"custom:{template_id}",
            "name": "Project One v2",
            "description": "d2",
            "text": "New body.",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Project One v2"
    assert res.json()["text"] == "New body."

    res = await client.get("/api/v1/ai/templates")
    assert res.json()["templates"][0]["name"] == "Project One v2"


# ----------------------------------------------------------------------
# Semantic search
# ----------------------------------------------------------------------

async def test_semantic_search_returns_matching_chunks(project_client, monkeypatch, configured_ai):
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
    assert payload["model"] == "test-model"
    assert len(payload["input"]) == 2
    assert payload["input"][0] == "fox"


async def test_semantic_search_unreachable(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    await import_text(client, text="The quick brown fox jumps over the lazy dog.")
    patch_client(monkeypatch, {"/embeddings": httpx.ConnectError("boom")})

    async def no_start(self, ai):
        return False

    monkeypatch.setattr(ai_service_module.AiService, "_ensure_local_backend", no_start)
    res = await client.post("/api/v1/ai/search", json={"query": "fox"})
    assert res.status_code == 503
    assert "unreachable" in res.json()["detail"]
    assert "embeddings" in res.json()["detail"]


async def test_semantic_search_empty_project(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    patch_client(monkeypatch, {"/embeddings": {"data": []}})
    res = await client.post("/api/v1/ai/search", json={"query": "fox"})
    assert res.status_code == 200, res.text
    assert res.json()["results"] == []


# ----------------------------------------------------------------------
# Agentic chat (MCP tools in the sidebar)
# ----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_pending_agentic(monkeypatch):
    """Keep the module-level pending-approval store isolated per test."""
    monkeypatch.setattr(ai_service_module, "_pending_agentic", {})


def tool_call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def final_message(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


async def test_agentic_executes_tool_then_answers(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": False,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "test-model",
            "api_key": "",
            "mcp_permissions": "write",
        },
    )
    fake = patch_client(
        monkeypatch,
        {
            "/chat/completions": [
                {"choices": [{"message": {"content": "", "tool_calls": [
                    tool_call("create_code", {"name": "Emerging Theme"})
                ]}}]},
                final_message("I created the code."),
            ]
        },
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "create a code called Emerging Theme", "agentic": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "I created the code."
    assert body["model"] == "test-model"
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["tool"] == "create_code"
    assert body["tool_calls"][0]["arguments"] == {"name": "Emerging Theme"}
    assert body["tool_calls"][0]["result"]["code"]["name"] == "Emerging Theme"

    assert len(fake.calls) == 2
    first = fake.calls[0]["json"]
    assert "tools" in first
    tool_names = [t["function"]["name"] for t in first["tools"]]
    assert "create_code" in tool_names
    assert "get_code_tree" in tool_names
    assert first["tool_choice"] == "auto"
    second = fake.calls[1]["json"]
    assert second["messages"][-1]["role"] == "tool"
    assert second["messages"][-1]["tool_call_id"] == "call_1"
    assert "Emerging Theme" in second["messages"][-1]["content"]


async def test_agentic_read_permission_hides_write_tools(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": [final_message("ok")]},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hello", "agentic": True}
    )
    assert res.status_code == 200, res.text
    tool_names = [t["function"]["name"] for t in fake.calls[0]["json"]["tools"]]
    assert "get_code_tree" in tool_names
    assert "create_code" not in tool_names


async def test_agentic_write_permission_exposes_write_tools(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": False,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "test-model",
            "api_key": "",
            "mcp_permissions": "write",
        },
    )
    assert res.status_code == 200, res.text
    fake = patch_client(monkeypatch, {"/chat/completions": [final_message("ok")]})
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hello", "agentic": True}
    )
    assert res.status_code == 200, res.text
    tool_names = [t["function"]["name"] for t in fake.calls[0]["json"]["tools"]]
    assert "create_code" in tool_names
    assert "set_attribute_value" in tool_names


async def test_agentic_confirm_writes_pauses_for_approval(
    project_client, monkeypatch, configured_ai
):
    client, _ = project_client
    await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": False,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "test-model",
            "api_key": "",
            "mcp_permissions": "write",
        },
    )
    fake = patch_client(
        monkeypatch,
        {
            "/chat/completions": [
                {"choices": [{"message": {"content": "", "tool_calls": [
                    tool_call("create_code", {"name": "Approved Code"})
                ]}}]},
                final_message("Done."),
            ]
        },
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "please create a code",
            "agentic": True,
            "confirm_writes": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "awaiting_approval"
    assert body["pending_tools"] == [
        {"name": "create_code", "arguments": {"name": "Approved Code"}}
    ]
    token = body["token"]

    appr = await client.post(
        "/api/v1/ai/chat/approve",
        json={"token": token, "approve": True, "chat_id": body["chat_id"]},
    )
    assert appr.status_code == 200, appr.text
    out = appr.json()
    assert out["reply"] == "Done."
    assert out["tool_calls"][0]["tool"] == "create_code"
    assert out["tool_calls"][0]["approved"] is True
    assert out["tool_calls"][0]["result"]["code"]["name"] == "Approved Code"
    assert fake.calls[1]["json"]["messages"][-1]["role"] == "tool"


async def test_agentic_pause_executes_read_tools_in_same_batch(
    project_client, monkeypatch, configured_ai
):
    """Read tools in a mixed batch run immediately; only the writes pause."""
    client, _ = project_client
    await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": False,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "test-model",
            "api_key": "",
            "mcp_permissions": "write",
        },
    )
    fake = patch_client(
        monkeypatch,
        {
            "/chat/completions": [
                {"choices": [{"message": {"content": "", "tool_calls": [
                    tool_call("get_code_tree", {}, call_id="call_read"),
                    tool_call("create_code", {"name": "Mixed Code"}, call_id="call_write"),
                ]}}]},
                final_message("Done with both."),
            ]
        },
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "check the tree and create a code",
            "agentic": True,
            "confirm_writes": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "awaiting_approval"
    assert [p["name"] for p in body["pending_tools"]] == ["create_code"]

    appr = await client.post(
        "/api/v1/ai/chat/approve",
        json={"token": body["token"], "approve": True, "chat_id": body["chat_id"]},
    )
    assert appr.status_code == 200, appr.text
    out = appr.json()
    assert out["reply"] == "Done with both."
    tools = [t["tool"] for t in out["tool_calls"]]
    assert "get_code_tree" in tools
    assert "create_code" in tools
    # Non-gated read tools carry no approval flag (never shown as rejected);
    # only the approved write does.
    assert "approved" not in out["tool_calls"][0]  # read tool
    assert out["tool_calls"][1]["approved"] is True  # approved write
    # The resumed model call saw the read result (call_read) and the write
    # result (call_write) — no dangling tool_call_id.
    resumed = fake.calls[1]["json"]["messages"]
    tool_ids = [m.get("tool_call_id") for m in resumed if m.get("role") == "tool"]
    assert "call_read" in tool_ids
    assert "call_write" in tool_ids


async def test_agentic_reject_write_does_not_execute(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": False,
            "provider": "lmstudio",
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "test-model",
            "api_key": "",
            "mcp_permissions": "write",
        },
    )
    patch_client(
        monkeypatch,
        {
            "/chat/completions": [
                {"choices": [{"message": {"content": "", "tool_calls": [
                    tool_call("create_code", {"name": "Should Not Exist"})
                ]}}]},
                final_message("I understand."),
            ]
        },
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "please create a code",
            "agentic": True,
            "confirm_writes": True,
        },
    )
    body = res.json()
    appr = await client.post(
        "/api/v1/ai/chat/approve",
        json={"token": body["token"], "approve": False, "chat_id": body["chat_id"]},
    )
    assert appr.status_code == 200, appr.text
    out = appr.json()
    assert out["reply"] == "I understand."
    assert out["tool_calls"][0]["approved"] is False
    assert out["tool_calls"][0]["result"]["status"] == "rejected by the user"

    codes = await client.get("/api/v1/codes")
    assert codes.status_code == 200, codes.text
    names = [c["name"] for c in codes.json()]
    assert "Should Not Exist" not in names


async def test_agentic_approve_unknown_token_fails(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    res = await client.post(
        "/api/v1/ai/chat/approve", json={"token": "nope", "approve": True}
    )
    assert res.status_code == 503
    assert "expired" in res.json()["detail"]


async def test_agentic_tool_error_continues(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {
            "/chat/completions": [
                {"choices": [{"message": {"content": "", "tool_calls": [
                    tool_call("get_source_text", {"source_id": 999})
                ]}}]},
                final_message("That source does not exist."),
            ]
        },
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "find source 999", "agentic": True}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "That source does not exist."
    assert "error" in body["tool_calls"][0]["result"]
    second = fake.calls[1]["json"]
    assert "error" in second["messages"][-1]["content"]


async def test_agentic_falls_back_when_tools_unsupported(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {
            "/chat/completions": [
                FakeResponse({"error": {"message": "unknown parameter: tools"}}, 400),
                final_message("plain fallback"),
            ]
        },
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hello", "agentic": True}
    )
    assert res.status_code == 200, res.text
    assert res.json()["reply"] == "plain fallback"
    assert len(fake.calls) == 2
    assert "tools" not in fake.calls[1]["json"]
    assert res.json()["tool_calls"] == []


async def test_agentic_tools_unsupported_backend_down_still_errors(
    project_client, monkeypatch, configured_ai
):
    client, _ = project_client
    # Non-list route: every call (tools + plain fallback) hits the 404.
    patch_client(
        monkeypatch,
        {
            "/chat/completions": FakeResponse(
                {"error": {"message": "model not found"}}, 404
            ),
        },
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hello", "agentic": True}
    )
    assert res.status_code == 503
    assert "AI backend error 404" in res.json()["detail"]


async def test_agentic_max_iterations_capped(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    calls = [
        {"choices": [{"message": {"content": "", "tool_calls": [
            tool_call("get_code_tree", {}, call_id=f"call_{i}")
        ]}}]}
        for i in range(3)
    ]
    patch_client(monkeypatch, {"/chat/completions": calls})
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "keep going", "agentic": True}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "The assistant did not produce a final answer."
    assert len(body["tool_calls"]) == 3


async def test_agentic_plain_chat_still_works(project_client, monkeypatch, configured_ai):
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": final_message("plain")},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 200, res.text
    assert res.json()["reply"] == "plain"
    assert res.json()["tool_calls"] == []
    assert "tools" not in fake.calls[0]["json"]


async def test_agentic_read_trace_has_no_approval_flag(
    project_client, monkeypatch, configured_ai
):
    """Regression: read tools executed without a gate must NOT carry an
    ``approved`` field — the frontend renders ``approved: false`` as a
    "Rejected" tag, which is wrong for read calls."""
    client, _ = project_client
    fake = patch_client(
        monkeypatch,
        {
            "/chat/completions": [
                {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [tool_call("get_code_tree", {})],
                            }
                        }
                    ]
                },
                final_message("done"),
            ]
        },
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "show the tree", "agentic": True, "confirm_writes": True},
    )
    assert res.status_code == 200, res.text
    tool_calls = res.json()["tool_calls"]
    assert [t["tool"] for t in tool_calls] == ["get_code_tree"]
    assert "approved" not in tool_calls[0]
