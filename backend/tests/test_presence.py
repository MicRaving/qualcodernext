"""Live coder-presence tests — per-instance presence files (who is active,
and on which file)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from qualcoder_api.services import presence_service
from qualcoder_api.services.project_service import ProjectService


@pytest.fixture
async def project(tmp_path):
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "P.qda"), codername="anna")
    yield svc
    await svc.close_project()


@pytest.fixture
async def project_client(tmp_path, monkeypatch):
    """API client with a fresh open project (endpoint test)."""
    from httpx import ASGITransport, AsyncClient
    from qualcoder_api.main import app
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "presence-api.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


def _read_all(root: Path) -> dict[str, dict]:
    out = {}
    for p in root.glob("*.json"):
        if p.name.endswith(".tmp"):
            continue
        out[p.name] = json.loads(p.read_text(encoding="utf-8"))
    return out


async def test_touch_creates_and_skips_unchanged(project):
    root = Path(project.project_path) / presence_service.PRESENCE_DIR_NAME
    presence_service.touch(project.project_path, "anna", file_id=7, file_name="a.txt")
    files = _read_all(root)
    assert len(files) == 1
    entry = next(iter(files.values()))
    assert entry["coder"] == "anna"
    assert entry["file_id"] == 7
    assert entry["file_name"] == "a.txt"

    # Unchanged + fresh heartbeat → no rewrite (returns False).
    first_mtime = next(iter(root.glob("*.json"))).stat().st_mtime_ns
    assert presence_service.touch(project.project_path, "anna", file_id=7, file_name="a.txt") is False
    assert next(iter(root.glob("*.json"))).stat().st_mtime_ns == first_mtime

    # A file change IS recorded.
    assert presence_service.touch(project.project_path, "anna", file_id=8, file_name="b.txt") is True
    entry = next(iter(_read_all(root).values()))
    assert entry["file_id"] == 8


async def test_read_excludes_self_and_prunes_stale(project):
    root = Path(project.project_path) / presence_service.PRESENCE_DIR_NAME
    presence_service.touch(project.project_path, "anna", file_id=1, file_name="a.txt")
    # Own entry is excluded.
    assert presence_service.read(project.project_path) == []

    # A stale entry (old ts) is pruned on read.
    stale = root / "999999.json"
    stale.write_text(
        json.dumps({"coder": "berta", "os_user": "u", "pid": 999999,
                    "ts": time.time() - presence_service.PRESENCE_TTL_SECS - 10,
                    "file_id": None, "file_name": ""}),
        encoding="utf-8",
    )
    assert presence_service.read(project.project_path) == []
    assert not stale.exists()


async def test_read_returns_foreign_live_entry(project):
    root = Path(project.project_path) / presence_service.PRESENCE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    sleeper = subprocess.Popen(  # noqa: ASYNC220 - foreign-pid liveness check
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    try:
        (root / f"{sleeper.pid}.json").write_text(
            json.dumps({"coder": "berta", "os_user": "marvi", "pid": sleeper.pid,
                        "ts": time.time(), "file_id": 3, "file_name": "focus.txt"}),
            encoding="utf-8",
        )
        entries = presence_service.read(project.project_path)
        assert len(entries) == 1
        e = entries[0]
        assert e["coder"] == "berta"
        assert e["file_id"] == 3
        assert e["file_name"] == "focus.txt"
    finally:
        sleeper.kill()


async def test_clear_removes_own_file(project):
    presence_service.touch(project.project_path, "anna", file_id=1, file_name="a.txt")
    root = Path(project.project_path) / presence_service.PRESENCE_DIR_NAME
    assert len(list(root.glob("*.json"))) == 1
    presence_service.clear(project.project_path)
    assert len(list(root.glob("*.json"))) == 0
    # close_project also clears (idempotent).
    presence_service.touch(project.project_path, "anna")
    await project.close_project()
    assert len(list(root.glob("*.json"))) == 0


async def test_presence_endpoints(project_client):
    client, _ = project_client
    res = await client.post(
        "/api/v1/sync/presence/activity",
        json={"file_id": 42, "file_name": "interview.txt"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    res = await client.get("/api/v1/sync/presence")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["presence"], list)
    # The activity endpoint updated the server's current source; the read
    # excludes this instance's own entry.
    assert body["presence"] == []
