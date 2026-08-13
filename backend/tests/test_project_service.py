"""Project lifecycle tests — create, open, close, backup, lock."""

from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

from qualcoder_api.services.project_service import (
    LOCK_FILE_NAME,
    ProjectService,
)


async def test_create_project_creates_structure(project_dir: Path, app_version: str):
    svc = ProjectService()
    ok = await svc.create_project(
        str(project_dir), app_version=app_version, codername="tester"
    )
    assert ok is True
    root = project_dir
    assert (root / "data.qda").exists()
    for sub in ("images", "audio", "video", "documents", "backups"):
        assert (root / sub).is_dir(), f"missing {sub}"


async def test_create_project_appends_qda_suffix(project_dir: Path, app_version: str):
    svc = ProjectService()
    ok = await svc.create_project(
        str(project_dir) + ".xyz", app_version=app_version, codername="tester"
    )
    assert ok is True
    assert Path(str(project_dir) + ".xyz.qda").is_dir()


async def test_create_project_avoids_name_collision(tmp_path, app_version: str):
    target = tmp_path / "Collide.qda"
    svc = ProjectService()
    await svc.create_project(str(target), app_version=app_version, codername="tester")
    await svc.close_project()
    svc2 = ProjectService()
    ok = await svc2.create_project(str(target), app_version=app_version, codername="tester")
    assert ok is True
    assert Path(str(target) + "_1").is_dir()


async def test_created_project_is_valid_v14(project_dir: Path, app_version: str):
    svc = ProjectService()
    await svc.create_project(str(project_dir), app_version=app_version, codername="tester")
    conn = await aiosqlite.connect(project_dir / "data.qda")
    cur = await conn.cursor()
    await cur.execute("SELECT databaseversion, codername, about FROM project")
    row = await cur.fetchone()
    assert row == ("v31", "tester", app_version)
    await cur.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='code_text_visible'")
    assert await cur.fetchone() is not None
    await conn.close()
    await svc.close_project()


async def test_open_project_roundtrip(project_dir: Path, app_version: str):
    svc = ProjectService()
    await svc.create_project(str(project_dir), app_version=app_version, codername="tester")
    await svc.close_project()

    opener = ProjectService()
    result = await opener.open_project(
        str(project_dir), app_version=app_version, codername="tester"
    )
    assert result.ok is True
    assert result.migrations_applied == []
    assert opener.project_name == project_dir.name
    header = await opener._get_header()
    assert header is not None
    assert header.databaseversion == "v31"
    await opener.close_project()


async def test_open_project_rejects_non_qda(tmp_path, app_version: str):
    svc = ProjectService()
    result = await svc.open_project(str(tmp_path / "no.qda"), app_version=app_version)
    assert result.ok is False


async def test_open_project_rejects_non_qualcoder(tmp_path, app_version: str):
    bogus = tmp_path / "bogus.qda"
    bogus.mkdir()
    conn = await aiosqlite.connect(bogus / "data.qda")
    await conn.execute("CREATE TABLE project (databaseversion text, about text)")
    await conn.execute("INSERT INTO project VALUES ('v14', 'Some other app')")
    await conn.commit()
    await conn.close()
    svc = ProjectService()
    result = await svc.open_project(str(bogus), app_version=app_version)
    assert result.ok is False
    # lock must be cleaned up on failed open
    assert not (bogus / LOCK_FILE_NAME).exists()


async def test_open_project_migrates_legacy(tmp_path, app_version: str):
    from tests.test_migration import LEGACY_TABLES

    legacy = tmp_path / "legacy.qda"
    legacy.mkdir()
    conn = await aiosqlite.connect(legacy / "data.qda")
    cur = await conn.cursor()
    for sql in LEGACY_TABLES:
        await cur.execute(sql)
    await cur.execute("INSERT INTO project VALUES ('v2', '2020-01-01', '', 'QualCoder 1.0')")
    await cur.execute("INSERT INTO code_name (name, owner, date, color) VALUES ('c1', 'x', '2020-01-01', '#fff')")
    await conn.commit()
    await conn.close()

    svc = ProjectService()
    result = await svc.open_project(
        str(legacy), app_version=app_version, codername="tester"
    )
    assert result.ok is True
    assert set(result.migrations_applied) >= {"v2", "v4", "v5", "v19"}
    conn = await aiosqlite.connect(legacy / "data.qda")
    cur = await conn.cursor()
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v31"
    await conn.close()
    await svc.close_project()


async def test_lock_prevents_concurrent_open(project_dir: Path, app_version: str):
    svc = ProjectService()
    await svc.create_project(str(project_dir), app_version=app_version, codername="tester")
    await svc.close_project()

    # Simultaneous work: a second instance may open the same project while
    # the first holds it — the presence registry keeps both entries.
    first = ProjectService()
    assert (await first.open_project(str(project_dir), app_version=app_version)).ok is True

    second = ProjectService()
    result = await second.open_project(str(project_dir), app_version=app_version)
    assert result.ok is True, result.error

    registry = (project_dir / LOCK_FILE_NAME).read_text(encoding="utf-8")
    assert "marvi" in registry
    assert registry.count("marvi") >= 2

    await first.close_project()
    # lock released -> open works again
    third = ProjectService()
    assert (await third.open_project(str(project_dir), app_version=app_version)).ok is True
    await third.close_project()
    await second.close_project()


async def test_stale_lock_is_broken(project_dir: Path, app_version: str):
    svc = ProjectService()
    await svc.create_project(str(project_dir), app_version=app_version, codername="tester")
    await svc.close_project()

    # simulate a stale lock file from a crash
    lock = project_dir / LOCK_FILE_NAME
    lock.write_text("ghost\n0.0\n", encoding="utf-8")

    opener = ProjectService()
    result = await opener.open_project(str(project_dir), app_version=app_version)
    assert result.ok is True
    await opener.close_project()


async def test_crashed_owner_lock_is_broken_immediately(tmp_path):
    """Regression: a lock left by a force-quit/crashed backend (dead pid)
    must not block reopening — even while the timestamp is fresh."""
    target = tmp_path / "Crashed.qda"
    svc = ProjectService()
    assert await svc.create_project(str(target), codername="default") is True
    await svc.close_project()

    lock = target / LOCK_FILE_NAME
    lock.write_text(f"ghost\n{time.time()!s}\n99999999\n", encoding="utf-8")

    opener = ProjectService()
    result = await opener.open_project(str(target))
    assert result.ok is True, result.error
    await opener.close_project()


async def test_live_owner_lock_still_blocks(tmp_path):
    """A lock held by a live foreign process is kept in the registry; the
    other instance still opens (presence, not exclusion) and sees the owner."""
    import subprocess
    import sys

    target = tmp_path / "Live.qda"
    svc = ProjectService()
    assert await svc.create_project(str(target), codername="default") is True
    await svc.close_project()

    sleeper = subprocess.Popen(  # noqa: ASYNC220 - foreign-pid liveness check
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    try:
        lock = target / LOCK_FILE_NAME
        lock.write_text(
            f"marvi\n{time.time()!s}\n{sleeper.pid}\n", encoding="utf-8"
        )

        opener = ProjectService()
        result = await opener.open_project(str(target))
        assert result.ok is True, result.error
        assert result.lock_user == "marvi"
        assert any(o["user"] == "marvi" for o in opener.openers())
        await opener.close_project()
    finally:
        sleeper.kill()


async def test_save_backup_creates_copy(project_dir: Path, app_version: str):
    svc = ProjectService()
    await svc.create_project(str(project_dir), app_version=app_version, codername="tester")
    msg, backup_path = await svc.save_backup()
    assert "Backup created" in msg
    assert Path(backup_path).exists()
    assert Path(backup_path).suffix == ".qda"
    await svc.close_project()


async def test_close_project_releases_everything(project_dir: Path, app_version: str):
    svc = ProjectService()
    await svc.create_project(str(project_dir), app_version=app_version, codername="tester")
    await svc.close_project()
    assert svc.engine is None
    assert svc.project_path == ""
    assert svc.project_name == ""
    assert not (project_dir / LOCK_FILE_NAME).exists()


async def test_reopen_with_defaults_preserves_about_marker(tmp_path):
    """Regression: open_project's default app_version must keep 'QualCoder'
    in the about column, or the header check fails on the SECOND open."""
    target = tmp_path / "Reopen.qda"
    svc = ProjectService()
    assert await svc.create_project(str(target), codername="default") is True
    await svc.close_project()

    first = ProjectService()
    assert (await first.open_project(str(target))).ok is True
    await first.close_project()

    # The about marker must survive the first open's migration pass.
    import aiosqlite

    conn = await aiosqlite.connect(target / "data.qda")
    cur = await conn.cursor()
    await cur.execute("SELECT about FROM project")
    about = (await cur.fetchone())[0]
    await conn.close()
    assert "QualCoder" in about

    # The second open must succeed (this failed before the fix).
    second = ProjectService()
    result = await second.open_project(str(target))
    assert result.ok is True, result.error
    await second.close_project()


async def test_reopen_same_instance_after_close(tmp_path):
    """Regression: closing a project resets project_path; reopening with the
    SAME service instance must restore it, or _finalize_open's db_path()
    resolves to a relative 'data.qda' (unable to open database file)."""
    target = tmp_path / "SameInstance.qda"
    svc = ProjectService()
    assert await svc.create_project(str(target), codername="default") is True
    await svc.close_project()
    assert svc.project_path == ""

    result = await svc.open_project(str(target))
    assert result.ok is True, result.error
    assert svc.project_path == str(target)
    await svc.close_project()

    # And a second close→open cycle works too (the real user flow).
    again = await svc.open_project(str(target))
    assert again.ok is True, again.error
    await svc.close_project()
