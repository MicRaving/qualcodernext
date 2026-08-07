"""Coding engine service tests — shift_positions, commit_edit, autocode, undo."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    AnnotationRepository,
    CaseRepository,
    CodeRepository,
    CodingRepository,
    SourceRepository,
)
from qualcoder_api.services.coding_service import (
    autocode,
    commit_edit,
    shift_positions,
    undo_codings,
)
from qualcoder_api.services.project_service import ProjectService


@pytest.fixture
async def project_session(tmp_path: Path):
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "coding.qda"), codername="tester")
    assert svc.session_factory is not None
    async with svc.session_factory() as session:
        yield session
    await svc.close_project()


# ----------------------------------------------------------------------
# shift_positions — pure position-shift logic (port of update_positions)
# ----------------------------------------------------------------------


def test_shift_add_at_start():
    result = shift_positions(
        "I read books",
        "X I read books",
        [
            {"ctid": 1, "pos0": 2, "pos1": 6},  # 'read'
            {"ctid": 2, "pos0": 0, "pos1": 3},  # starts at 0
        ],
        [],
        [],
    )
    codings = result["codings"]
    # 'read' shifts right by the 2 inserted chars: 2-6 -> 4-8
    assert codings[0]["ctid"] == 1
    assert codings[0]["newpos0"] == 4
    assert codings[0]["newpos1"] == 8
    # pos0 == 0 special case keeps the new start at 0
    assert codings[1]["newpos0"] == 0
    assert codings[1]["newpos1"] == 5
    # original keys are preserved untouched
    assert codings[0]["pos0"] == 2
    assert codings[0]["pos1"] == 6


def test_shift_add_at_start_does_not_mutate_input():
    codings = [{"ctid": 1, "pos0": 2, "pos1": 6}]
    shift_positions("I read books", "X I read books", codings, [], [])
    assert codings == [{"ctid": 1, "pos0": 2, "pos1": 6}]


def test_shift_add_in_middle():
    result = shift_positions(
        "I read books",
        "I read big books",
        [
            {"ctid": 1, "pos0": 2, "pos1": 6},  # 'read' — before insertion point
            {"ctid": 2, "pos0": 7, "pos1": 12},  # 'books' — after insertion point
        ],
        [],
        [],
    )
    codings = result["codings"]
    assert (codings[0]["newpos0"], codings[0]["newpos1"]) == (2, 6)
    assert (codings[1]["newpos0"], codings[1]["newpos1"]) == (11, 16)


def test_shift_remove_in_middle():
    result = shift_positions(
        "I read big books",
        "I read books",
        [{"ctid": 1, "pos0": 7, "pos1": 10}],  # 'big'
        [],
        [],
    )
    # legacy shifts the removed segment back onto the surviving text
    c = result["codings"][0]
    assert (c["newpos0"], c["newpos1"]) == (3, 6)
    assert result["deletions"]["code_text"] == []


def test_shift_remove_in_middle_crossing_segment_deleted():
    result = shift_positions(
        "I read big books",
        "I read books",
        [
            {"ctid": 1, "pos0": 6, "pos1": 8},  # crosses the deletion boundary
            {"ctid": 2, "pos0": 6, "pos1": 7},
            {"ctid": 3, "pos0": 2, "pos1": 6},  # 'read' — untouched
        ],
        [],
        [],
    )
    codings = result["codings"]
    assert codings[0]["newpos0"] is None
    assert codings[1]["newpos0"] is None
    assert (codings[2]["newpos0"], codings[2]["newpos1"]) == (2, 6)
    assert result["deletions"]["code_text"] == [1, 2]


def test_shift_add_at_end():
    result = shift_positions(
        "I read books",
        "I read books!",
        [
            {"ctid": 1, "pos0": 2, "pos1": 6},  # 'read' — before insertion point
            {"ctid": 2, "pos0": 7, "pos1": 12},  # 'books' — ends at insertion point
        ],
        [],
        [],
    )
    codings = result["codings"]
    assert (codings[0]["newpos0"], codings[0]["newpos1"]) == (2, 6)
    # coding ending exactly at the insertion point extends by chars_len
    assert (codings[1]["newpos0"], codings[1]["newpos1"]) == (7, 13)


def test_shift_remove_from_end():
    result = shift_positions(
        "I read books!",
        "I read books",
        [{"ctid": 1, "pos0": 7, "pos1": 13}],  # 'books!'
        [],
        [],
    )
    c = result["codings"][0]
    assert (c["newpos0"], c["newpos1"]) == (7, 12)


def test_shift_remove_from_start_clamps_to_zero():
    result = shift_positions(
        "abcd",
        "bcd",
        [
            {"ctid": 1, "pos0": 0, "pos1": 1},  # 'a' fully removed
            {"ctid": 2, "pos0": 2, "pos1": 3},  # 'c' still present
        ],
        [],
        [],
    )
    codings = result["codings"]
    assert (codings[0]["newpos0"], codings[0]["newpos1"]) == (0, 0)
    assert (codings[1]["newpos0"], codings[1]["newpos1"]) == (1, 2)


def test_shift_unicode_and_emoji():
    # emoji is a single python code point; the algorithm uses len() semantics
    # 'a😀b' is 3 chars -> insertion at preceding_pos 2; coding 2-4 shifts +1
    result = shift_positions(
        "a\N{GRINNING FACE}bc",
        "a\N{GRINNING FACE}bXc",
        [{"ctid": 1, "pos0": 2, "pos1": 4}],
        [],
        [],
    )
    c = result["codings"][0]
    assert (c["newpos0"], c["newpos1"]) == (3, 5)

    # no diff -> positions unchanged
    result = shift_positions(
        "a\N{GRINNING FACE}bc",
        "a\N{GRINNING FACE}bc",
        [{"ctid": 2, "pos0": 1, "pos1": 2}],
        [],
        [],
    )
    c = result["codings"][0]
    assert (c["newpos0"], c["newpos1"]) == (1, 2)


def test_shift_no_diff_is_idempotent():
    result = shift_positions(
        "I read books",
        "I read books",
        [{"ctid": 1, "pos0": 2, "pos1": 6, "cid": 9}],
        [{"anid": 1, "pos0": 7, "pos1": 12}],
        [{"id": 1, "pos0": 0, "pos1": 12}],
    )
    assert result["codings"][0]["newpos0"] == 2
    assert result["codings"][0]["newpos1"] == 6
    assert result["annotations"][0]["newpos0"] == 7
    assert result["case_text"][0]["newpos1"] == 12
    assert result["deletions"] == {"code_text": [], "annotation": [], "case_text": []}


def test_shift_annotations_and_case_text():
    result = shift_positions(
        "I read books",
        "I read big books",
        [],
        [{"anid": 1, "pos0": 2, "pos1": 6}],
        [{"id": 1, "pos0": 0, "pos1": 12}],
    )
    a = result["annotations"][0]
    assert (a["newpos0"], a["newpos1"]) == (2, 6)
    c = result["case_text"][0]
    assert (c["newpos0"], c["newpos1"]) == (0, 16)


def test_shift_deletions_marked_none():
    result = shift_positions(
        "I read big books",
        "I read books",
        [{"ctid": 1, "pos0": 6, "pos1": 7}],
        [{"anid": 2, "pos0": 6, "pos1": 7}],
        [{"id": 3, "pos0": 6, "pos1": 7}],
    )
    assert result["codings"][0]["newpos0"] is None
    assert result["annotations"][0]["newpos0"] is None
    assert result["case_text"][0]["newpos0"] is None
    assert result["deletions"] == {"code_text": [1], "annotation": [2], "case_text": [3]}


# ----------------------------------------------------------------------
# autocode
# ----------------------------------------------------------------------


async def _seed_source_and_code(session, text: str, name: str = "doc.txt"):
    source = await SourceRepository(session).add_source(
        name=name, mediapath=f"/docs/{name}", fulltext=text, owner="tester"
    )
    code = await CodeRepository(session).add_code(name="animal", owner="tester")
    return source, code


async def test_autocode_all_first_last_modes(project_session):
    session = project_session
    source, code = await _seed_source_and_code(session, "cat dog cat bird cat")

    all_ = await autocode(
        session, fid=source.id, cid=code.cid, find_texts=["cat"], mode="all", owner="t-all"
    )
    assert [c["pos0"] for c in all_] == [0, 8, 17]
    assert all(c["seltext"] == "cat" for c in all_)
    assert all(c["cid"] == code.cid and c["fid"] == source.id for c in all_)

    first = await autocode(
        session, fid=source.id, cid=code.cid, find_texts=["cat"], mode="first", owner="t-first"
    )
    assert [c["pos0"] for c in first] == [0]

    last = await autocode(
        session, fid=source.id, cid=code.cid, find_texts=["cat"], mode="last", owner="t-last"
    )
    assert [c["pos0"] for c in last] == [17]


async def test_autocode_regex_mode(project_session):
    session = project_session
    source, code = await _seed_source_and_code(session, "cat dog cat bird cat")
    created = await autocode(
        session,
        fid=source.id,
        cid=code.cid,
        find_texts=[r"c.t"],
        mode="all",
        use_regex=True,
        owner="t-regex",
    )
    assert [c["pos0"] for c in created] == [0, 8, 17]
    # regex seltext is the matched substring
    assert all(c["seltext"] == "cat" for c in created)


async def test_autocode_invalid_regex_raises(project_session):
    session = project_session
    source, code = await _seed_source_and_code(session, "cat")
    with pytest.raises(ValueError, match="invalid regex"):
        await autocode(
            session, fid=source.id, cid=code.cid, find_texts=["["], use_regex=True, owner="x"
        )


async def test_autocode_without_fid_covers_all_text_sources(project_session):
    session = project_session
    _, code = await _seed_source_and_code(session, "cat a", name="a.txt")
    await SourceRepository(session).add_source(
        name="img.png", mediapath="/images/img.png", fulltext="cat b", owner="tester"
    )
    await SourceRepository(session).add_source(
        name="ext.txt", mediapath="docs:C:/ext.txt", fulltext="cat c", owner="tester"
    )
    created = await autocode(
        session, fid=None, cid=code.cid, find_texts=["cat"], mode="all", owner="t-all"
    )
    assert len(created) == 2  # /images/ and /audio/... sources are excluded
    assert sorted({c["fid"] for c in created}) == sorted(c["fid"] for c in created)


async def test_autocode_skips_duplicate_inserts(project_session):
    session = project_session
    source, code = await _seed_source_and_code(session, "cat dog cat")
    created = await autocode(
        session, fid=source.id, cid=code.cid, find_texts=["cat", "cat"], mode="all", owner="t-dup"
    )
    assert len(created) == 2  # second find_text is entirely duplicate


async def test_autocode_emoji_position_adjustment(project_session):
    session = project_session
    source, code = await _seed_source_and_code(session, "cat \N{GRINNING FACE} dog")
    created = await autocode(
        session, fid=source.id, cid=code.cid, find_texts=["dog"], mode="all", owner="t-emoji"
    )
    assert len(created) == 1
    # legacy adds each preceding emoji's extra length (match_end - match_start)
    assert created[0]["pos0"] == 7
    assert created[0]["pos1"] == 10


async def test_autocode_code_within_code_keeps_matches_inside_coded_spans(project_session):
    """The legacy code_within_code mode now filters matches to the coded
    spans of the given code (same file and owner)."""
    session = project_session
    source, code = await _seed_source_and_code(session, "alpha beta alpha")
    # Seed a coding of the second half of the text under code id 9999.
    await session.execute(
        tables.code_text.insert().values(
            cid=9999, fid=source.id, seltext="beta alpha", pos0=6, pos1=16,
            owner="x", date="", memo="",
        )
    )
    await session.commit()
    created = await autocode(
        session,
        fid=source.id,
        cid=code.cid,
        find_texts=["alpha"],
        mode="code_within_code 9999",
        owner="x",
    )
    assert len(created) == 1
    assert created[0]["pos0"] == 11


# ----------------------------------------------------------------------
# commit_edit
# ----------------------------------------------------------------------


async def test_commit_edit_middle_remove_shifts_and_rewrites(project_session):
    session = project_session
    source = await SourceRepository(session).add_source(
        name="t.txt", mediapath="/docs/t.txt", fulltext="I read big books today", owner="tester"
    )
    code = await CodeRepository(session).add_code(name="c", owner="tester")
    repo = CodingRepository(session)
    await repo.add_text_coding(
        cid=code.cid, fid=source.id, seltext="big", pos0=7, pos1=10, owner="tester"
    )
    await AnnotationRepository(session).add_annotation(
        fid=source.id, pos0=2, pos1=6, memo="note", owner="tester"
    )
    case = await CaseRepository(session).add_case(name="P1", owner="tester")
    await CaseRepository(session).link_text_span(
        caseid=case.caseid, fid=source.id, pos0=2, pos1=6, owner="tester"
    )

    new_text = "I read books today"
    summary = await commit_edit(session, fid=source.id, new_text=new_text, owner="tester")

    assert summary["updated"] == {"code_text": 1, "annotation": 1, "case_text": 1}
    assert summary["deleted"] == {"code_text": [], "annotation": [], "case_text": []}

    src = await SourceRepository(session).get_source(source.id)
    assert src is not None
    assert src.fulltext == new_text

    rows = (await session.execute(select(tables.code_text))).all()
    assert len(rows) == 1
    row = rows[0]
    # legacy diff aligns "ig b" as the removed chunk: 7-10 shifts back by 4
    assert (row.pos0, row.pos1) == (3, 6)
    assert row.seltext == new_text[3:6]

    ann_rows = (await session.execute(select(tables.annotation))).all()
    assert len(ann_rows) == 1
    assert (ann_rows[0].pos0, ann_rows[0].pos1) == (2, 6)

    case_rows = (await session.execute(select(tables.case_text))).all()
    assert len(case_rows) == 1
    assert (case_rows[0].pos0, case_rows[0].pos1) == (2, 6)


async def test_commit_edit_deletes_vanished_segment(project_session):
    session = project_session
    source = await SourceRepository(session).add_source(
        name="t.txt", mediapath="/docs/t.txt", fulltext="I read big books today", owner="tester"
    )
    code = await CodeRepository(session).add_code(name="c", owner="tester")
    repo = CodingRepository(session)
    coding = await repo.add_text_coding(
        cid=code.cid, fid=source.id, seltext=" ", pos0=6, pos1=7, owner="tester"
    )

    summary = await commit_edit(session, fid=source.id, new_text="I read books today", owner="tester")
    assert summary["updated"]["code_text"] == 0
    assert summary["deleted"]["code_text"] == [coding.ctid]
    rows = (await session.execute(select(tables.code_text))).all()
    assert rows == []


async def test_commit_edit_end_append_keeps_positions(project_session):
    session = project_session
    source = await SourceRepository(session).add_source(
        name="t.txt", mediapath="/docs/t.txt", fulltext="I read big books today", owner="tester"
    )
    code = await CodeRepository(session).add_code(name="c", owner="tester")
    repo = CodingRepository(session)
    await repo.add_text_coding(
        cid=code.cid, fid=source.id, seltext="big", pos0=7, pos1=10, owner="tester"
    )

    new_text = "I read big books today!"
    summary = await commit_edit(session, fid=source.id, new_text=new_text, owner="tester")
    assert summary["updated"]["code_text"] == 1

    src = await SourceRepository(session).get_source(source.id)
    assert src is not None
    assert src.fulltext == new_text
    rows = (await session.execute(select(tables.code_text))).all()
    assert len(rows) == 1
    assert (rows[0].pos0, rows[0].pos1) == (7, 10)
    assert rows[0].seltext == "big"


async def test_commit_edit_missing_source_raises(project_session):
    session = project_session
    with pytest.raises(ValueError, match="source not found"):
        await commit_edit(session, fid=999, new_text="x", owner="tester")


# ----------------------------------------------------------------------
# undo_codings
# ----------------------------------------------------------------------


async def test_undo_codings_restores_deleted_rows(project_session):
    session = project_session
    source, code = await _seed_source_and_code(session, "I read big books today")
    coding = await CodingRepository(session).add_text_coding(
        cid=code.cid, fid=source.id, seltext="big", pos0=7, pos1=10, owner="tester", memo="m"
    )
    item = {
        "ctid": coding.ctid,
        "cid": coding.cid,
        "fid": coding.fid,
        "seltext": coding.seltext,
        "pos0": coding.pos0,
        "pos1": coding.pos1,
        "owner": coding.owner,
        "memo": coding.memo,
        "date": coding.date,
        "important": coding.important,
    }
    await CodingRepository(session).delete_text_coding(coding.ctid)

    restored = await undo_codings(session, [item])
    assert restored == 1
    rows = (await session.execute(select(tables.code_text))).all()
    assert len(rows) == 1
    assert (rows[0].pos0, rows[0].pos1) == (7, 10)
    assert rows[0].seltext == "big"
    assert rows[0].memo == "m"

    # restoring the same row again is skipped (unique constraint)
    restored = await undo_codings(session, [item])
    assert restored == 0
