"""Project-context injection tests for the AI chat.

The chat endpoint injects a compact, read-only summary of the open project
into the user message for the project-aware modes (general, topic
exploration, code analysis, text analysis) — gated by the AI enabled flag
and the ``mcp_permissions`` setting (read/full only, never write).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import ai_service as ai_service_module
from qualcoder_api.services import user_settings
from tests.test_api_ai import FakeClient, patch_client


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the developer's real AI settings out of the run."""
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "ctx.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


async def enable_ai(
    client, monkeypatch, tmp_path, mcp_permissions: str = "read", enabled: bool = True
) -> None:
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": enabled,
            "provider": "ollama",
            "api_base": "http://localhost:11434/v1",
            "model": "llama3.2",
            "api_key": "",
            "mcp_permissions": mcp_permissions,
        },
    )
    assert res.status_code == 200, res.text


async def import_text(client, name: str, text: str = "Body.") -> int:
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": (name, text, "text/plain")},
        data={"owner": "tester"},
    )
    assert res.status_code == 200, res.text
    sources = (await client.get("/api/v1/sources")).json()
    return next(s["id"] for s in sources if s["name"] == name)


async def add_code(client, name: str) -> int:
    res = await client.post("/api/v1/codes", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["cid"]


async def set_code_memo(client, cid: int, memo: str) -> None:
    res = await client.patch(f"/api/v1/codes/{cid}", json={"memo": memo})
    assert res.status_code == 200, res.text


async def add_coding(client, cid: int, fid: int, pos0: int = 0, seltext: str = "snippet") -> None:
    res = await client.post(
        "/api/v1/codings/text",
        json={
            "cid": cid,
            "fid": fid,
            "seltext": seltext,
            "pos0": pos0,
            "pos1": pos0 + len(seltext),
            "owner": "tester",
        },
    )
    assert res.status_code == 201, res.text


async def add_case(client, name: str) -> None:
    res = await client.post("/api/v1/cases", json={"name": name})
    assert res.status_code == 201, res.text


async def add_media_source(tmp_path, name: str, mediapath: str) -> None:
    """Insert a non-text source row directly (import only handles text)."""
    from sqlalchemy import insert

    from qualcoder_api.main import service
    from qualcoder_api.persistence import tables

    async with service.session_factory() as session:
        await session.execute(
            insert(tables.source).values(
                name=name, mediapath=mediapath, fulltext=None, owner="tester"
            )
        )
        await session.commit()


# ----------------------------------------------------------------------
# Context injection
# ----------------------------------------------------------------------

async def test_chat_injects_project_context_general_mode(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    fid = await import_text(client, "alpha.txt", "Hello world.")
    await add_code(client, "Happiness")
    sad_cid = await add_code(client, "Sadness")
    await add_coding(client, sad_cid, fid)
    await add_coding(client, sad_cid, fid, pos0=10)
    await add_case(client, "Case A")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert content.startswith("PROJECT CONTEXT\n")
    assert "- alpha.txt (text)" in content
    assert "- Happiness: 0 codings" in content
    assert "- Sadness: 2 codings" in content
    assert "Total codings: 2" in content
    assert "Cases: 1" in content
    assert content.endswith("\n\nhello")


async def test_chat_injects_project_context_in_topic_exploration_mode(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    await import_text(client, "alpha.txt")
    await add_code(client, "Hope")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "explore", "mode": "topic_exploration"},
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "PROJECT CONTEXT" in content
    assert "- Hope: 0 codings" in content


async def test_chat_media_sources_show_media_type(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    await import_text(client, "doc.txt")
    await add_media_source(tmp_path, "clip.mp3", "audio:clip.mp3")
    await add_media_source(tmp_path, "photo.jpg", "images:photo.jpg")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hi", "mode": "general"})
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "- clip.mp3 (audio)" in content
    assert "- photo.jpg (image)" in content
    assert "- doc.txt (text)" in content


async def test_chat_sources_capped_at_twenty(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    for i in range(25):
        await import_text(client, f"file-{i:02d}.txt")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hi"})
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "Sources: 25 total, 20 shown" in content
    lines = [line for line in content.splitlines() if line.startswith("- file-")]
    assert len(lines) == 20


async def test_chat_context_capped_at_3000_chars(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    for i in range(40):
        await add_code(client, f"Code number {i:02d} " + ("x" * 90))
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hi", "mode": "general"})
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    block = content.split("\n\n", 1)[0]
    assert block.startswith("PROJECT CONTEXT")
    assert len(block) <= 3000


# ----------------------------------------------------------------------
# Code-analysis context (code tree + memos + example segments)
# ----------------------------------------------------------------------

async def test_chat_code_analysis_includes_memos_and_examples(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    fid = await import_text(client, "alpha.txt", "Alpha body with a happy quote inside.")
    happy_cid = await add_code(client, "Happiness")
    sad_cid = await add_code(client, "Sadness")
    await set_code_memo(client, sad_cid, "Sadness captures everything gloomy in the interviews.")
    await add_coding(client, happy_cid, fid, seltext="a happy quote")
    await add_coding(client, sad_cid, fid, seltext="a gloomy remark")
    await add_coding(client, sad_cid, fid, pos0=20, seltext="another gloomy remark")
    await add_coding(client, sad_cid, fid, pos0=50, seltext="third gloomy remark")
    await add_coding(client, sad_cid, fid, pos0=80, seltext="fourth gloomy remark")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "analyze", "mode": "code_analysis"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "CODE ANALYSIS CONTEXT" in content
    assert content.endswith("\n\nanalyze")
    assert "- Happiness" in content
    assert "- Sadness" in content
    assert "Codings: 1" in content
    assert "Codings: 4" in content
    assert "Memo: Sadness captures" in content
    assert 'Example: "a gloomy remark" (alpha.txt)' in content
    assert 'Example: "another gloomy remark" (alpha.txt)' in content
    assert "third gloomy remark" not in content
    assert "fourth gloomy remark" not in content


async def test_chat_code_analysis_shows_category_path_and_truncates(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    fid = await import_text(client, "alpha.txt", "Body.")
    res = await client.post(
        "/api/v1/codes/categories", json={"name": "Emotions"}
    )
    assert res.status_code == 201, res.text
    catid = res.json()["catid"]
    res = await client.post(
        "/api/v1/codes", json={"name": "Happiness", "catid": catid}
    )
    assert res.status_code == 201, res.text
    happy_cid = res.json()["cid"]
    await set_code_memo(client, happy_cid, "memo word " * 30)
    await add_coding(client, happy_cid, fid, seltext="word " * 30)
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "analyze", "mode": "code_analysis"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "- Happiness (path: Emotions)" in content
    memo_line = next(line for line in content.splitlines() if line.startswith("  Memo: "))
    assert len(memo_line) <= 200 + len("  Memo: ")
    example_line = next(line for line in content.splitlines() if line.startswith('  Example: "'))
    assert len(example_line) <= 120 + len('  Example: "" (alpha.txt)')


async def test_chat_code_analysis_capped_at_5000_chars(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    for i in range(40):
        cid = await add_code(client, f"Code number {i:02d} " + ("x" * 90))
        await set_code_memo(client, cid, "m" * 250)
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hi", "mode": "code_analysis"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    block = content.split("CODE ANALYSIS CONTEXT", 1)[1].split("\n\n", 1)[0]
    assert block.startswith("\nCodes: 40 total, 30 shown")
    assert len(block) <= 5000


# ----------------------------------------------------------------------
# Text-analysis context (open-source fulltext)
# ----------------------------------------------------------------------

async def test_chat_text_analysis_with_source_id_includes_text(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    body = "The first interview participant described her daily routine in detail."
    fid = await import_text(client, "interview.txt", body)
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "what is this about?", "mode": "text_analysis", "source_id": fid},
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "TEXT ANALYSIS SOURCE\n# interview.txt\n\n" in content
    assert body in content
    assert content.endswith("\n\nwhat is this about?")


async def test_chat_text_analysis_source_text_capped(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    body = "paragraph one. " * 500
    fid = await import_text(client, "long.txt", body)
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "hi", "mode": "text_analysis", "source_id": fid},
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "TEXT ANALYSIS SOURCE\n# long.txt\n\n" in content
    text_part = content.split("TEXT ANALYSIS SOURCE\n# long.txt\n\n", 1)[1].split("\n\n", 1)[0]
    assert len(text_part) <= 6000
    assert text_part == body[:6000]


async def test_chat_text_analysis_without_source_id_falls_back_to_summary(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    await import_text(client, "alpha.txt", "Body.")
    await add_code(client, "Hope")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "explore", "mode": "text_analysis"}
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "PROJECT CONTEXT" in content
    assert "- alpha.txt (text)" in content
    assert "- Hope: 0 codings" in content
    assert content.endswith("\n\nexplore")


async def test_chat_text_analysis_unknown_source_skips_text(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post(
        "/api/v1/ai/chat",
        json={"message": "hi", "mode": "text_analysis", "source_id": 99999},
    )
    assert res.status_code == 200, res.text
    content = fake.calls[0]["json"]["messages"][1]["content"]
    assert "PROJECT CONTEXT" in content
    assert "TEXT ANALYSIS SOURCE" not in content


# ----------------------------------------------------------------------
# Permission & mode gating
# ----------------------------------------------------------------------

async def test_chat_no_context_when_mcp_permissions_write(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path, mcp_permissions="write")
    await import_text(client, "alpha.txt")
    await add_code(client, "Hope")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hi", "mode": "general"})
    assert res.status_code == 200, res.text
    assert fake.calls[0]["json"]["messages"][1]["content"] == "hi"


async def test_chat_no_context_when_ai_disabled(project_client, tmp_path, monkeypatch):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path, enabled=False)
    await import_text(client, "alpha.txt")
    await add_code(client, "Hope")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hi", "mode": "general"})
    assert res.status_code == 200, res.text
    assert fake.calls[0]["json"]["messages"][1]["content"] == "hi"


async def test_chat_no_context_in_help_and_memo_modes(
    project_client, tmp_path, monkeypatch
):
    client, _ = project_client
    await enable_ai(client, monkeypatch, tmp_path)
    await import_text(client, "alpha.txt")
    await add_code(client, "Hope")
    fake = patch_client(
        monkeypatch,
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}},
    )
    res = await client.post("/api/v1/ai/chat", json={"message": "hi", "mode": "help"})
    assert res.status_code == 200, res.text
    assert "PROJECT CONTEXT" not in fake.calls[0]["json"]["messages"][1]["content"]
    res = await client.post(
        "/api/v1/ai/chat", json={"message": "hi", "mode": "memo_analysis"}
    )
    assert res.status_code == 200, res.text
    assert "PROJECT CONTEXT" not in fake.calls[0]["json"]["messages"][1]["content"]


# ----------------------------------------------------------------------
# No project open
# ----------------------------------------------------------------------

async def test_chat_no_project_open_skips_context(monkeypatch):
    """AiService with no session factory (no open project) injects nothing."""
    from qualcoder_api.services.ai_service import AiService

    fake = FakeClient(
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}}
    )
    monkeypatch.setattr(ai_service_module, "AsyncClient", lambda **kw: fake)
    ai = {
        "enabled": True,
        "provider": "ollama",
        "api_base": "http://localhost:11434/v1",
        "model": "llama3.2",
        "api_key": "",
        "mcp_permissions": "read",
    }
    reply = await AiService(None).chat(ai, "hello", mode="general")
    assert reply["reply"] == "ok"
    assert fake.calls[0]["json"]["messages"][1]["content"] == "hello"


async def test_chat_context_survives_query_failure(monkeypatch):
    """A broken summary query must never fail the chat — context is skipped."""
    from qualcoder_api.services.ai_service import AiService

    class BrokenSession:
        async def __aenter__(self):
            raise RuntimeError("boom")

        async def __aexit__(self, *_args):
            pass

    class BrokenFactory:
        def __call__(self):
            return BrokenSession()

    fake = FakeClient(
        {"/chat/completions": {"choices": [{"message": {"content": "ok"}}]}}
    )
    monkeypatch.setattr(ai_service_module, "AsyncClient", lambda **kw: fake)
    ai = {
        "enabled": True,
        "provider": "ollama",
        "api_base": "http://localhost:11434/v1",
        "model": "llama3.2",
        "api_key": "",
        "mcp_permissions": "read",
    }
    await AiService(BrokenFactory()).chat(ai, "hello", mode="general")
    assert fake.calls[0]["json"]["messages"][1]["content"] == "hello"
