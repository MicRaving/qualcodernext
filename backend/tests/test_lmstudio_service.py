"""LM Studio auto-start: CLI discovery, ensure flow, API endpoint, and the
chat retry that kicks in when the backend was down."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import ai_service as ai_service_module
from qualcoder_api.services import lmstudio_service as lms_mod
from qualcoder_api.services import user_settings
from qualcoder_api.services.ai_service import AiService, AiUnavailable

# ----------------------------------------------------------------------
# CLI discovery
# ----------------------------------------------------------------------


def test_find_lms_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "lms-custom.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv("QC_LMS_CLI", str(exe))
    assert lms_mod.find_lms() == str(exe)


def test_find_lms_env_override_missing_file_falls_through(monkeypatch):
    monkeypatch.setenv("QC_LMS_CLI", str(__import__("pathlib").Path("Z:/nope/lms.exe")))
    # Falls through to PATH/default-location discovery; must not return the
    # bogus override. On a machine with lms installed this finds the real
    # one, otherwise None — either way never the missing path.
    result = lms_mod.find_lms()
    assert result != "Z:/nope/lms.exe"


def test_find_lms_standard_location(tmp_path, monkeypatch):
    binary = "lms.exe" if lms_mod.os.name == "nt" else "lms"
    std = tmp_path / ".lmstudio" / "bin" / binary
    std.parent.mkdir(parents=True)
    std.write_bytes(b"x")
    monkeypatch.delenv("QC_LMS_CLI", raising=False)
    monkeypatch.setattr(lms_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(lms_mod, "_standard_candidates", lambda: [std])
    assert lms_mod.find_lms() == str(std)


# ----------------------------------------------------------------------
# ensure_lmstudio flow
# ----------------------------------------------------------------------


def test_ensure_already_ready(monkeypatch):
    monkeypatch.setattr(lms_mod, "reachable", lambda base: True)
    monkeypatch.setattr(lms_mod, "loaded_ids", lambda base: ["qwen/qwen3.5-9b"])
    res = lms_mod.ensure_lmstudio("http://127.0.0.1:1234/v1", "qwen/qwen3.5-9b")
    assert res == {
        "ok": True,
        "started_server": False,
        "loaded_model": False,
        "already_ready": True,
        "error": "",
    }


def test_ensure_no_cli(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(lms_mod, "reachable", lambda base: False)
    monkeypatch.setattr(lms_mod, "find_lms", lambda: None)
    monkeypatch.setattr(
        lms_mod, "_run_lms", lambda cli, args, timeout_s: calls.append(args) or (True, "")
    )
    res = lms_mod.ensure_lmstudio("http://127.0.0.1:1234/v1", "m")
    assert res["ok"] is False
    assert "CLI not found" in res["error"]
    assert calls == []


def test_ensure_starts_server_and_loads_model(monkeypatch):
    """Server down + model not served → runs ``server start`` then ``load``."""
    calls: list[list[str]] = []
    state = {"reachable": False, "ids": []}

    def fake_reachable(base: str) -> bool:
        return state["reachable"]

    def fake_run(cli: str, args: list[str], timeout_s: float) -> tuple[bool, str]:
        calls.append(args)
        if args[:2] == ["server", "start"]:
            state["reachable"] = True
        if args[:1] == ["load"]:
            state["ids"] = ["qwen/qwen3.5-9b"]
        return True, "Success!"

    monkeypatch.setattr(lms_mod, "reachable", fake_reachable)
    monkeypatch.setattr(lms_mod, "loaded_ids", lambda base: state["ids"])
    monkeypatch.setattr(lms_mod, "find_lms", lambda: "C:/fake/lms.exe")
    monkeypatch.setattr(lms_mod, "_run_lms", fake_run)

    res = lms_mod.ensure_lmstudio("http://127.0.0.1:1234/v1", "qwen/qwen3.5-9b")
    assert res["ok"] is True
    assert res["started_server"] is True
    assert res["loaded_model"] is True
    assert calls[0][:2] == ["server", "start"]
    assert calls[1][0] == "load"
    assert "qwen/qwen3.5-9b" in calls[1]


def test_ensure_skips_load_when_no_model_configured(monkeypatch):
    calls: list[list[str]] = []
    state = {"reachable": False}

    def fake_run(cli: str, args: list[str], timeout_s: float) -> tuple[bool, str]:
        calls.append(args)
        if args[:2] == ["server", "start"]:
            state["reachable"] = True
            return True, ""
        raise AssertionError("only server start expected")

    monkeypatch.setattr(lms_mod, "reachable", lambda base: state["reachable"])
    monkeypatch.setattr(lms_mod, "find_lms", lambda: "C:/fake/lms.exe")
    monkeypatch.setattr(lms_mod, "loaded_ids", lambda base: [])
    monkeypatch.setattr(lms_mod, "_run_lms", fake_run)
    res = lms_mod.ensure_lmstudio("http://127.0.0.1:1234/v1", "")
    assert res["ok"] is True
    assert res["started_server"] is True
    assert res["loaded_model"] is False
    assert len(calls) == 1


def test_ensure_reports_server_start_failure(monkeypatch):
    monkeypatch.setattr(lms_mod, "reachable", lambda base: False)
    monkeypatch.setattr(lms_mod, "find_lms", lambda: "C:/fake/lms.exe")
    monkeypatch.setattr(lms_mod, "_run_lms", lambda cli, args, timeout_s: (False, "boom"))
    res = lms_mod.ensure_lmstudio("http://127.0.0.1:1234/v1", "m")
    assert res["ok"] is False
    assert "server start failed" in res["error"]
    assert "boom" in res["error"]


def test_ensure_reports_load_failure(monkeypatch):
    def fake_run(cli: str, args: list[str], timeout_s: float) -> tuple[bool, str]:
        if args[:2] == ["server", "start"]:
            return (True, "")
        return (False, "model key not found")

    monkeypatch.setattr(lms_mod, "reachable", lambda base: True)
    monkeypatch.setattr(lms_mod, "loaded_ids", lambda base: [])
    monkeypatch.setattr(lms_mod, "find_lms", lambda: "C:/fake/lms.exe")
    monkeypatch.setattr(lms_mod, "_run_lms", fake_run)
    res = lms_mod.ensure_lmstudio("http://127.0.0.1:1234/v1", "missing-model")
    assert res["ok"] is False
    assert "lms load failed" in res["error"]
    assert "not found" in res["error"]


# ----------------------------------------------------------------------
# API endpoint
# ----------------------------------------------------------------------


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


async def _configure(provider: str = "lmstudio") -> None:
    user_settings.save_ai_settings(
        {
            "enabled": True,
            "provider": provider,
            "api_base": "http://127.0.0.1:1234/v1",
            "model": "test-model",
            "api_key": "",
        }
    )


async def test_ensure_backend_endpoint_passthrough(isolated_settings, monkeypatch):
    await _configure()
    seen: dict[str, Any] = {}

    def fake_ensure(api_base: str, model: str) -> dict:
        seen["api_base"] = api_base
        seen["model"] = model
        return {"ok": True, "started_server": True, "loaded_model": True,
                "already_ready": False, "error": ""}

    monkeypatch.setattr(lms_mod, "ensure_lmstudio", fake_ensure)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/ai/ensure-backend")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["loaded_model"] is True
    assert seen["api_base"] == "http://127.0.0.1:1234/v1"
    assert seen["model"] == "test-model"


async def test_ensure_backend_endpoint_rejects_cloud_provider(
    isolated_settings, monkeypatch
):
    await _configure("gpt")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/ai/ensure-backend")
    assert res.status_code == 422
    assert "lmstudio" in res.json()["detail"]


async def test_ensure_backend_endpoint_respects_disabled_flag(
    isolated_settings, monkeypatch
):
    await _configure()
    stored = user_settings.load_settings()
    stored["ai"]["auto_start_backend"] = False
    user_settings.save_settings(stored)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/ai/ensure-backend")
    assert res.status_code == 422
    assert "disabled" in res.json()["detail"]


async def test_auto_start_setting_roundtrip(isolated_settings):
    saved = user_settings.save_ai_settings(
        {
            "enabled": True,
            "provider": "lmstudio",
            "api_base": "",
            "model": "m",
            "auto_start_backend": False,
        }
    )
    assert saved["auto_start_backend"] is False
    loaded = user_settings.get_ai_settings()
    assert loaded["auto_start_backend"] is False
    # Default when absent: True.
    stored = user_settings.load_settings()
    del stored["ai"]["auto_start_backend"]
    user_settings.save_settings(stored)
    assert user_settings.get_ai_settings()["auto_start_backend"] is True


# ----------------------------------------------------------------------
# Chat retry after auto-start
# ----------------------------------------------------------------------


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class SeqClient:
    """Serves queued results in order (exceptions included)."""

    def __init__(self, queue: list[Any]):
        self.queue = queue

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def post(self, url: str, **kwargs):
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, FakeResponse) else FakeResponse(item)


@pytest.fixture
def ai_dict():
    return {
        "enabled": True,
        "provider": "lmstudio",
        "api_base": "http://127.0.0.1:1234/v1",
        "model": "test-model",
        "api_key": "",
        "auto_start_backend": True,
    }


async def test_chat_retries_after_autostart(ai_dict, monkeypatch):
    queue: list[Any] = [
        httpx.ConnectError("down"),
        FakeResponse({"choices": [{"message": {"content": "hi!"}}]}),
    ]
    monkeypatch.setattr(ai_service_module, "AsyncClient", lambda **kw: SeqClient(queue))

    ensured = {"count": 0}

    async def fake_ensure(self, ai: dict) -> bool:
        ensured["count"] += 1
        return True

    monkeypatch.setattr(AiService, "_ensure_local_backend", fake_ensure)
    svc = AiService(session_factory=None)
    out = await svc.chat(ai_dict, "hello")
    assert out["reply"] == "hi!"
    assert ensured["count"] == 1
    assert len(queue) == 0


async def test_chat_fails_when_autostart_not_applicable(ai_dict, monkeypatch):
    queue: list[Any] = [httpx.ConnectError("down")]
    monkeypatch.setattr(ai_service_module, "AsyncClient", lambda **kw: SeqClient(queue))

    async def no_start(self, ai: dict) -> bool:
        return False

    monkeypatch.setattr(AiService, "_ensure_local_backend", no_start)
    svc = AiService(session_factory=None)

    with pytest.raises(AiUnavailable, match="unreachable"):
        await svc.chat(ai_dict, "hello")


async def test_chat_fails_when_retry_also_unreachable(ai_dict, monkeypatch):
    queue: list[Any] = [
        httpx.ConnectError("down"),
        httpx.ConnectError("still down"),
    ]
    monkeypatch.setattr(ai_service_module, "AsyncClient", lambda **kw: SeqClient(queue))

    async def yes(self, ai: dict) -> bool:
        return True

    monkeypatch.setattr(AiService, "_ensure_local_backend", yes)
    svc = AiService(session_factory=None)

    with pytest.raises(AiUnavailable, match="attempted to start"):
        await svc.chat(ai_dict, "hello")
