"""Migration chain tests — legacy v2-era databases converge to v18."""

from __future__ import annotations

import aiosqlite
import pytest

from qualcoder_api.persistence.migration import MigrationChain

LEGACY_TABLES = [
    "CREATE TABLE project (databaseversion text, date text, memo text, about text)",
    "CREATE TABLE source (id integer primary key, name text, fulltext text, mediapath text, memo text, "
    "owner text, date text, unique(name))",
    "CREATE TABLE code_image (imid integer primary key, id integer, x1 integer, y1 integer, width integer, "
    "height integer, cid integer, memo text, date text, owner text)",
    "CREATE TABLE code_av (avid integer primary key, id integer, pos0 integer, pos1 integer, cid integer, "
    "memo text, date text, owner text)",
    "CREATE TABLE annotation (anid integer primary key, fid integer, pos0 integer, pos1 integer, memo text, "
    "owner text, date text, unique(fid,pos0,pos1,owner))",
    "CREATE TABLE attribute_type (name text primary key, date text, owner text, memo text, caseOrFile text, "
    "valuetype text)",
    "CREATE TABLE attribute (attrid integer primary key, name text, attr_type text, value text, id integer, "
    "date text, owner text, unique(name,attr_type,id))",
    "CREATE TABLE case_text (id integer primary key, caseid integer, fid integer, pos0 integer, pos1 integer, "
    "owner text, date text)",
    "CREATE TABLE cases (caseid integer primary key, name text, memo text, owner text, date text, "
    "constraint ucm unique(name))",
    "CREATE TABLE code_cat (catid integer primary key, name text, owner text, date text, memo text, "
    "supercatid integer, unique(name))",
    "CREATE TABLE code_text (cid integer, fid integer, seltext text, pos0 integer, pos1 integer, "
    "owner text, date text, memo text)",
    "CREATE TABLE code_name (cid integer primary key, name text, memo text, catid integer, owner text, "
    "date text, color text, unique(name))",
    "CREATE TABLE journal (jid integer primary key, name text, jentry text, date text, owner text)",
]

ALL_VERSIONS = [f"v{v}" for v in range(2, 21)]


@pytest.fixture
async def v2_db(tmp_path):
    """A legacy v2-era database with representative data."""
    db = tmp_path / "legacy.qda"
    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    for sql in LEGACY_TABLES:
        await cur.execute(sql)
    await cur.execute("INSERT INTO project VALUES ('v2', '2020-01-01', 'memo', 'QualCoder 1.0')")
    await cur.execute("INSERT INTO code_name (name, memo, owner, date, color) "
                      "VALUES ('code_a', '', 'alice', '2020-01-01', '#F5F6CE')")
    await cur.execute("INSERT INTO code_name (name, memo, owner, date, color) "
                      "VALUES ('code_b', '', 'bob', '2020-01-01', '#F2F5A9')")
    await cur.execute("INSERT INTO source (name, fulltext, mediapath, owner, date) "
                      "VALUES ('interview.txt', 'hello world and more', '/docs/interview.txt', "
                      "'alice', '2020-01-01')")
    await cur.execute("INSERT INTO source (name, fulltext, mediapath, owner, date) "
                      "VALUES ('talk.mp3', '', '/audio/talk.mp3', 'bob', '2020-01-01')")
    await cur.execute("INSERT INTO source (name, fulltext, mediapath, owner, date) "
                      "VALUES ('talk.mp3.transcribed', 'transcript', '/docs/talk.mp3.transcribed', "
                      "'bob', '2020-01-01')")
    await cur.execute("INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date, memo) "
                      "VALUES (1, 1, 'hello world', 0, 11, 'alice', '2020-01-01', '')")
    await cur.execute("INSERT INTO code_text (cid, fid, seltext, pos0, pos1, owner, date, memo) "
                      "VALUES (2, 1, 'and more', 12, 20, 'bob', '2020-01-01', '')")
    await cur.execute("INSERT INTO code_image (id, x1, y1, width, height, cid, memo, date, owner) "
                      "VALUES (1, 10, 20, 30, 40, 1, '', '2020-01-01', 'alice')")
    await cur.execute("INSERT INTO code_av (id, pos0, pos1, cid, memo, date, owner) "
                      "VALUES (2, 500, 1500, 2, '', '2020-01-01', 'bob')")
    await conn.commit()
    yield conn
    await conn.close()


async def _columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    cur = await conn.cursor()
    await cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cur.fetchall()}


async def _objects(conn: aiosqlite.Connection) -> set[str]:
    cur = await conn.cursor()
    await cur.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
        "AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in await cur.fetchall()}


async def test_full_chain_returns_all_versions(v2_db):
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert applied == ALL_VERSIONS


async def test_full_chain_sets_final_version(v2_db):
    chain = MigrationChain(v2_db)
    await chain.run_all("4.0-test", "tester")
    cur = await v2_db.cursor()
    await cur.execute("SELECT databaseversion, about FROM project")
    row = await cur.fetchone()
    assert row[0] == "v19"
    assert row[1] == "4.0-test"


async def test_code_text_rebuilt_with_ctid(v2_db):
    chain = MigrationChain(v2_db)
    await chain.run_all("4.0-test", "tester")
    cols = await _columns(v2_db, "code_text")
    assert {"ctid", "avid", "important"} <= cols
    cur = await v2_db.cursor()
    await cur.execute("SELECT ctid, cid, seltext, pos0, pos1, owner FROM code_text ORDER BY ctid")
    rows = await cur.fetchall()
    assert len(rows) == 2
    assert rows[0] == (1, 1, "hello world", 0, 11, "alice")
    assert rows[1] == (2, 2, "and more", 12, 20, "bob")


async def test_coding_data_preserved_across_media_tables(v2_db):
    chain = MigrationChain(v2_db)
    await chain.run_all("4.0-test", "tester")
    cur = await v2_db.cursor()
    # v15 backfills NULL important (the API models require an int).
    await cur.execute("SELECT x1, y1, width, height, cid, important FROM code_image")
    assert await cur.fetchone() == (10, 20, 30, 40, 1, 0)
    await cur.execute("SELECT pos0, pos1, cid, important FROM code_av")
    assert await cur.fetchone() == (500, 1500, 2, 0)


async def test_v5_links_transcribed_text(v2_db):
    chain = MigrationChain(v2_db)
    await chain.run_all("4.0-test", "tester")
    cur = await v2_db.cursor()
    await cur.execute(
        "SELECT av_text_id FROM source WHERE name = 'talk.mp3'"
    )
    row = await cur.fetchone()
    assert row is not None
    # transcription source id is 3 (inserted third)
    assert row[0] == 3


async def test_all_migration_tables_exist(v2_db):
    chain = MigrationChain(v2_db)
    await chain.run_all("4.0-test", "tester")
    objects = await _objects(v2_db)
    for table in (
        "stored_sql", "graph", "gr_cdct_text_item", "gr_case_text_item",
        "gr_file_text_item", "gr_free_text_item", "gr_cdct_line_item",
        "gr_free_line_item", "gr_pix_item", "gr_av_item", "gr_memo_item",
        "ris", "manage_files_display", "files_filter", "coder_names",
        "code_image_visible", "code_text_visible", "code_av_visible",
        "annotation_visible",
    ):
        assert table in objects, f"missing {table}"


async def test_subcode_and_av_bookmark_columns(v2_db):
    """v16 supercid + v18 av bookmark columns exist after the full chain."""
    chain = MigrationChain(v2_db)
    await chain.run_all("4.0-test", "tester")
    cols = await _columns(v2_db, "code_name")
    assert "supercid" in cols
    cols = await _columns(v2_db, "project")
    assert {"avbookmarkfile", "avbookmarkmsec", "avbookmarktextpos"} <= cols
    cols = await _columns(v2_db, "gr_cdct_line_item")
    assert {"label", "arrow_mode"} <= cols


async def test_chain_is_idempotent(v2_db):
    chain = MigrationChain(v2_db)
    await chain.run_all("4.0-test", "tester")
    second = await chain.run_all("4.0-test", "tester")
    assert second == []


async def test_v14_db_gets_no_migrations(tmp_path):
    """A pristine v18 database (fresh schema) needs no migrations."""
    db = tmp_path / "fresh.qda"
    conn = await aiosqlite.connect(db)
    from qualcoder_api.persistence.schema import create_new_project_schema

    await create_new_project_schema(conn, app_version="4.0-test", codername="tester")
    chain = MigrationChain(conn)
    applied = await chain.run_all("4.0-test", "tester")
    assert applied == []
    await conn.close()


async def test_migrated_v5_database_converges(v2_db):
    """Partial migration (v2→v5) then full chain still converges."""
    chain = MigrationChain(v2_db)
    await chain.migrate_v2_to_v5("4.0-test", "tester")
    await chain.migrate_v6_to_v14("4.0-test")
    cur = await v2_db.cursor()
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v14"
