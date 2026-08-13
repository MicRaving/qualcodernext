"""Schema tests — the v14 schema created for new projects."""

from __future__ import annotations

import aiosqlite
import pytest

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.schema import create_new_project_schema

EXPECTED_TABLES = {
    "project",
    "source",
    "code_image",
    "code_av",
    "annotation",
    "link",
    "attribute_type",
    "attribute",
    "case_text",
    "cases",
    "code_cat",
    "code_text",
    "code_name",
    "journal",
    "stored_sql",
    "graph",
    "gr_cdct_text_item",
    "gr_case_text_item",
    "gr_file_text_item",
    "gr_free_text_item",
    "gr_cdct_line_item",
    "gr_free_line_item",
    "gr_pix_item",
    "gr_av_item",
    "gr_memo_item",
    "ris",
    "manage_files_display",
    "files_filter",
    "coder_names",
    "sync_log",
    "audit_log",
    "dictionary",
    "dictionary_entry",
    "creative_item",
    "qtt_sheet",
    "qtt_item",
}

EXPECTED_VIEWS = {
    "code_image_visible",
    "code_text_visible",
    "code_av_visible",
    "annotation_visible",
}


@pytest.fixture
async def new_db(tmp_path):
    db = tmp_path / "new.qda"
    conn = await aiosqlite.connect(db)
    await create_new_project_schema(conn, app_version="4.0-test", codername="tester")
    yield conn
    await conn.close()


async def _all_objects(conn: aiosqlite.Connection) -> set[str]:
    cur = await conn.cursor()
    await cur.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
        "AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in await cur.fetchall()}


async def test_all_v14_tables_created(new_db):
    names = await _all_objects(new_db)
    assert names >= EXPECTED_TABLES


async def test_all_visibility_views_created(new_db):
    names = await _all_objects(new_db)
    assert names >= EXPECTED_VIEWS


async def test_initial_project_row(new_db):
    cur = await new_db.cursor()
    await cur.execute(
        "SELECT databaseversion, memo, about, bookmarkfile, bookmarkpos, codername, "
        "recently_used_codes FROM project"
    )
    row = await cur.fetchone()
    assert row is not None
    assert row[0] == "v25"
    assert row[1] == ""
    assert row[2] == "4.0-test"
    assert row[3] == 0
    assert row[4] == 0
    assert row[5] == "tester"
    assert row[6] == ""


@pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
async def test_schema_matches_metadata_table(table_name, new_db):
    """Every legacy table exists in the SQLAlchemy metadata and vice versa."""
    metadata_names = {t.name for t in tables.metadata.tables.values()}
    assert table_name in metadata_names
    names = await _all_objects(new_db)
    assert table_name in names


async def test_metadata_has_no_extra_tables(new_db):
    metadata_names = {t.name for t in tables.metadata.tables.values()}
    names = await _all_objects(new_db)
    assert metadata_names == EXPECTED_TABLES
    assert names - {"coder_names"} >= EXPECTED_TABLES - {"coder_names"}


async def test_views_filter_hidden_coders(new_db):
    cur = await new_db.cursor()
    await cur.execute("INSERT INTO code_name (name, memo, owner, date, color) "
                      "VALUES ('code_a', '', 'alice', '2026-01-01', '#ffffff')")
    await cur.execute("INSERT INTO source (name, fulltext, mediapath, owner, date) "
                      "VALUES ('f1.txt', 'hello world', '/docs/f1.txt', 'alice', '2026-01-01')")
    await cur.execute("INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date) "
                      "VALUES (1, 1, 'hello', 0, 5, 'alice', '2026-01-01')")
    await cur.execute("INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date) "
                      "VALUES (1, 1, 'world', 6, 11, 'bob', '2026-01-01')")
    await cur.execute("INSERT INTO coder_names (name, visibility) VALUES ('bob', 0)")
    await new_db.commit()
    await cur.execute("SELECT count(*) FROM code_text_visible")
    assert (await cur.fetchone())[0] == 1
