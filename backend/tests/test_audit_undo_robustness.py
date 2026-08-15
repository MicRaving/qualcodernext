"""Robustness tests — undo/redo must never 500, even for audit rows that
were recorded BEFORE the ``before``/``row`` detail fields existed.

Legacy rows (from old projects) carry at most the entity_id columns but no
recorded row snapshots. Every data-dependent undo/redo path must surface the
stable, user-friendly ``MISSING_DATA_MESSAGE`` as a 422 detail instead of a
raw KeyError / 500 or a technical "missing detail field" message.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import user_settings
from qualcoder_api.services.audit_undo import MISSING_DATA_MESSAGE


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def open_project(client, tmp_path):
    target = tmp_path / "undo_robust.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text
    yield target
    await client.post("/api/v1/projects/close")


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Keep the developer's real ~/.qualcoder/settings.json out of the run."""
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    return user_settings.SETTINGS_FILE


def _insert_legacy_audit(
    target, action: str, entity: str, entity_id=None, source_id=None, detail: dict | None = None
) -> None:
    """Insert an audit row the way old projects recorded them: the core
    columns are filled but the detail carries no before/row snapshots."""
    with sqlite3.connect(str(target / "data.qda")) as conn:
        conn.execute(
            "INSERT INTO audit_log (ts, user, action, entity, entity_id, source_id, detail) "
            "VALUES (datetime('now'), 'default', ?, ?, ?, ?, ?)",
            (action, entity, entity_id, source_id, json.dumps(detail or {})),
        )
        conn.commit()


async def _find_audit_id(client, action: str, index: int = 0) -> int:
    res = await client.get("/api/v1/audit", params={"action": action})
    rows = res.json()["rows"]
    assert rows, f"no audit rows for {action}"
    return rows[index]["id"]


async def _call(client, path: str, aid: int) -> dict:
    res = await client.post(path, json={"id": aid})
    return {"status": res.status_code, "body": res.json()}


# ----------------------------------------------------------------------
# 1. Legacy rows (no before/row detail) for every handler family.
#
# Expected statuses: 422 when the direction needs the missing snapshot
# (asserting the exact MISSING_DATA_MESSAGE), 200 when the direction is a
# pure delete/no-op that needs no recorded data.
# ----------------------------------------------------------------------

# (action, entity, entity_id, source_id, expect_undo, expect_redo)
LEGACY_MATRIX = [
    # code tree / coding
    ("code.rename", "code", 11, None, 422, 422),
    ("code.create", "code", 11, None, 422, 422),
    ("code.delete", "code", 11, None, 422, 422),
    ("code.move", "code", 11, None, 422, 422),
    ("code.promote", "code", 11, None, 422, 422),
    ("code.demote", "code", 11, None, 422, 422),
    ("code.merge", "code", 11, None, 422, 422),
    ("code.memo", "code", 11, None, 422, 422),
    ("coding.create", "code_text", 11, 1, 422, 422),
    ("coding.delete", "code_text", 11, 1, 422, 422),
    ("coding.update", "code_text", 11, 1, 422, 422),
    ("coding.update", "code_image", 11, 1, 422, 422),
    ("coding.update", "code_av", 11, 1, 422, 422),
    ("coding.update", "no_such_entity", 11, 1, 422, 422),
    ("coding.undo", "code_text", None, None, 422, 422),
    ("coding.autocode", "code_text", None, None, 422, 422),
    ("annotation.create", "annotation", 11, 1, 422, 422),
    ("annotation.delete", "annotation", 11, 1, 422, 422),
    ("annotation.update", "annotation", 11, 1, 422, 422),
    # categories
    ("category.create", "code_cat", 11, None, 200, 422),
    ("category.delete", "code_cat", 11, None, 422, 200),
    ("category.rename", "code_cat", 11, None, 422, 422),
    ("category.move", "code_cat", 11, None, 422, 422),
    ("category.promote", "code_cat", 11, None, 422, 422),
    ("category.demote", "code_cat", 11, None, 422, 422),
    ("category.merge", "code_cat", 11, None, 422, 422),
    # cases / journals
    ("case.create", "case", 11, None, 422, 422),
    ("case.delete", "case", 11, None, 422, 200),
    ("case.update", "case", 11, None, 422, 422),
    ("case.link_file", "case_text", 11, 1, 200, 422),
    ("case.link_span", "case_text", 11, 1, 200, 422),
    ("case.unlink_file", "case_text", None, 1, 200, 200),
    ("journal.create", "journal", 11, None, 422, 422),
    ("journal.delete", "journal", 11, None, 422, 200),
    ("journal.update", "journal", 11, None, 422, 422),
    # sources
    ("source.edit", "source", 11, None, 422, 422),
    ("source.update", "source", 11, None, 422, 422),
    ("source.import", "source", 11, None, 200, 422),
    ("source.link", "source", 11, None, 200, 422),
    ("source.delete", "source", 11, None, 422, 200),
    ("source.link_fix", "source", 11, None, 422, 422),
    ("source.replace", "source", 11, None, 422, 422),
    ("transcript.create", "source", 11, 2, 200, 422),
    ("transcript.delete", "source", 11, 2, 422, 200),
    # attributes / links / comments / creative
    ("attribute.create", "attribute_type", None, None, 422, 422),
    ("attribute.delete", "attribute_type", None, None, 422, 422),
    ("attribute.set_value", "attribute", 11, None, 422, 422),
    ("link.create", "link", 11, None, 200, 422),
    ("link.delete", "link", 11, None, 422, 200),
    ("comment.create", "comment", 11, None, 200, 422),
    ("comment.update", "comment", 11, None, 422, 422),
    ("comment.delete", "comment", 11, None, 422, 200),
    ("creative.create", "creative_item", 11, None, 200, 422),
    ("creative.update", "creative_item", 11, None, 422, 422),
    ("creative.delete", "creative_item", 11, None, 422, 200),
    ("creative.promote", "code", 11, None, 422, 422),
    # tools / settings
    ("bookmark.set", "project", None, None, 422, 422),
    ("speakers.mark", "source", 11, None, 200, 422),
    ("pseudonym.add", "project", None, None, 422, 422),
    ("pseudonym.delete", "project", None, None, 422, 422),
    ("sync.toggle", "project", None, None, 422, 422),
    ("coder.create", "coder", None, None, 422, 422),
    ("coder.delete", "coder", None, None, 422, 422),
    ("coder.rename", "coder", None, None, 422, 422),
    ("coder.visibility", "coder", None, None, 422, 422),
    # references
    ("reference.delete", "ris", 11, None, 422, 200),
    ("reference.attach", "source", 11, None, 200, 422),
    ("reference.detach", "source", 11, None, 422, 422),
    # filters / stored sql / dictionaries / code sets / r scripts
    ("filter.create", "files_filter", 11, None, 200, 422),
    ("filter.delete", "files_filter", 11, None, 422, 200),
    ("sql.save", "stored_sql", 11, None, 200, 422),
    ("sql.delete", "stored_sql", 11, None, 422, 200),
    ("dictionary.create", "dictionary", 11, None, 200, 422),
    ("dictionary.update", "dictionary", 11, None, 422, 422),
    ("dictionary.entry_add", "dictionary_entry", 11, None, 200, 422),
    ("dictionary.entry_delete", "dictionary_entry", 11, None, 422, 200),
    ("dictionary.delete", "dictionary", 11, None, 422, 200),
    ("dictionary.import", "dictionary", 11, None, 200, 422),
    ("code_set.create", "code_set", 11, None, 200, 422),
    ("code_set.rename", "code_set", 11, None, 422, 422),
    ("code_set.delete", "code_set", 11, None, 422, 200),
    ("code_set.members_add", "code_set", 11, None, 200, 200),
    ("code_set.members_remove", "code_set", 11, None, 200, 200),
    ("r_script.create", "r_script", 11, None, 200, 422),
    ("r_script.update", "r_script", 11, None, 422, 422),
    ("r_script.delete", "r_script", 11, None, 422, 200),
    # qtt
    ("qtt.create", "qtt_sheet", 11, None, 200, 422),
    ("qtt.update", "qtt_sheet", 11, None, 422, 422),
    ("qtt.delete", "qtt_sheet", 11, None, 422, 200),
    ("qtt.item.create", "qtt_item", 11, None, 200, 422),
    ("qtt.item.update", "qtt_item", 11, None, 422, 422),
    ("qtt.item.delete", "qtt_item", 11, None, 422, 200),
    ("qtt.send_segment", "qtt_item", 11, None, 200, 422),
    # graphs
    ("graph.create", "graph", 11, None, 200, 422),
    ("graph.update", "graph", 11, None, 422, 422),
    ("graph.delete", "graph", 11, None, 422, 200),
    ("graph.item_add", "gr_cdct_text_item", 11, None, 200, 422),
    ("graph.item_update", "gr_cdct_text_item", 11, None, 422, 422),
    ("graph.item_delete", "gr_cdct_text_item", 11, None, 422, 200),
    ("graph.line_add", "gr_cdct_line_item", 11, None, 200, 422),
    ("graph.line_update", "gr_cdct_line_item", 11, None, 422, 422),
    ("graph.line_delete", "gr_cdct_line_item", 11, None, 422, 200),
    # jobs
    ("transcribe.start", "source", 11, None, 422, 422),
    ("r.run", "r", None, None, 422, 422),
]


@pytest.mark.parametrize(
    ("action", "entity", "entity_id", "source_id", "expect_undo", "expect_redo"),
    LEGACY_MATRIX,
    ids=[f"{a}->{b}/{c}" for a, b, c, _, _, _ in LEGACY_MATRIX],
)
async def test_legacy_rows_never_500(
    client, open_project, settings_file, action, entity, entity_id, source_id,
    expect_undo, expect_redo,
):
    _insert_legacy_audit(
        open_project, action, entity, entity_id=entity_id, source_id=source_id
    )
    aid = await _find_audit_id(client, action)

    undo = await _call(client, "/api/v1/audit/undo", aid)
    assert undo["status"] == expect_undo, (action, undo)
    if expect_undo == 422:
        # The endpoint must surface the stable user-friendly message.
        assert undo["body"]["detail"] == MISSING_DATA_MESSAGE, (action, undo)
    assert undo["status"] != 500, (action, undo)

    redo = await _call(client, "/api/v1/audit/redo", aid)
    assert redo["status"] == expect_redo, (action, redo)
    if expect_redo == 422:
        # Redo either cannot work (missing data → stable message) or is
        # genuinely not invertible (explanatory message) — never a 500.
        assert redo["body"]["detail"], (action, redo)
        assert isinstance(redo["body"]["detail"], str), (action, redo)
    assert redo["status"] != 500, (action, redo)


# ----------------------------------------------------------------------
# 2. Redo-side message check for the not-invertible families.
# ----------------------------------------------------------------------

REDO_IMPOSSIBLE = [
    # (action, entity, entity_id, detail, needle)
    ("source.import", "source", 11, {}, "import the file again"),
    ("source.link", "source", 11, {}, "import the file again"),
    ("source.replace", "source", 11, {}, "upload the replacement file again"),
    ("dictionary.import", "dictionary", 11, {}, "re-import the dictionary file"),
    ("transcribe.start", "source", 11, {"job_id": "nosuchjob"}, "start the job again"),
    ("r.run", "r", None, {"job_id": "nosuchjob"}, "run the script again"),
    ("speakers.mark", "source", 11, {}, "run the speaker detection again"),
    ("coding.autocode", "code_text", None, {}, "run the autocode again"),
    ("graph.create", "graph", 11, {"model": True}, "run the model generator again"),
]


@pytest.mark.parametrize(
    ("action", "entity", "entity_id", "detail", "needle"),
    REDO_IMPOSSIBLE,
    ids=[r[0] for r in REDO_IMPOSSIBLE],
)
async def test_redo_impossible_has_explanatory_message(
    client, open_project, settings_file, action, entity, entity_id, detail, needle,
):
    _insert_legacy_audit(open_project, action, entity, entity_id=entity_id, detail=detail)
    aid = await _find_audit_id(client, action)
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 422, (action, res.text)
    assert needle in res.json()["detail"], (action, res.text)


# ----------------------------------------------------------------------
# 3. Runtime hardening: guards that previously could 500 or corrupt.
# ----------------------------------------------------------------------


async def test_source_update_legacy_row_does_not_null_columns(client, open_project):
    """A legacy source.update row that recorded only the name must restore
    only the name — memo must NOT be overwritten with NULL."""
    fid = None
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("su.txt", "some content", "text/plain")}
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]
    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        conn.execute("UPDATE source SET memo = 'keep me', name = 'renamed.txt' WHERE id = ?", (fid,))
        conn.commit()

    _insert_legacy_audit(
        open_project, "source.update", "source", entity_id=fid,
        detail={"before_name": "su.txt", "after_name": "renamed.txt"},
    )
    aid = await _find_audit_id(client, "source.update")

    undo = await _call(client, "/api/v1/audit/undo", aid)
    assert undo["status"] == 200, undo
    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        name, memo = conn.execute(
            "SELECT name, memo FROM source WHERE id = ?", (fid,)
        ).fetchone()
    assert name == "su.txt"
    assert memo == "keep me"


async def test_source_edit_undo_source_gone_is_422_not_500(client, open_project):
    """source.edit undo must not 500 when the edited source no longer exists."""
    _insert_legacy_audit(
        open_project, "source.edit", "source", entity_id=9999,
        detail={"fid": 9999, "before": "old text", "after": "new text"},
    )
    aid = await _find_audit_id(client, "source.edit")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 422, res.text
    assert "cannot apply the edit undo" in res.json()["detail"], res.text


async def test_annotation_restore_collision_is_422_not_500(client, open_project):
    """annotation.delete undo must surface a unique-constraint collision as a
    422 with an explanatory message, not a 500."""
    res = await client.post(
        "/api/v1/sources/import", files={"file": ("an.txt", "annotation text", "text/plain")}
    )
    fid = res.json()["id"]
    res = await client.post(
        "/api/v1/annotations", json={"fid": fid, "pos0": 0, "pos1": 6, "memo": "ann"}
    )
    anid = res.json()["anid"]

    # annotation.delete row whose detail carries the still-existing row:
    # undo tries to re-insert it → unique collision → clean 422.
    with sqlite3.connect(str(open_project / "data.qda")) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(annotation)")]
        vals = conn.execute(
            "SELECT * FROM annotation WHERE anid = ?", (anid,)
        ).fetchone()
    row = dict(zip(cols, vals, strict=True))
    _insert_legacy_audit(
        open_project, "annotation.delete", "annotation", entity_id=anid, detail={"anid": anid, **row}
    )
    aid = await _find_audit_id(client, "annotation.delete")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 422, res.text
    assert "cannot restore annotation" in res.json()["detail"], res.text


async def test_endpoint_surfaces_message_as_detail(client, open_project, settings_file):
    """The audit.undo endpoint must surface the missing-data message as the
    response detail (read-only check of the 422 mapping)."""
    _insert_legacy_audit(open_project, "bookmark.set", "project", detail={})
    aid = await _find_audit_id(client, "bookmark.set")
    res = await client.post("/api/v1/audit/undo", json={"id": aid})
    assert res.status_code == 422
    assert res.json()["detail"] == MISSING_DATA_MESSAGE
    # Same for redo.
    res = await client.post("/api/v1/audit/redo", json={"id": aid})
    assert res.status_code == 422
    assert res.json()["detail"] == MISSING_DATA_MESSAGE
