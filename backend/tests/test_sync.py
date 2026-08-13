"""Collaboration sync tests (Option B: change-log sidecars).

The critical scenario: two raters work on SEPARATE copies of the same
project; the sidecar change files are exchanged (simulated by copying the
``changes/`` folders between the two project copies); each rater imports
the other's sidecar and the projects converge.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    AttributeRepository,
    CaseRepository,
    CodeRepository,
    CodingRepository,
    JournalRepository,
    SourceRepository,
)
from qualcoder_api.services import sync
from qualcoder_api.services.project_service import ProjectService


@pytest.fixture
async def rater_a(tmp_path):
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "A.qda"), codername="anna")
    assert svc.session_factory is not None
    yield svc
    await svc.close_project()


@pytest.fixture
async def rater_b(tmp_path):
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "B.qda"), codername="berta")
    assert svc.session_factory is not None
    yield svc
    await svc.close_project()


@pytest.fixture
async def project_client(tmp_path, monkeypatch):
    """API client with a fresh open project (endpoint tests).

    The sync switch lives in the per-machine settings file — isolate it so
    endpoint tests never read or write the developer's real settings."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "sync-api.qda"
        res = await c.post("/api/v1/projects", json={"project_path": str(target), "codername": "tester"})
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


def _copy_changes(src_project: str, dst_project: str) -> None:
    src = Path(src_project) / sync.SYNC_DIR_NAME
    dst = Path(dst_project) / sync.SYNC_DIR_NAME
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


async def _export(svc, user: str) -> None:
    async with svc.session_factory() as session:
        await sync.export_pending(session, svc.project_path, user)


async def test_capture_records_mutations(rater_a):
    svc = rater_a
    sync.set_current_user("anna")
    async with svc.session_factory() as session:
        repo = CodeRepository(session)
        code = await repo.add_code(name="fear", owner="anna")
        assert code is not None
        row = (
            await session.execute(
                tables.sync_log.select().where(tables.sync_log.c.entity == "code_name")
            )
        ).first()
        assert row is not None
        assert row.seq == 1
        assert row.user == "anna"
        assert json.loads(row.row_json)["name"] == "fear"
        # a second mutation increments the per-user seq
        await repo.add_code(name="joy", owner="anna")
        row2 = (
            await session.execute(
                tables.sync_log.select()
                .where(tables.sync_log.c.entity == "code_name")
                .order_by(tables.sync_log.c.id.desc())
            )
        ).first()
        assert row2.seq == 2


async def test_replay_does_not_recapture(rater_a, rater_b):
    """Applying another rater's changes must not create new sync_log rows."""
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await CodeRepository(session).add_code(name="alien", owner="berta")
    await _export(rater_b, "berta")
    _copy_changes(rater_b.project_path, rater_a.project_path)
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        report = await sync.import_pending(session, rater_a.project_path, "anna")
        assert report["berta"]["applied"] >= 1
        count = (
            await session.execute(
                tables.sync_log.select().where(tables.sync_log.c.user == "anna")
            )
        ).all()
        assert len(count) == 0


async def test_two_rater_roundtrip_converges(rater_a, rater_b):
    """The full collaboration scenario: both raters code/rename/delete,
    exchange sidecars, and both projects converge to the union."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        source = await SourceRepository(session).add_source(
            name="interview.txt", fulltext="alpha beta gamma", mediapath="/docs/interview.txt",
            owner="anna",
        )
        code_a = await CodeRepository(session).add_code(name="fear", owner="anna")
        await CodingRepository(session).add_text_coding(
            cid=code_a.cid, fid=source.id, seltext="alpha", pos0=0, pos1=5,
            owner="anna",
        )
        await CaseRepository(session).add_case(name="case_one", owner="anna")
        await JournalRepository(session).add_journal(name="log", jentry="day one", owner="anna")

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        source_b = await SourceRepository(session).add_source(
            name="focus.txt", fulltext="hello world", mediapath="/docs/focus.txt",
            owner="berta",
        )
        code_b = await CodeRepository(session).add_code(name="hope", owner="berta")
        await CodingRepository(session).add_text_coding(
            cid=code_b.cid, fid=source_b.id, seltext="hello", pos0=0, pos1=5,
            owner="berta",
        )
        await AttributeRepository(session).add_type(
            name="age", owner="berta", case_or_file="case", value_type="number"
        )

    # Export both sidecars, then exchange them.
    await _export(rater_a, "anna")
    await _export(rater_b, "berta")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    _copy_changes(rater_b.project_path, rater_a.project_path)

    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        report = await sync.import_pending(session, rater_a.project_path, "anna")
        assert "berta" in report
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert "anna" in report

    # Convergence: both projects end up with the union of both raters' data.
    expected = {
        "source": 2,
        "code_name": 2,
        "code_text": 2,
        "cases": 1,
        "journal": 1,
        "attribute_type": 1,
    }
    for svc in (rater_a, rater_b):
        async with svc.session_factory() as session:
            for table, want in expected.items():
                n = (await session.execute(tables.metadata.tables[table].select())).scalars().all()
                assert len(n) == want, f"{table}: {len(n)} != {want}"

    # Owners preserved.
    async with rater_a.session_factory() as session:
        codings = (await session.execute(tables.code_text.select())).all()
        assert {c.owner for c in codings} == {"anna", "berta"}


async def test_delete_propagates(rater_a, rater_b):
    """Deleting a source on one side removes its codings on the other."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        source = await SourceRepository(session).add_source(
            name="x.txt", fulltext="some text", mediapath="/docs/x.txt", owner="anna"
        )
        code = await CodeRepository(session).add_code(name="c", owner="anna")
        await CodingRepository(session).add_text_coding(
            cid=code.cid, fid=source.id, seltext="some", pos0=0, pos1=4, owner="anna"
        )
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await sync.import_pending(session, rater_b.project_path, "berta")
        # Now berta deletes the source.
        await SourceRepository(session).delete_source(source.id)
    await _export(rater_b, "berta")
    _copy_changes(rater_b.project_path, rater_a.project_path)
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        report = await sync.import_pending(session, rater_a.project_path, "anna")
        assert report["berta"]["applied"] >= 1
        assert len((await session.execute(tables.source.select())).scalars().all()) == 0
        assert len((await session.execute(tables.code_text.select())).scalars().all()) == 0


async def test_pk_collision_remaps_and_updates_follow(rater_a, rater_b):
    """Both raters create a coding with ctid=1; the second import remaps the
    colliding row and later updates/deletes of that row still land on it —
    without touching the other rater's own ctid=1 row."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        source_a = await SourceRepository(session).add_source(
            name="a.txt", fulltext="alpha", mediapath="/docs/a.txt", owner="anna"
        )
        code_a = await CodeRepository(session).add_code(name="ac", owner="anna")
        coding_a = await CodingRepository(session).add_text_coding(
            cid=code_a.cid, fid=source_a.id, seltext="alpha", pos0=0, pos1=5, owner="anna"
        )
        assert coding_a.ctid == 1

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        source_b = await SourceRepository(session).add_source(
            name="b.txt", fulltext="beta", mediapath="/docs/b.txt", owner="berta"
        )
        code_b = await CodeRepository(session).add_code(name="bc", owner="berta")
        coding_b = await CodingRepository(session).add_text_coding(
            cid=code_b.cid, fid=source_b.id, seltext="beta", pos0=0, pos1=4, owner="berta"
        )
        assert coding_b.ctid == 1

    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        # berta's own ctid=1 exists; anna's row must be remapped (different
        # natural keys), not lost and not reported as a conflict.
        assert report["anna"]["conflicts"] == []
        codings = (await session.execute(tables.code_text.select())).all()
        assert len(codings) == 2
        anna_row = next(c for c in codings if c.owner == "anna")
        assert anna_row.ctid != 1

    # anna edits her coding; berta imports and the memo lands on anna's
    # remapped row while berta's own ctid=1 stays untouched.
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await CodingRepository(session).update_text_coding(coding_a.ctid, memo="edited")
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["conflicts"] == []
        codings = (await session.execute(tables.code_text.select())).all()
        assert len(codings) == 2
        anna_row = next(c for c in codings if c.owner == "anna")
        berta_row = next(c for c in codings if c.owner == "berta")
        assert anna_row.memo == "edited"
        assert berta_row.memo == ""

    # anna deletes her OWN source; berta imports: anna's source and coding
    # vanish, berta's own source and coding survive (id isolation).
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await SourceRepository(session).delete_source(source_a.id)
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["conflicts"] == []
        sources = (await session.execute(tables.source.select())).all()
        assert [s.name for s in sources] == ["b.txt"]
        codings = (await session.execute(tables.code_text.select())).all()
        assert [c.owner for c in codings] == ["berta"]


async def test_sync_endpoints(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/sync/status")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["enabled"] is False  # the switch is off by default
    assert "last_sync" in body
    # Toggle on and verify the setting sticks + status reflects it.
    res = await client.put("/api/v1/sync/settings", json={"enabled": True})
    assert res.status_code == 200
    assert res.json()["enabled"] is True
    res = await client.get("/api/v1/sync/settings")
    assert res.json()["enabled"] is True
    res = await client.get("/api/v1/sync/status")
    assert res.json()["enabled"] is True
    res = await client.post("/api/v1/sync/now")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["exported"] == 0  # nothing mutated yet
    res = await client.put("/api/v1/sync/settings", json={"enabled": False})
    assert res.json()["enabled"] is False


# ----------------------------------------------------------------------
# Shared-folder detection (auto-enable on project open)
# ----------------------------------------------------------------------

async def test_detect_shared_changes_dir_with_foreign_sidecars(rater_a):
    """A changes/ folder holding ANOTHER rater's sidecar marks the project
    as shared (the current user's own sidecar does not)."""
    changes = Path(rater_a.project_path) / sync.SYNC_DIR_NAME
    (changes / "berta").mkdir(parents=True)
    (changes / "berta" / "changes.jsonl").write_text("", encoding="utf-8")
    result = sync.detect_shared(rater_a.project_path, user="anna")
    assert result == {"shared": True, "reason": "change sidecars from other raters"}
    # The rater's own sidecar alone is not evidence of sharing.
    (changes / "anna").mkdir(parents=True)
    (changes / "anna" / "changes.jsonl").write_text("", encoding="utf-8")
    (changes / "berta" / "changes.jsonl").unlink()
    (changes / "berta").rmdir()
    assert sync.detect_shared(rater_a.project_path, user="anna") == {
        "shared": False,
        "reason": "not a shared folder",
    }


def test_detect_shared_marker(tmp_path):
    project = tmp_path / "M.qda"
    project.mkdir()
    (project / ".qcnext-shared").write_text("", encoding="utf-8")
    assert sync.detect_shared(str(project)) == {
        "shared": True,
        "reason": "shared-folder marker",
    }


def test_detect_shared_unc_path(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "nt")
    project = tmp_path / "N.qda"
    project.mkdir()
    assert sync.detect_shared("\\\\server\\share\\N.qda") == {
        "shared": True,
        "reason": "network path (UNC)",
    }


def test_detect_shared_plain_folder(tmp_path):
    project = tmp_path / "P.qda"
    project.mkdir()
    assert sync.detect_shared(str(project)) == {
        "shared": False,
        "reason": "not a shared folder",
    }


async def test_auto_enable_decision_honors_override(rater_a, tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    (Path(rater_a.project_path) / ".qcnext-shared").write_text("", encoding="utf-8")
    # "auto" (default) follows the detection.
    assert sync.auto_enable_decision(rater_a.project_path) == {
        "sync_auto_enabled": True,
        "reason": "shared-folder marker",
    }
    # "off" wins over a detected shared folder.
    user_settings.set_sync_override(rater_a.project_path, "off")
    assert sync.auto_enable_decision(rater_a.project_path) == {
        "sync_auto_enabled": False,
        "reason": "per-project override",
    }
    # "on" forces sync on even for a plain folder.
    (Path(rater_a.project_path) / ".qcnext-shared").unlink()
    user_settings.set_sync_override(rater_a.project_path, "on")
    assert sync.auto_enable_decision(rater_a.project_path) == {
        "sync_auto_enabled": True,
        "reason": "per-project override",
    }


async def test_sync_auto_detect_endpoint(project_client):
    client, target = project_client
    res = await client.get("/api/v1/sync/auto-detect", params={"project_path": str(target)})
    assert res.status_code == 200
    assert res.json() == {"shared": False, "reason": "not a shared folder"}
    (target / ".qcnext-shared").write_text("", encoding="utf-8")
    res = await client.get("/api/v1/sync/auto-detect", params={"project_path": str(target)})
    assert res.json()["shared"] is True


async def test_sync_override_endpoint(project_client):
    client, target = project_client
    res = await client.put(
        "/api/v1/sync/override", json={"project_path": str(target), "mode": "off"}
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "project_path": str(target), "mode": "off"}
    res = await client.put(
        "/api/v1/sync/override", json={"project_path": str(target), "mode": "sometimes"}
    )
    assert res.status_code == 422


async def test_open_result_reports_sync_auto_enable(project_client):
    """The open result carries the shared-folder decision; the per-project
    override wins over the detection."""
    client, target = project_client
    await client.post("/api/v1/projects/close")
    res = await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    body = res.json()
    assert body["ok"] is True
    assert body["sync_auto_enabled"] is False
    assert body["sync_auto_reason"] == "not a shared folder"
    await client.post("/api/v1/projects/close")
    (target / ".qcnext-shared").write_text("", encoding="utf-8")
    res = await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    assert res.json()["sync_auto_enabled"] is True
    await client.post("/api/v1/projects/close")
    await client.put(
        "/api/v1/sync/override", json={"project_path": str(target), "mode": "off"}
    )
    res = await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    assert res.json()["sync_auto_enabled"] is False
