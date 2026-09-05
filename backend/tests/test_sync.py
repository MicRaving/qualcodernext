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
from qualcoder_api.services import sync, sync_engine
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


async def test_r_script_roundtrip_converges(rater_a, rater_b):
    """Saved R scripts are journaled to sync_log AND travel through the
    sidecar to collaborators (r_script must be in SYNC_ENTITIES)."""
    sync.set_current_user("anna")
    ts = "2026-01-01T00:00:00Z"
    async with rater_a.session_factory() as session:
        from sqlalchemy import insert
        result = await session.execute(
            insert(tables.r_script).values(
                name="plot.R", script="plot(1:10)", owner="anna",
                created=ts, updated=ts,
            )
        )
        script_id = result.inserted_primary_key[0]
        row = (
            await session.execute(
                tables.r_script.select().where(tables.r_script.c.id == script_id)
            )
        ).first()
        data = dict(row._mapping)
        await sync.capture_insert(session, entity="r_script", pk_name="id",
                                  pk_value=script_id, row=data)
        await session.commit()

    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["conflicts"] == []
        scripts = (await session.execute(tables.r_script.select())).all()
        assert len(scripts) == 1
        assert scripts[0].name == "plot.R"

    # A later change from anna must NOT be blocked by the r_script replay
    # (the watermark advances past it).
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="after-script", owner="anna")
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["conflicts"] == []
        codes = (await session.execute(tables.code_name.select())).all()
        assert any(c.name == "after-script" for c in codes)


async def test_conflict_does_not_block_later_entries(rater_b, tmp_path):
    """A single conflicted entry must not freeze the rest of the sidecar:
    later entries apply, the watermark advances past them, and the conflict
    is recorded for retry on a later cycle."""
    from sqlalchemy import insert as sa_insert

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        # berta already owns an r_script named "shared.R" (id=1) — anna's
        # insert of the same name collides on the UNIQUE constraint and
        # cannot be natural-key-merged, so it must be a real conflict.
        await session.execute(
            sa_insert(tables.r_script).values(
                name="shared.R", script="berta version", owner="berta",
                created="t", updated="t",
            )
        )
        await session.commit()

    # Craft anna's sidecar: seq1 conflicts, seq2 must still apply.
    sidecar = Path(rater_b.project_path) / sync.SYNC_DIR_NAME / "anna" / "changes.jsonl"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({
            "id": 1, "ts": "t", "user": "anna", "seq": 1, "entity": "r_script",
            "action": "insert", "pk_name": "id", "pk_value": 1,
            "row": {"id": 1, "name": "shared.R", "script": "anna version",
                    "owner": "anna", "created": "t", "updated": "t"},
        }),
        json.dumps({
            "id": 2, "ts": "t", "user": "anna", "seq": 2, "entity": "code_name",
            "action": "insert", "pk_name": "cid", "pk_value": 1,
            "row": {"cid": 1, "name": "clean", "owner": "anna", "date": "t", "color": "1"},
        }),
    ]
    sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["applied"] == 1
        assert len(report["anna"]["conflicts"]) == 1
        conflict = report["anna"]["conflicts"][0]
        assert conflict["entity"] == "r_script"
        assert conflict["action"] == "insert"
        # The later, clean entry applied despite the conflict.
        codes = (await session.execute(tables.code_name.select())).all()
        assert any(c.name == "clean" for c in codes)
        # The conflicting r_script was NOT applied (berta's stays).
        scripts = (await session.execute(tables.r_script.select())).all()
        assert len(scripts) == 1
        assert scripts[0].script == "berta version"

    # The watermark advanced past seq2, so a second import does NOT re-apply
    # the clean entry — and the recorded conflict is still pending.
    state = sync.load_state(rater_b.project_path)
    assert sync._imported_seq(state, "anna") >= 2
    assert "1" in sync._recorded_conflicts(state, "anna")
    summary = sync._conflict_summary(state, "anna")
    assert summary and summary[0]["entity"] == "r_script" and summary[0]["reason"]


async def test_non_pk_unique_constraint_conflict(rater_b, tmp_path):
    """A same-name source with a different PK and different content is matched
    by natural key and surfaced as a concurrent-edit conflict.  It must:
    - record a conflict in the sync_conflict TABLE (not just JSON state)
    - carry the LOCAL row snapshot (so the resolver shows "mine" correctly)
    - NOT poison the session for later entries
    - advance the watermark past the conflict
    - survive a second import cycle (no re-replay)
    """
    from sqlalchemy import insert as sa_insert
    from sqlalchemy import text as sa_text

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        # berta has a source named "Kodiertutorial.txt" (id=29)
        await session.execute(
            sa_insert(tables.source).values(
                id=29, name="Kodiertutorial.txt", fulltext="berta's text",
                owner="berta", date="t",
            )
        )
        await session.commit()

    # Craft anna's sidecar: seq1 has a DIFFERENT PK (id=99) but the SAME
    # name and different content → natural-key match → concurrent edit.  seq2
    # is clean.
    sidecar = Path(rater_b.project_path) / sync.SYNC_DIR_NAME / "anna" / "changes.jsonl"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({
            "id": 1, "ts": "t", "user": "anna", "seq": 1, "entity": "source",
            "action": "insert", "pk_name": "id", "pk_value": 99,
            "row": {"id": 99, "name": "Kodiertutorial.txt", "fulltext": "anna's text",
                    "mediapath": None, "memo": None, "owner": "anna", "date": "t",
                    "av_text_id": None, "risid": None},
        }),
        json.dumps({
            "id": 2, "ts": "t", "user": "anna", "seq": 2, "entity": "code_name",
            "action": "insert", "pk_name": "cid", "pk_value": 1,
            "row": {"cid": 1, "name": "clean", "owner": "anna", "date": "t", "color": "1"},
        }),
    ]
    sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert "anna" in report
        # seq2 applied despite seq1's conflict.
        assert report["anna"]["applied"] == 1
        assert len(report["anna"]["conflicts"]) == 1
        conflict = report["anna"]["conflicts"][0]
        assert conflict["entity"] == "source"
        assert conflict["reason"] == "concurrent edit"

        # The conflict was persisted to the sync_conflict TABLE with the LOCAL
        # row snapshot (so the resolver shows "mine", not an empty row).
        rows = await session.execute(
            sa_text("SELECT entity, pk, local_row FROM sync_conflict WHERE resolved_at IS NULL")
        )
        conflicts_in_db = rows.all()
        assert any(r.entity == "source" for r in conflicts_in_db)
        source_conflict = next(r for r in conflicts_in_db if r.entity == "source")
        assert source_conflict.local_row is not None
        assert json.loads(source_conflict.local_row)["name"] == "Kodiertutorial.txt"

        # berta's source is untouched.
        sources = (await session.execute(tables.source.select())).all()
        assert len(sources) == 1
        assert sources[0].name == "Kodiertutorial.txt"
        assert sources[0].fulltext == "berta's text"

        # The clean code applied.
        codes = (await session.execute(tables.code_name.select())).all()
        assert any(c.name == "clean" for c in codes)

    # Watermark advanced past both entries.
    state = sync.load_state(rater_b.project_path)
    assert sync._imported_seq(state, "anna") >= 2

    # Second import: no re-replay (0 applied, 0 conflicts).
    async with rater_b.session_factory() as session:
        report2 = await sync.import_pending(session, rater_b.project_path, "berta")
    assert "anna" not in report2 or report2["anna"]["applied"] == 0


async def test_export_appends_and_survives_truncated_tail(rater_a):
    """Append-only export never rewrites prior lines; a partial trailing line
    (crash mid-append) is dropped on parse and later exports are intact."""
    sync.set_current_user("anna")
    sidecar = Path(rater_a.project_path) / sync.SYNC_DIR_NAME / "anna" / "changes.jsonl"

    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="first", owner="anna")
    await _export(rater_a, "anna")
    first_len = sidecar.read_text(encoding="utf-8").count("\n")

    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="second", owner="anna")
    await _export(rater_a, "anna")
    # Append: the first export's lines are untouched.
    assert sidecar.read_text(encoding="utf-8").count("\n") == first_len + 1

    # Simulate a torn tail (crash mid-append), then export again.
    with open(sidecar, "a", encoding="utf-8") as f:  # noqa: ASYNC230 - test fixture
        f.write('{"partial')
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="third", owner="anna")
    await _export(rater_a, "anna")

    entries = sync._parse_sidecar(sidecar)
    names = [e["row"].get("name") for e in entries if e["entity"] == "code_name"]
    assert "first" in names and "second" in names and "third" in names


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


async def test_delete_then_reinsert_same_pk_no_ghost(rater_a, rater_b):
    """Deleting the max-id row and re-adding reuses its PK (plain INTEGER
    PRIMARY KEY); the peer must apply the delete AND the insert. Collapsing
    the pair to the insert alone resurrects the deleted file as a ghost and
    the file/coding counts diverge permanently (the watermark advances past
    the dropped delete, so it never heals)."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        source = await SourceRepository(session).add_source(
            name="old.txt", fulltext="old text here", mediapath="/docs/old.txt", owner="anna"
        )
        assert source.id == 1
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await sync.import_pending(session, rater_b.project_path, "berta")

    # Anna deletes old.txt, then imports new.txt — SQLite reuses id=1.
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await SourceRepository(session).delete_source(source.id)
        new_source = await SourceRepository(session).add_source(
            name="new.txt", fulltext="new text here", mediapath="/docs/new.txt", owner="anna"
        )
        assert new_source.id == source.id
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["applied"] >= 2
        names = (
            await session.execute(tables.source.select().with_only_columns(tables.source.c.name))
        ).scalars().all()
    assert list(names) == ["new.txt"]


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


async def test_natural_key_match_across_diverged_pks(rater_b):
    """A source with the SAME name but a DIFFERENT autoincrement PK converges
    by natural key — no duplicate row, no conflict."""
    from sqlalchemy import insert as sa_insert

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        # berta has "Kodiertutorial.txt" at id=29.
        await session.execute(
            sa_insert(tables.source).values(
                id=29, name="Kodiertutorial.txt", fulltext="same text",
                owner="default", date="t",
            )
        )
        await session.commit()

    # anna's sidecar has the same source at id=99 (diverged PK) with identical
    # content — it must converge, not duplicate.
    sidecar = Path(rater_b.project_path) / sync.SYNC_DIR_NAME / "anna" / "changes.jsonl"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({
            "id": 1, "ts": "t", "user": "anna", "seq": 1, "entity": "source",
            "action": "insert", "pk_name": "id", "pk_value": 99,
            "row": {"id": 99, "name": "Kodiertutorial.txt", "fulltext": "same text",
                    "mediapath": None, "memo": None, "owner": "default", "date": "t",
                    "av_text_id": None, "risid": None},
        }) + "\n",
        encoding="utf-8",
    )

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["conflicts"] == []
        sources = (await session.execute(tables.source.select())).all()
        assert len(sources) == 1
        assert sources[0].id == 29
        assert sources[0].name == "Kodiertutorial.txt"


async def test_legacy_rev0_delete_does_not_destroy_local_row(rater_b):
    """A rev-0 (unversioned/legacy) delete for a row that still exists locally
    is ambiguous and must be skipped — never destroy local data on it."""
    from sqlalchemy import insert as sa_insert

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await session.execute(
            sa_insert(tables.source).values(
                id=29, name="Kodiertutorial.txt", fulltext="text",
                owner="berta", date="t",
            )
        )
        await session.commit()

    sidecar = Path(rater_b.project_path) / sync.SYNC_DIR_NAME / "anna" / "changes.jsonl"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({
            "id": 1, "ts": "t", "user": "anna", "seq": 1, "entity": "source",
            "action": "delete", "pk_name": "id", "pk_value": 29,
            "row": {"id": 29, "name": "Kodiertutorial.txt", "fulltext": "text",
                    "mediapath": None, "memo": None, "owner": "berta", "date": "t",
                    "av_text_id": None, "risid": None},
        }) + "\n",
        encoding="utf-8",
    )

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        report = await sync.import_pending(session, rater_b.project_path, "berta")
        assert report["anna"]["conflicts"] == []
        sources = (await session.execute(tables.source.select())).all()
        assert len(sources) == 1
        assert sources[0].name == "Kodiertutorial.txt"


async def test_sync_presence_endpoint(project_client):
    """GET /sync/presence reports live other-instance presence (empty here —
    no other instances on this single client)."""
    client, _ = project_client
    res = await client.get("/api/v1/sync/presence")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["presence"] == []


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
    as shared — but ONLY when that other instance is live (fresh heartbeat
    or explicit collab marker). A bare pile of stale sidecars is an offline
    backup: auto-enabling collaboration on it would replay a huge stale
    backlog on open and freeze/empty the app."""
    import json
    import os
    import time

    changes = Path(rater_a.project_path) / sync.SYNC_DIR_NAME
    (changes / "berta").mkdir(parents=True)
    (changes / "berta" / "changes.jsonl").write_text("", encoding="utf-8")

    # No marker, no presence → offline backup, NOT shared.
    result = sync.detect_shared(rater_a.project_path, user="anna")
    assert result == {
        "shared": False,
        "reason": "offline backup (stale change sidecars, no live collaborator)",
    }

    # Explicit collaboration marker → shared.
    (Path(rater_a.project_path) / ".qcnext-project").write_text("{}", encoding="utf-8")
    assert sync.detect_shared(rater_a.project_path, user="anna") == {
        "shared": True,
        "reason": "change sidecars from other instances",
    }
    (Path(rater_a.project_path) / ".qcnext-project").unlink()

    # Fresh live peer heartbeat → shared.
    presence = Path(rater_a.project_path) / "presence"
    presence.mkdir(parents=True)
    peer_pid = os.getpid() + 424242  # not this process, but "remote" entries
    (presence / f"{peer_pid}.json").write_text(
        json.dumps({"coder": "berta", "pid": 99999901, "host": "other-host",
                    "ts": time.time(), "file_id": None, "file_name": ""}),
        encoding="utf-8",
    )
    result = sync.detect_shared(rater_a.project_path, user="anna")
    assert result == {"shared": True, "reason": "change sidecars from other instances"}

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


@pytest.mark.parametrize("folder", ["OneDrive", "Dropbox", "Google Drive", "iCloud", "Nextcloud"])
def test_detect_shared_cloud_sync_folder(tmp_path, folder):
    project = tmp_path / folder / "P.qda"
    project.mkdir(parents=True)
    res = sync.detect_shared(str(project))
    assert res["shared"] is True
    assert "cloud-sync folder" in res["reason"]


def test_detect_shared_st_folder_marker(tmp_path):
    syncroot = tmp_path / "mysync"
    syncroot.mkdir()
    (syncroot / ".stfolder").write_text("", encoding="utf-8")
    project = syncroot / "sub" / "deeper" / "P.qda"
    project.mkdir(parents=True)
    assert sync.detect_shared(str(project)) == {
        "shared": True,
        "reason": "Syncthing folder marker",
    }


def test_detect_shared_st_marker_ignores_unrelated(tmp_path):
    project = tmp_path / "plain" / "P.qda"
    project.mkdir(parents=True)
    assert sync.detect_shared(str(project))["shared"] is False


async def test_auto_enable_decision_honors_override(rater_a, tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    (Path(rater_a.project_path) / ".qcnext-shared").write_text("", encoding="utf-8")
    # "auto" (default) follows the detection.
    res = sync.auto_enable_decision(rater_a.project_path)
    assert res["sync_auto_enabled"] is False  # never auto-enable
    assert "shared-folder marker" in res["reason"]
    # "off" wins over a detected shared folder.
    user_settings.set_sync_override(rater_a.project_path, "off")
    assert sync.auto_enable_decision(rater_a.project_path) == {
        "sync_auto_enabled": False,
        "reason": "per-project override",
    }
    # "on" override: still never AUTO-enabled (manual toggle only).
    (Path(rater_a.project_path) / ".qcnext-shared").unlink()
    user_settings.set_sync_override(rater_a.project_path, "on")
    assert sync.auto_enable_decision(rater_a.project_path) == {
        "sync_auto_enabled": False,
        "reason": "per-project override",
    }


async def test_auto_enable_decision_marker_reports_manual_requirement(rater_a):
    from qualcoder_api.services import project_marker

    project_marker.write_marker(rater_a.project_path, uuid="testuuid")
    try:
        res = sync.auto_enable_decision(rater_a.project_path)
        assert res["sync_auto_enabled"] is False
        assert "manually" in res["reason"] or "manual" in res["reason"]
    finally:
        (Path(rater_a.project_path) / ".qcnext-project").unlink(missing_ok=True)


# ── first-sync baseline for new collaborators ───────────────────────────


def _sidecar_entry(seq: int, entity: str = "code_name", pk: int = 1) -> dict:
    return {
        "seq": seq,
        "instance": "berta",
        "coder": "berta",
        "entity": entity,
        "action": "insert",
        "pk_name": "cid" if entity == "code_name" else "id",
        "pk_value": pk,
        "rev": seq,
        "mtime": "2026-01-01T00:00:00.000",
        "row": {"name": f"N{seq}", "owner": "berta", "date": "2026-01-01",
                "memo": "", "color": None, "catid": None, "supercid": None,
                "memo_type": "", "position": seq},
    }


async def test_baseline_first_sync_skips_backlog_for_new_collaborator(
    rater_a, tmp_path
):
    """A fresh instance enabling sync on an established shared project must
    NOT replay the entire existing sidecar backlog: baseline adopts current
    state as already-seen; only entries appended AFTER the baseline flow."""
    from qualcoder_api.persistence.repo.code_repo import CodeRepository
    from qualcoder_api.services import sync_engine
    from qualcoder_api.services.sync_state import (
        _imported_seq,
        load_state,
    )

    changes = Path(rater_a.project_path) / sync.SYNC_DIR_NAME
    berta = changes / "berta"
    berta.mkdir(parents=True)

    async with rater_a.session_factory() as session:
        repo = CodeRepository(session)
        await repo.add_code(name="Old1", owner="berta")
        await repo.add_code(name="Old2", owner="berta")

        # Simulate berta's sidecar history: two exported entries.
        lines = "\n".join(
            json.dumps(
                {
                    "seq": n,
                    "instance": "berta",
                    "coder": "berta",
                    "entity": "code_name",
                    "action": "insert",
                    "pk_name": "cid",
                    "pk_value": n,
                    "rev": n,
                    "mtime": "2026-01-0%dT00:00:00.000" % n,
                    "row": {"name": f"Backlog{n}", "catid": None, "supercid": None,
                            "memo": "", "color": None, "owner": "berta",
                            "date": "2026-01-01", "memo_type": "", "position": n},
                },
                ensure_ascii=False,
            )
            for n in (1, 2)
        ) + "\n"
        sidecar = berta / "changes.jsonl"
        sidecar.write_text(lines, encoding="utf-8")

        instance_id = "newcomer"
        assert await sync_engine.baseline_first_sync(
            session, rater_a.project_path, instance_id
        ) is True

        state = load_state(rater_a.project_path)
        assert _imported_seq(state, "berta") == 2
        assert state["exports"][instance_id] >= 0

        # A later entry DOES flow past the baseline.
        (sidecar).write_text(lines + json.dumps(_sidecar_entry(3)) + "\n", encoding="utf-8")
        report = await __import__("qualcoder_api.services.sync_replay", fromlist=["import_pending"]).import_pending(
            session, rater_a.project_path, instance_id
        )
        assert report.get("berta", {}).get("applied", 0) == 1

        # Re-baseline is refused once state exists.
        assert await sync_engine.baseline_first_sync(
            session, rater_a.project_path, instance_id
        ) is False


async def test_baseline_manual_enable_offline_backup_no_replay(rater_a):
    """Manual enable on an offline backup: backlog skipped, live data intact."""
    from qualcoder_api.persistence.repo.code_repo import CodeRepository
    from qualcoder_api.services import sync_engine

    async with rater_a.session_factory() as session:
        repo = CodeRepository(session)
        await repo.add_code(name="Keep1", owner="anna")
        await repo.add_code(name="Keep2", owner="anna")

    changes = Path(rater_a.project_path) / sync.SYNC_DIR_NAME
    stale = changes / "oldmachine"
    stale.mkdir(parents=True)
    stale_lines = "\n".join(json.dumps(e) for e in [
        _sidecar_entry(1), _sidecar_entry(2),
    ]) + "\n"
    (stale / "changes.jsonl").write_text(stale_lines, encoding="utf-8")

    async with rater_a.session_factory() as session:
        assert await sync_engine.baseline_first_sync(
            session, rater_a.project_path, "anna-instance"
        ) is True
        report = await __import__(
            "qualcoder_api.services.sync_replay", fromlist=["import_pending"]
        ).import_pending(session, rater_a.project_path, "anna-instance")
        assert report.get("oldmachine", {}).get("applied", 0) == 0

        repo = CodeRepository(session)
        codes = await repo.list_codes()
        names = {c.name for c in codes}
        assert {"Keep1", "Keep2"} <= names


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
    """The open result carries the shared-folder decision — but collaboration
    is NEVER auto-enabled: shared detection surfaces as an informational
    reason only ('manual enable required (...)')."""
    client, target = project_client
    await client.post("/api/v1/projects/close")
    res = await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    body = res.json()
    assert body["ok"] is True
    assert body["sync_auto_enabled"] is False
    assert body["sync_auto_reason"] == "manual enable required (not a shared folder)"
    await client.post("/api/v1/projects/close")
    (target / ".qcnext-shared").write_text("", encoding="utf-8")
    res = await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    assert res.json()["sync_auto_enabled"] is False  # never auto-enable
    assert "manual enable required" in res.json()["sync_auto_reason"]
    await client.post("/api/v1/projects/close")
    await client.put(
        "/api/v1/sync/override", json={"project_path": str(target), "mode": "off"}
    )
    res = await client.post("/api/v1/projects/open", json={"project_path": str(target)})
    assert res.json()["sync_auto_enabled"] is False


# ----------------------------------------------------------------------
# Sync-health / robustness fixes
# ----------------------------------------------------------------------

def test_reset_health_for_project_clears_globals():
    """Switching projects zeroes the process-wide health globals (used at the
    start of run_sync_cycle / sync_status) so the indicator never shows the
    previous project's state."""
    sync._health_project = "proj-a"
    sync._last_sync_ts = 55.0
    sync._last_error = "boom"
    sync._last_error_ts = 7.0
    sync._last_result = {"ok": False}
    sync._reset_health_for_project("proj-b")
    assert sync._last_sync_ts == 0.0
    assert sync._last_error == ""
    assert sync._last_error_ts == 0.0
    assert sync._last_result is None
    assert sync._health_project == "proj-b"
    # Same project: no reset, values set afterwards are preserved.
    sync._last_error = "boom"
    sync._reset_health_for_project("proj-b")
    assert sync._last_error == "boom"


async def test_health_resets_on_project_change(rater_a, rater_b):
    """sync_status and run_sync_cycle start with a clean health state when
    the active project differs from the last one."""
    sync._health_project = ""
    sync._note_error(RuntimeError("boom"))
    sync._last_sync_ts = 55.0
    sync._last_result = {"ok": False}

    status = await sync.sync_status(rater_a.session_factory, rater_a.project_path, "anna")
    assert status["ok"] is True
    assert sync._health_project == rater_a.project_path
    assert sync._last_sync_ts == 0.0
    assert sync._last_error == ""
    assert sync._last_error_ts == 0.0
    assert sync._last_result is None

    # Same project: error set afterwards is preserved.
    sync._note_error(RuntimeError("boom"))
    await sync.sync_status(rater_a.session_factory, rater_a.project_path, "anna")
    assert sync._last_error == "boom"

    # A different project resets again (run_sync_cycle path).
    result = await sync.run_sync_cycle(rater_b.session_factory, rater_b.project_path, "berta")
    assert result["ok"] is True
    assert sync._health_project == rater_b.project_path


async def test_export_defers_when_sidecar_locked(rater_a, monkeypatch):
    """A PermissionError on the sidecar append defers export instead of
    failing: no watermark advance, and the rows are retried next cycle."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="first", owner="anna")

    def _locked(sidecar, lines):
        raise PermissionError(13, "Permission denied")

    with monkeypatch.context() as m:
        m.setattr(sync_engine, "_append_sidecar", _locked)
        async with rater_a.session_factory() as session:
            result = await sync.export_pending(session, rater_a.project_path, "anna")
        assert result == {"exported": 0, "deferred": 1}
        state = sync.load_state(rater_a.project_path)
        assert sync._exported_id(state, "anna") == 0

    # Unlocked retry exports the deferred rows and advances the watermark.
    async with rater_a.session_factory() as session:
        result = await sync.export_pending(session, rater_a.project_path, "anna")
    assert result == {"exported": 1}
    state = sync.load_state(rater_a.project_path)
    assert sync._exported_id(state, "anna") >= 1


async def test_cycle_defers_locked_sidecar_without_error(rater_a, monkeypatch):
    """run_sync_cycle treats a deferred (locked) append as a success — no
    scary error surfaces in the health globals."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="first", owner="anna")

    def _locked(sidecar, lines):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(sync_engine, "_append_sidecar", _locked)
    result = await sync.run_sync_cycle(rater_a.session_factory, rater_a.project_path, "anna")
    assert result["ok"] is True
    assert result["exported"] == 0
    assert result["deferred"] == 1
    assert sync._last_error == ""
    assert sync._last_error_ts == 0.0


async def test_db_locked_replay_is_retried_not_conflict(rater_b, monkeypatch):
    """A transient 'database is locked' OperationalError is retried by
    _replay_one and NOT recorded as a conflict nor advanced past the
    watermark by import_pending."""
    from sqlalchemy.exc import OperationalError

    sidecar = Path(rater_b.project_path) / sync.SYNC_DIR_NAME / "anna" / "changes.jsonl"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": 1, "ts": "t", "user": "anna", "seq": 1, "entity": "code_name",
        "action": "insert", "pk_name": "cid", "pk_value": 1,
        "row": {"cid": 1, "name": "locked", "owner": "anna", "date": "t", "color": "1"},
    }
    sidecar.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    async def _locked_insert(session, entity, row):
        raise OperationalError("INSERT code_name", {}, Exception("database is locked"))

    monkeypatch.setattr(sync_engine, "_insert_row", _locked_insert)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        outcome = await sync._replay_one(session, entry, {})
        assert outcome == {"status": "retry", "entity": "code_name",
                           "pk": "1", "action": "insert"}
        report = await sync.import_pending(session, rater_b.project_path, "berta")

    assert report["anna"]["applied"] == 0
    assert report["anna"]["conflicts"] == []
    state = sync.load_state(rater_b.project_path)
    assert sync._imported_seq(state, "anna") == 0
    assert sync._recorded_conflicts(state, "anna") == {}
    # The insert was never applied.
    async with rater_b.session_factory() as session:
        codes = (await session.execute(tables.code_name.select())).all()
        assert len(codes) == 0


async def test_session_id_exports_to_replay_not_legacy(rater_a):
    """A session id (dash) routes exports to ``replays/<id>.jsonl`` only —
    never to the legacy ``changes/<instance>`` path. One identity → one
    replay file, so watermarks and imports stay consistent."""
    sid = "inst1-123456-abcd"
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="fear", owner="anna")
    async with rater_a.session_factory() as session:
        report = await sync.export_pending(session, rater_a.project_path, sid)
    assert report["exported"] == 1
    replay = Path(rater_a.project_path) / "replays" / f"{sid}.jsonl"
    assert replay.exists()
    assert not (Path(rater_a.project_path) / sync.SYNC_DIR_NAME / sid / "changes.jsonl").exists()


async def test_coder_names_roundtrip(rater_a, rater_b):
    """A coder registered on one machine (the API path, which captures into
    sync_log) reaches the other machine through the sidecars, so both
    instances show the same coder roster — fixing the "different instances
    show different coders" symptom."""
    from sqlalchemy import text

    from qualcoder_api.api.v1.coders import _ensure_project_coder

    sync.set_current_user("anna")
    await _ensure_project_coder(rater_a, "carol")
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await sync.import_pending(session, rater_b.project_path, "berta")
        rows = await session.execute(text("SELECT name FROM coder_names"))
    names = {r[0] for r in rows}
    assert "carol" in names
    # Visibility changes travel too.
    from qualcoder_api.api.v1.coders import _capture_coder

    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await session.execute(
            text("UPDATE coder_names SET visibility = 0 WHERE name = 'carol'")
        )
        await _capture_coder(session, "update", "carol", {"name": "carol", "visibility": 0})
        await session.commit()
    await _export(rater_a, "anna")
    _copy_changes(rater_a.project_path, rater_b.project_path)
    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await sync.import_pending(session, rater_b.project_path, "berta")
        row = (
            await session.execute(
                text("SELECT visibility FROM coder_names WHERE name = 'carol'")
            )
        ).first()
    assert row is not None and row[0] == 0


# ----------------------------------------------------------------------
# Cleanup: sync_log trimming + sidecar compaction
# ----------------------------------------------------------------------

async def test_export_trims_exported_sync_log_rows(rater_a):
    """After export, already-exported sync_log rows are dropped (keeping the
    latest row per user so the seq counter never resets)."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="one", owner="anna")
        await CodeRepository(session).add_code(name="two", owner="anna")
        await CodeRepository(session).add_code(name="three", owner="anna")
    await _export(rater_a, "anna")
    async with rater_a.session_factory() as session:
        rows = (await session.execute(tables.sync_log.select())).all()
        # Only the latest row per user survives.
        assert len(rows) == 1
        assert json.loads(rows[0].row_json)["name"] == "three"


async def test_export_keeps_unexported_rows(rater_a):
    """Rows above the export watermark are never trimmed."""
    sync.set_current_user("anna")
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="one", owner="anna")
    await _export(rater_a, "anna")
    async with rater_a.session_factory() as session:
        await CodeRepository(session).add_code(name="two", owner="anna")
    # No export yet — both rows remain (one exported, one pending).
    async with rater_a.session_factory() as session:
        rows = (await session.execute(tables.sync_log.select())).all()
        assert len(rows) == 2


async def test_sidecar_compaction_keeps_latest_per_row(tmp_path):
    """Compaction rewrites a sidecar to one entry per (entity, pk)."""
    sidecar = tmp_path / "changes.jsonl"
    lines = [
        {"seq": 1, "entity": "code_name", "pk_value": "1", "rev": 1,
         "row": {"name": "old"}},
        {"seq": 2, "entity": "code_name", "pk_value": "1", "rev": 2,
         "row": {"name": "new"}},
        {"seq": 3, "entity": "code_name", "pk_value": "2", "rev": 1,
         "row": {"name": "other"}},
    ]
    sidecar.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")
    # Force compaction by lowering the threshold.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_engine, "SIDECAR_COMPACT_THRESHOLD_ENTRIES", 1)
    kept = sync_engine._compact_sidecar(sidecar)
    assert kept == 2
    entries = sync_engine._parse_sidecar(sidecar)
    by_pk = {str(e["pk_value"]): e for e in entries}
    assert by_pk["1"]["row"]["name"] == "new"
    assert by_pk["2"]["row"]["name"] == "other"
    monkeypatch.undo()


async def test_sidecar_compaction_keeps_delete_before_reinsert(tmp_path):
    """A delete→insert cycle for one PK is a reused key (different logical
    rows): compaction must keep both, or peers resurrect the deleted row."""
    sidecar = tmp_path / "changes.jsonl"
    lines = [
        {"seq": 1, "entity": "source", "action": "insert", "pk_value": "1", "rev": 1,
         "row": {"name": "old.txt"}},
        {"seq": 2, "entity": "source", "action": "delete", "pk_value": "1", "rev": 2,
         "row": {"name": "old.txt"}},
        {"seq": 3, "entity": "source", "action": "insert", "pk_value": "1", "rev": 3,
         "row": {"name": "new.txt"}},
    ]
    sidecar.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_engine, "SIDECAR_COMPACT_THRESHOLD_ENTRIES", 1)
    kept = sync_engine._compact_sidecar(sidecar)
    assert kept == 2
    entries = sync_engine._parse_sidecar(sidecar)
    assert [(e["seq"], e["action"]) for e in entries] == [(2, "delete"), (3, "insert")]
    monkeypatch.undo()


# ----------------------------------------------------------------------
# Conflict resolution
# ----------------------------------------------------------------------

async def test_resolve_conflict_keep_mine(rater_b):
    """Resolving with "local" keeps the local row and bumps its rev."""
    from sqlalchemy import text as sa_text

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await CodeRepository(session).add_code(name="shared", owner="berta")
        # Simulate a conflict: local row exists, remote has a different name.
        await session.execute(
            sa_text(
                "INSERT INTO sync_conflict (entity, pk, pk_name, local_rev, remote_rev, "
                "local_row, remote_row, remote_instance, remote_coder, detected_at) "
                "VALUES ('code_name', '1', 'cid', 1, 1, :local, :remote, 'x', 'anna', 't')"
            ),
            {
                "local": json.dumps({"cid": 1, "name": "shared", "owner": "berta"}),
                "remote": json.dumps({"cid": 1, "name": "renamed", "owner": "anna"}),
            },
        )
        await session.commit()

    result = await sync.resolve_conflict(
        rater_b.session_factory, rater_b.project_path, 1, "local", None
    )
    assert result["ok"] is True
    async with rater_b.session_factory() as session:
        code = (await session.execute(tables.code_name.select())).first()
        assert code.name == "shared"
        rev = (await session.execute(
            sa_text("SELECT rev FROM sync_rev WHERE entity='code_name' AND pk='1'")
        )).scalar()
        assert rev == 2


async def test_resolve_conflict_take_theirs(rater_b):
    """Resolving with "remote" applies the remote row."""
    from sqlalchemy import text as sa_text

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await CodeRepository(session).add_code(name="shared", owner="berta")
        await session.execute(
            sa_text(
                "INSERT INTO sync_conflict (entity, pk, pk_name, local_rev, remote_rev, "
                "local_row, remote_row, remote_instance, remote_coder, detected_at) "
                "VALUES ('code_name', '1', 'cid', 1, 1, :local, :remote, 'x', 'anna', 't')"
            ),
            {
                "local": json.dumps({"cid": 1, "name": "shared", "owner": "berta"}),
                "remote": json.dumps({"cid": 1, "name": "renamed", "owner": "anna"}),
            },
        )
        await session.commit()

    result = await sync.resolve_conflict(
        rater_b.session_factory, rater_b.project_path, 1, "remote", None
    )
    assert result["ok"] is True
    async with rater_b.session_factory() as session:
        code = (await session.execute(tables.code_name.select())).first()
        assert code.name == "renamed"


async def test_resolve_all_conflicts(rater_b):
    """Bulk resolution clears every pending conflict with one strategy."""
    from sqlalchemy import text as sa_text

    sync.set_current_user("berta")
    async with rater_b.session_factory() as session:
        await CodeRepository(session).add_code(name="a", owner="berta")
        await CodeRepository(session).add_code(name="b", owner="berta")
        for pk, name in (("1", "a"), ("2", "b")):
            await session.execute(
                sa_text(
                    "INSERT INTO sync_conflict (entity, pk, pk_name, local_rev, remote_rev, "
                    "local_row, remote_row, remote_instance, remote_coder, detected_at) "
                    "VALUES ('code_name', :pk, 'cid', 1, 1, :local, :remote, 'x', 'anna', 't')"
                ),
                {
                    "pk": pk,
                    "local": json.dumps({"cid": int(pk), "name": name, "owner": "berta"}),
                    "remote": json.dumps({"cid": int(pk), "name": name + "-x", "owner": "anna"}),
                },
            )
        await session.commit()

    result = await sync.resolve_all_conflicts(
        rater_b.session_factory, rater_b.project_path, "local"
    )
    assert result["ok"] is True
    assert result["resolved"] == 2
    async with rater_b.session_factory() as session:
        pending = (await session.execute(
            sa_text("SELECT COUNT(*) FROM sync_conflict WHERE resolved_at IS NULL")
        )).scalar()
        assert pending == 0


async def test_resolve_all_conflicts_endpoint(project_client):
    """POST /sync/conflicts/resolve-all resolves pending conflicts."""
    client, _ = project_client
    res = await client.post("/api/v1/sync/conflicts/resolve-all", json={"resolution": "local"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    res = await client.post("/api/v1/sync/conflicts/resolve-all", json={"resolution": "merged"})
    assert res.status_code == 422
