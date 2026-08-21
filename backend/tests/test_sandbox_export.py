"""Full-state export + sandbox rebuild tests (Golden Master collaboration)."""

from __future__ import annotations

import pytest

from qualcoder_api.persistence import database
from qualcoder_api.persistence.repositories import CodeRepository, SourceRepository
from qualcoder_api.services import sync, sync_engine
from qualcoder_api.services.project_service import ProjectService
from qualcoder_api.services.sandbox import (
    create_fresh_sandbox,
    remove_sandbox,
    sandbox_path,
)

UUID = "test-sandbox-uuid"


@pytest.fixture
async def svc(tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    s = ProjectService()
    await s.create_project(str(tmp_path / "P.qda"), codername="alice")
    yield s
    await s.close_project()
    remove_sandbox(UUID)


async def test_export_full_state_emits_all_rows(svc):
    sync.set_current_user("alice")
    async with svc.session_factory() as session:
        await CodeRepository(session).add_code(name="fear", owner="alice")
        await SourceRepository(session).add_source(
            name="doc1.txt", fulltext="hello world", owner="alice"
        )
    async with svc.session_factory() as session:
        report = await sync.export_full_state(session, svc.project_path, "inst1")
    assert report["exported"] >= 3  # project + code + source

    # The snapshot marker is recorded in the state file.
    state = sync.load_state(svc.project_path)
    assert state.get("snapshot", {}).get("instance") == "inst1"


async def test_max_sidecar_seq(svc):
    sync.set_current_user("alice")
    async with svc.session_factory() as session:
        await CodeRepository(session).add_code(name="fear", owner="alice")
    async with svc.session_factory() as session:
        await sync.export_full_state(session, svc.project_path, "inst1")
    assert sync_engine._max_sidecar_seq(svc.project_path) > 0


async def test_rebuild_from_sidecars_reconstructs(svc):
    sync.set_current_user("alice")
    async with svc.session_factory() as session:
        await CodeRepository(session).add_code(name="fear", owner="alice")
        await SourceRepository(session).add_source(
            name="doc1.txt", fulltext="hello world", owner="alice"
        )
    async with svc.session_factory() as session:
        await sync.export_full_state(session, svc.project_path, "inst1")

    # Simulate a lost sandbox: create a fresh one and rebuild from sidecars.
    await create_fresh_sandbox(UUID, codername="alice")
    target = sandbox_path(UUID)
    engine = database.create_project_engine(str(target))
    try:
        factory = database.create_session_factory(engine)
        rebuild = await sync.rebuild_from_sidecars(factory, svc.project_path, "inst1")
        assert rebuild["applied"] >= 3
        async with factory() as session:
            from sqlalchemy import text

            code_count = (await session.execute(text("SELECT COUNT(*) FROM code_name"))).scalar()
            src_count = (await session.execute(text("SELECT COUNT(*) FROM source"))).scalar()
            proj_count = (await session.execute(text("SELECT COUNT(*) FROM project"))).scalar()
    finally:
        await engine.dispose()

    assert code_count == 1
    assert src_count == 1
    assert proj_count == 1
