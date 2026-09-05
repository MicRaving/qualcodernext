"""Collaboration (Golden Master + sandbox) mode tests.

Exercises project_service mode transitions end-to-end: activation, close /
reopen in collaboration mode, consolidation, and revert to single-coder.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest
from sqlalchemy import text

from qualcoder_api.persistence.repositories import CodeRepository, SourceRepository
from qualcoder_api.services import project_marker, sandbox, sync, sync_engine, sync_state
from qualcoder_api.services import user_settings as user_settings_mod
from qualcoder_api.services.project_service import ProjectService


@pytest.fixture
async def collab_svc(tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    s = ProjectService()
    await s.create_project(str(tmp_path / "C.qda"), codername="alice")
    # Two real coders so the activation gate passes.
    async with s.session_factory() as session:
        for name in ("alice", "bob"):
            await session.execute(
                text("INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"),
                {"n": name},
            )
        await session.commit()
    user_settings.save_sync_settings(True)
    yield s, str(tmp_path / "C.qda")
    await s.close_project()
    marker = project_marker.read_marker(str(tmp_path / "C.qda"))
    if marker:
        sandbox.remove_sandbox(marker["uuid"])


async def test_activate_writes_marker_and_sandbox(collab_svc):
    svc, path = collab_svc
    sync.set_current_user("alice")
    result = await svc.activate_collaboration(codername="alice")
    assert result["ok"] is True
    assert svc.collaboration_mode() is True
    assert svc.uuid
    assert project_marker.marker_exists(path) is True
    assert sandbox.sandbox_exists(svc.uuid, svc._sandbox_instance()) is True
    # Idempotent.
    again = await svc.activate_collaboration(codername="alice")
    assert again["ok"] is False


async def test_activate_requires_two_coders(tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "Solo.qda"), codername="solo")
    user_settings.save_sync_settings(True)
    try:
        sync.set_current_user("solo")
        result = await svc.activate_collaboration(codername="solo")
        assert result["ok"] is False
        assert "coder" in result["reason"]
    finally:
        await svc.close_project()


async def test_close_consolidates_and_reopens_in_collab(collab_svc):
    svc, path = collab_svc
    sync.set_current_user("alice")
    await svc.activate_collaboration(codername="alice")
    async with svc.session_factory() as session:
        await CodeRepository(session).add_code(name="fear", owner="alice")
    await svc.close_project()

    # The cold archive now holds the code.
    conn = await aiosqlite.connect(Path(path) / "data.qda")
    cur = await conn.cursor()
    await cur.execute("SELECT COUNT(*) FROM code_name")
    assert (await cur.fetchone())[0] == 1
    await conn.close()

    # Reopen: collaboration mode, sandbox is the live DB, code present.
    opener = ProjectService()
    result = await opener.open_project(path, codername="alice")
    try:
        assert result.ok is True
        assert opener.collaboration_mode() is True
        async with opener.session_factory() as session:
            count = (await session.execute(text("SELECT COUNT(*) FROM code_name"))).scalar()
        assert count == 1
    finally:
        await opener.close_project()
    marker = project_marker.read_marker(path)
    if marker:
        sandbox.remove_sandbox(marker["uuid"])


async def test_close_merge_writes_watermark_and_cleans_replays(collab_svc):
    """Closing the sole session (the admin) snapshots the master, records
    ``replays/merged.json`` with the merged session, and deletes the merged
    replay — so replays don't pile up and a fresh opener rebuilds from the
    master + watermark."""
    import json

    from qualcoder_api.persistence.repositories import CodeRepository

    svc, path = collab_svc
    sync.set_current_user("alice")
    await svc.activate_collaboration(codername="alice")
    sid = svc.current_session_id
    async with svc.session_factory() as session:
        await CodeRepository(session).add_code(name="fear", owner="alice")
    await svc.close_project()

    replays = Path(path) / "replays"
    merged = replays / "merged.json"
    assert merged.exists()
    wm = json.loads(merged.read_text(encoding="utf-8"))
    assert sid in wm.get("merged_sessions", [])
    # The merged replay is gone (merged into master + implicitly acked).
    assert not (replays / f"{sid}.jsonl").exists()


async def test_revert_returns_to_single_coder(collab_svc):
    svc, path = collab_svc
    sync.set_current_user("alice")
    await svc.activate_collaboration(codername="alice")
    result = await svc.revert_collaboration()
    assert result["ok"] is True
    assert svc.collaboration_mode() is False
    assert project_marker.marker_exists(path) is False
    # data.qda is the live DB again.
    conn = await aiosqlite.connect(Path(path) / "data.qda")
    cur = await conn.cursor()
    await cur.execute("SELECT COUNT(*) FROM project")
    assert (await cur.fetchone())[0] == 1
    await conn.close()


# ── API level ────────────────────────────────────────────────────────────

@pytest.fixture
async def api_collab(tmp_path, monkeypatch):
    """API client with an open project seeded for collaboration activation."""
    from httpx import ASGITransport, AsyncClient

    from qualcoder_api.main import app, service
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "api-collab.qda"
        res = await c.post(
            "/api/v1/projects",
            json={"project_path": str(target), "codername": "alice"},
        )
        assert res.status_code == 200, res.text
        # Seed a second coder + enable sync through the shared service.
        async with service.session_factory() as session:
            for name in ("alice", "bob"):
                await session.execute(
                    text("INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"),
                    {"n": name},
                )
            await session.commit()
        user_settings.save_sync_settings(True)
        yield c, str(target), service
        await c.post("/api/v1/projects/close")
        marker = project_marker.read_marker(str(target))
        if marker:
            sandbox.remove_sandbox(marker["uuid"])


async def test_api_mode_and_activate_revert(api_collab):
    c, _target, _service = api_collab
    sync.set_current_user("alice")

    # Initially single mode.
    res = await c.get("/api/v1/projects/mode")
    assert res.status_code == 200
    assert res.json()["mode"] == "single"

    # Activate.
    res = await c.post("/api/v1/projects/activate-collaboration")
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    res = await c.get("/api/v1/projects/mode")
    assert res.json()["mode"] == "collaboration"

    # Revert.
    res = await c.post("/api/v1/projects/revert-collaboration")
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    res = await c.get("/api/v1/projects/mode")
    assert res.json()["mode"] == "single"


async def test_api_activate_409_without_two_coders(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from qualcoder_api.main import app
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "api-solo.qda"
        await c.post(
            "/api/v1/projects",
            json={"project_path": str(target), "codername": "solo"},
        )
        user_settings.save_sync_settings(True)
        res = await c.post("/api/v1/projects/activate-collaboration")
        assert res.status_code == 409, res.text
        assert "coder" in res.json()["detail"]
        await c.post("/api/v1/projects/close")


# ── Two instances, one shared folder ─────────────────────────────────────
# The suite previously covered only single-sandbox flows, so divergent
# counts between real instances slipped through.  Each machine below gets
# its own sandbox instance id, sync-state file, settings file and coder.


@pytest.fixture
async def two_machines(tmp_path, monkeypatch):
    """Yield (make, use) for two ProjectServices sharing one folder."""
    import contextlib

    holder = {"id": "AAAAAAAAAAAA"}
    monkeypatch.setattr(user_settings_mod, "get_instance_id", lambda: holder["id"])
    monkeypatch.setattr(
        sync_state, "_state_path",
        lambda project_path: tmp_path / f"syncstate_{holder['id']}.json",
    )
    made: list[ProjectService] = []

    def use(mid: str) -> None:
        holder["id"] = mid
        monkeypatch.setattr(
            user_settings_mod, "SETTINGS_FILE", tmp_path / f"settings_{mid}.json"
        )

    async def make(mid: str) -> ProjectService:
        use(mid)
        svc = ProjectService()
        svc._sandbox_instance = (lambda m=mid: m)  # type: ignore[method-assign]
        made.append(svc)
        return svc

    yield make, use
    for svc in made:
        with contextlib.suppress(Exception):
            await svc.close_project()
    marker = project_marker.read_marker(str(tmp_path / "shared.qda"))
    if marker:
        sandbox.remove_sandbox(marker["uuid"])


async def test_join_from_stale_archive_heals(two_machines, tmp_path):
    """A joiner seeded from a stale cold archive must converge.

    The archive copy drags a foreign change journal with it: without the
    open-time scrub the joiner re-exports that history as its own (stale
    re-exports resurrect rows peers deleted), and with advanced watermarks
    the sidecars that reconcile the stale seed are skipped forever.
    """
    make, use = two_machines
    shared = str(tmp_path / "shared.qda")

    async def file_names(svc) -> list[str]:
        async with svc.session_factory() as session:
            rows = await session.execute(text("SELECT name FROM source ORDER BY id"))
            return [r[0] for r in rows]

    async def cycle(svc):
        return await sync_engine.run_sync_cycle(
            svc.session_factory, svc.project_path, svc.current_session_id
        )

    # Machine A: create, second coder, activate, 3 files, close (merge).
    a = await make("AAAAAAAAAAAA")
    sync.set_current_user("alice")
    await a.create_project(shared, codername="alice")
    async with a.session_factory() as session:
        for name in ("alice", "bob"):
            await session.execute(
                text("INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"),
                {"n": name},
            )
        await session.commit()
    user_settings_mod.save_sync_settings(True)
    assert (await a.activate_collaboration(codername="alice"))["ok"] is True
    async with a.session_factory() as session:
        for i in range(3):
            await SourceRepository(session).add_source(
                name=f"f{i}.txt", fulltext="x", mediapath=f"/docs/f{i}.txt", owner="alice"
            )
    await a.close_project()

    # A reopens, deletes 2 of 3, exports, stays open (archive now stale).
    use("AAAAAAAAAAAA")
    sync.set_current_user("alice")
    assert (await a.open_project(shared, codername="alice")).ok is True
    async with a.session_factory() as session:
        ids = (await session.execute(text("SELECT id FROM source ORDER BY id"))).all()
        for (i,) in ids[1:]:
            await SourceRepository(session).delete_source(int(i))
    assert await file_names(a) == ["f0.txt"]
    assert (await cycle(a))["ok"] is True

    # Machine B joins fresh while A is still open.
    b = await make("BBBBBBBBBBBB")
    use("BBBBBBBBBBBB")
    sync.set_current_user("bob")
    user_settings_mod.save_sync_settings(True)
    assert (await b.open_project(shared, codername="bob")).ok is True

    # The join must not re-export the archive's foreign journal as its own.
    first = await cycle(b)
    assert first["ok"] is True
    assert first["exported"] == 0

    # Steady-state cycles on both sides converge to A's exact state.
    for _ in range(3):
        use("AAAAAAAAAAAA")
        sync.set_current_user("alice")
        await cycle(a)
        use("BBBBBBBBBBBB")
        sync.set_current_user("bob")
        await cycle(b)
    assert await file_names(a) == ["f0.txt"]
    assert await file_names(b) == ["f0.txt"]


async def test_close_skips_merge_when_converge_fails(two_machines, tmp_path, monkeypatch):
    """A last-closer whose final import fails must NOT merge.

    Merging snapshots an incomplete sandbox while the watermark records —
    and the cleanup deletes — replays whose rows would then be lost from
    shared state forever (peers already trimmed them on export).  Skipping
    leaves the evidence; the next clean close merges and heals.
    """
    make, use = two_machines
    shared = str(tmp_path / "shared.qda")

    async def master_names() -> list[str]:
        conn = await aiosqlite.connect(str(Path(shared) / "data.qda"))
        try:
            cur = await conn.cursor()
            await cur.execute("SELECT name FROM source ORDER BY id")
            return [r[0] for r in await cur.fetchall()]
        finally:
            await conn.close()

    def live_replays() -> list[str]:
        replays = Path(shared) / "replays"
        if not replays.is_dir():
            return []
        return sorted(p.name for p in replays.glob("*.jsonl"))

    async def cycle(svc):
        return await sync_engine.run_sync_cycle(
            svc.session_factory, svc.project_path, svc.current_session_id
        )

    from qualcoder_api.persistence.repositories import SourceRepository

    a = await make("AAAAAAAAAAAA")
    sync.set_current_user("alice")
    await a.create_project(shared, codername="alice")
    async with a.session_factory() as session:
        for name in ("alice", "bob"):
            await session.execute(
                text("INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"),
                {"n": name},
            )
        await session.commit()
    user_settings_mod.save_sync_settings(True)
    assert (await a.activate_collaboration(codername="alice"))["ok"] is True

    b = await make("BBBBBBBBBBBB")
    use("BBBBBBBBBBBB")
    sync.set_current_user("bob")
    assert (await b.open_project(shared, codername="bob")).ok is True

    # B adds a file and exports it (journal trimmed afterwards).
    async with b.session_factory() as session:
        await SourceRepository(session).add_source(
            name="b-only.txt", fulltext="x", mediapath="/docs/b-only.txt", owner="bob"
        )
    assert (await cycle(b))["exported"] == 1
    # B closes first; A still open so no merge happens yet.
    await b.close_project()

    # A's last close with a sabotaged final import: the merge must be
    # withheld, the master untouched, and B's replay preserved.
    real_import = sync.import_pending

    async def boom_import(session, project_path, instance_id):
        raise RuntimeError("simulated import failure (locked db)")

    monkeypatch.setattr(sync, "import_pending", boom_import)
    use("AAAAAAAAAAAA")
    sync.set_current_user("alice")
    await a.close_project()
    assert await master_names() == []
    assert live_replays() != []

    # Next clean close merges and heals: the master gains B's file.
    # (Restore just the sabotage — the fixture's identity patches stay.)
    monkeypatch.setattr(sync, "import_pending", real_import)
    use("AAAAAAAAAAAA")
    sync.set_current_user("alice")
    assert (await a.open_project(shared, codername="alice")).ok is True
    await a.close_project()
    assert await master_names() == ["b-only.txt"]
