"""Cleanup tests — WAL checkpoints, project compaction, maintenance settings.

Covers: checkpoint-on-close (WAL flushed/truncated), the manual compact
endpoint (file shrinks, data intact, indexes recreated), compact-on-close
setting, backups taken after a checkpoint (consistent copies), and the
no-project-open guard.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.persistence.schema import _INDEX_SQL


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the developer's real ~/.qualcoder/settings.json out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def open_project(client, tmp_path):
    target = tmp_path / "cleanup.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text
    yield target
    await client.post("/api/v1/projects/close")


async def _seed_project(target: Path, n_sources: int = 8, n_codings: int = 24) -> None:
    """Insert sources + codings directly via SQL (fast, no API round-trips).

    All writes land in the WAL — the main file is untouched until the next
    checkpoint, which is exactly what the tests below exercise.
    """
    conn = await aiosqlite.connect(target / "data.qda")
    try:
        cur = await conn.cursor()
        # The engine sets WAL mode lazily on first connect; enable it here so
        # the seed writes deterministically land in the -wal file.
        await cur.execute("PRAGMA journal_mode=WAL")
        for i in range(n_sources):
            await cur.execute(
                "INSERT INTO source (name, fulltext, memo, owner, date, memo_type) "
                "VALUES (?, ?, '', 'default', '2026-01-01', 'text')",
                (f"doc{i}.txt", f"content of document {i} " * 2000),
            )
        await cur.execute("SELECT id FROM source")
        fids = [row[0] for row in await cur.fetchall()]
        for i in range(n_codings):
            await cur.execute(
                "INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date) "
                "VALUES (1, ?, ?, ?, ?, 'default', '2026-01-01')",
                (fids[i % len(fids)], f"coding {i}", i * 100, i * 100 + 10),
            )
        await conn.commit()
    finally:
        await conn.close()


async def _index_names(target: Path) -> set[str]:
    conn = await aiosqlite.connect(target / "data.qda")
    try:
        cur = await conn.cursor()
        await cur.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        return {row[0] for row in await cur.fetchall()}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Checkpoint on close
# ---------------------------------------------------------------------------


async def test_close_checkpoints_wal(client, open_project):
    target = open_project
    # An API call opens an engine-pool connection (WAL mode) that stays alive,
    # so the committed seed frames keep sitting in the -wal file instead of
    # being checkpointed when the seed connection closes.
    res = await client.get("/api/v1/projects/current/summary")
    assert res.status_code == 200
    await _seed_project(target, n_sources=2)

    wal = target / "data.qda-wal"
    assert wal.exists(), "WAL file should exist while the project is open"
    assert wal.stat().st_size > 0, "seeded writes should be in the WAL"

    res = await client.post("/api/v1/projects/close")
    assert res.status_code == 200

    # Close flushes the WAL: truncated to zero or deleted outright.
    assert not wal.exists() or wal.stat().st_size == 0, "WAL must be flushed on close"


# ---------------------------------------------------------------------------
# Manual compaction
# ---------------------------------------------------------------------------


async def test_compact_without_project_returns_409(client):
    res = await client.post("/api/v1/projects/compact")
    assert res.status_code == 409


async def test_compact_reclaims_space_and_preserves_data(client, open_project):
    target = open_project
    # Keep an engine-pool connection alive so the seed writes and the deletes
    # below stay in the WAL until the compact checkpoints them.
    res = await client.get("/api/v1/projects/current/summary")
    assert res.status_code == 200
    await _seed_project(target, n_sources=8, n_codings=24)

    # Delete most rows — the freed space lives in the WAL until checkpointed.
    conn = await aiosqlite.connect(target / "data.qda")
    await conn.execute("DELETE FROM code_text")
    await conn.execute(
        "DELETE FROM source WHERE id IN "
        "(SELECT id FROM source ORDER BY id DESC LIMIT 6)"
    )
    await conn.commit()
    await conn.close()

    res = await client.post("/api/v1/projects/compact")
    assert res.status_code == 200, res.text
    stats = res.json()
    assert stats["ok"] is True
    assert stats["before_bytes"] > stats["after_bytes"], "file must shrink"
    assert stats["freed_bytes"] == stats["before_bytes"] - stats["after_bytes"]
    # Every dropped index (canonical _INDEX_SQL plus any extra idx_* like the
    # sync_log unique index) is recreated either from _INDEX_SQL or the
    # safety-net restore, so dropped == recreated and covers _INDEX_SQL.
    assert stats["indexes_dropped"] == stats["indexes_recreated"]
    assert stats["indexes_dropped"] >= len(_INDEX_SQL)

    # The open project keeps working right after the compaction...
    res = await client.get("/api/v1/projects/current/summary")
    assert res.status_code == 200
    assert res.json()["summary"]["files_count"] == 2
    assert res.json()["summary"]["codes_count"] == 0

    # ...and every rebuildable index from schema.py exists again.
    present = await _index_names(target)
    expected = {sql.split()[5] for sql in _INDEX_SQL}
    assert expected <= present

    # A subsequent close→open cycle still works.
    res = await client.post("/api/v1/projects/close")
    assert res.status_code == 200
    res = await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    res = await client.get("/api/v1/projects/current/summary")
    assert res.status_code == 200
    assert res.json()["summary"]["files_count"] == 2


async def test_compact_is_audit_recorded(client, open_project):
    target = open_project
    await client.get("/api/v1/projects/current/summary")  # keep the WAL alive
    await _seed_project(target, n_sources=2)

    res = await client.post("/api/v1/projects/compact")
    assert res.status_code == 200, res.text

    res = await client.get("/api/v1/audit", params={"action": "project.compact"})
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["action"] == "project.compact"
    assert rows[0]["detail"]["before_bytes"] > 0
    assert rows[0]["detail"]["after_bytes"] > 0


# ---------------------------------------------------------------------------
# Backups after a checkpoint
# ---------------------------------------------------------------------------


async def test_backup_is_consistent_with_wal(client, open_project):
    """A backup taken while the project is open must include WAL content.

    Without the checkpoint-before-copy, the copied data.qda misses every
    committed frame still sitting in the -wal file (0 sources in the copy).
    """
    target = open_project
    await client.get("/api/v1/projects/current/summary")  # keep the WAL alive
    await _seed_project(target, n_sources=3)

    from qualcoder_api.main import service

    msg, backup_path = await service.save_backup()
    assert "Backup created" in msg

    conn = await aiosqlite.connect(backup_path)
    try:
        cur = await conn.cursor()
        await cur.execute("SELECT count(*) FROM source")
        count = (await cur.fetchone())[0]
    finally:
        await conn.close()
    assert count == 3, "backup copy must contain the WAL-flushed rows"


# ---------------------------------------------------------------------------
# Compact-on-close setting
# ---------------------------------------------------------------------------


async def test_maintenance_settings_roundtrip(client):
    res = await client.get("/api/v1/maintenance/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["compact_on_close"] is False
    assert body["last_compact"] == ""

    res = await client.put(
        "/api/v1/maintenance/settings", json={"compact_on_close": True}
    )
    assert res.status_code == 200, res.text
    assert res.json()["compact_on_close"] is True

    res = await client.get("/api/v1/maintenance/settings")
    assert res.json()["compact_on_close"] is True
    assert res.json()["last_compact"] == ""


async def test_compact_on_close_setting_honored(client, open_project, monkeypatch):
    target = open_project
    await client.get("/api/v1/projects/current/summary")  # keep the WAL alive
    await _seed_project(target, n_sources=3)

    from qualcoder_api.services import cleanup_service, user_settings

    calls: list[str] = []
    real = cleanup_service.compact_project

    async def spy(db_path: str):
        calls.append(db_path)
        return await real(db_path)

    monkeypatch.setattr(cleanup_service, "compact_project", spy)

    res = await client.put(
        "/api/v1/maintenance/settings", json={"compact_on_close": True}
    )
    assert res.status_code == 200

    res = await client.post("/api/v1/projects/close")
    assert res.status_code == 200
    assert calls == [str(target / "data.qda")]
    assert user_settings.get_last_compact() != ""

    # Opted back out: plain checkpoint close, no compaction.
    await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    calls.clear()
    res = await client.put(
        "/api/v1/maintenance/settings", json={"compact_on_close": False}
    )
    assert res.status_code == 200
    res = await client.post("/api/v1/projects/close")
    assert res.status_code == 200
    assert calls == []
