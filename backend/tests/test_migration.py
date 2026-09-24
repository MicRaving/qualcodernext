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

ALL_VERSIONS = [f"v{v}" for v in range(2, 32)] + ["v34", "v35", "v36", "v37", "v38", "v39"]


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
    assert row[0] == "v39"
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
        "annotation_visible", "link",
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


async def test_v22_adds_value_labels_column(v2_db):
    """v22 adds attribute_type.value_labels without touching existing rows."""
    cur = await v2_db.cursor()
    await cur.execute(
        "INSERT INTO attribute_type (name, date, owner, memo, caseOrFile, valuetype) "
        "VALUES ('Age', '2020-01-01', 'alice', '', 'case', 'number')"
    )
    await v2_db.commit()

    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v22" in applied

    cols = await _columns(v2_db, "attribute_type")
    assert "value_labels" in cols
    # Pre-existing rows are unaffected (column stays NULL → API default {}).
    await cur.execute("SELECT name, value_labels FROM attribute_type WHERE name = 'Age'")
    assert await cur.fetchone() == ("Age", None)


async def test_v23_adds_dictionary_tables(v2_db):
    """v23 adds the word-dictionary tables and they stay queryable."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v23" in applied

    objects = await _objects(v2_db)
    assert {"dictionary", "dictionary_entry"} <= objects
    cur = await v2_db.cursor()
    await cur.execute("PRAGMA table_info(dictionary)")
    cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "name", "owner", "created"} <= cols
    await cur.execute("PRAGMA table_info(dictionary_entry)")
    entry_cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "dict_id", "code_name", "term"} <= entry_cols


async def test_v24_adds_creative_item_table(v2_db):
    """v24 adds the creative-coding scratchpad table and its index."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v24" in applied

    objects = await _objects(v2_db)
    assert "creative_item" in objects
    cur = await v2_db.cursor()
    await cur.execute("PRAGMA table_info(creative_item)")
    cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "text", "source_fid", "pos0", "pos1", "note", "owner", "date"} <= cols
    # Unsourced items are allowed (positions nullable).
    await cur.execute(
        "INSERT INTO creative_item (text, note, owner, date) "
        "VALUES ('an idea', 'keep', 'alice', '2026-01-01')"
    )
    await v2_db.commit()
    await cur.execute("SELECT text, source_fid, pos0, pos1 FROM creative_item")
    assert await cur.fetchone() == ("an idea", None, None, None)
    # The source_fid hot-path index exists.
    await cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_creative_item_source_fid'"
    )
    assert await cur.fetchone() is not None


async def test_v25_adds_qtt_tables(v2_db):
    """v25 adds the QTT worksheet tables and the sheet_id index."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v25" in applied

    objects = await _objects(v2_db)
    assert {"qtt_sheet", "qtt_item"} <= objects
    cur = await v2_db.cursor()
    await cur.execute("PRAGMA table_info(qtt_sheet)")
    sheet_cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "name", "kind", "sections_json", "research_question", "purpose", "framework", "owner", "date"} <= sheet_cols
    await cur.execute("PRAGMA table_info(qtt_item)")
    item_cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "sheet_id", "section", "kind", "payload_json", "owner", "date"} <= item_cols
    # Rows round-trip (JSON payloads).
    await cur.execute(
        "INSERT INTO qtt_sheet (name, kind, sections_json, owner, date) "
        "VALUES ('Board', 'qual', '[\"Insights\"]', 'alice', '2026-01-01')"
    )
    await cur.execute(
        "INSERT INTO qtt_item (sheet_id, section, kind, payload_json, owner, date) "
        "VALUES (1, 'Insights', 'note', '{\"text\":\"hi\"}', 'alice', '2026-01-01')"
    )
    await v2_db.commit()
    await cur.execute("SELECT name, kind, sections_json FROM qtt_sheet")
    assert await cur.fetchone() == ("Board", "qual", '["Insights"]')
    # The sheet_id hot-path index exists.
    await cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_qtt_item_sheet_id'"
    )
    assert await cur.fetchone() is not None


async def test_v26_adds_comment_table(v2_db):
    """v26 adds the comment table + target index."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v26" in applied
    objects = await _objects(v2_db)
    assert "comment" in objects
    cur = await v2_db.cursor()
    await cur.execute("PRAGMA table_info(comment)")
    cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "target_kind", "target_id", "body", "owner", "created"} <= cols
    await cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_comment_target'"
    )
    assert await cur.fetchone() is not None


async def test_v27_adds_weight_columns(v2_db):
    """v27 adds the weight column to the three coding tables."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v27" in applied
    for table in ("code_text", "code_image", "code_av"):
        cols = await _columns(v2_db, table)
        assert "weight" in cols


async def test_v28_adds_memo_type_columns(v2_db):
    """v28 adds memo_type to code_name and source."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v28" in applied
    for table in ("code_name", "source"):
        cols = await _columns(v2_db, table)
        assert "memo_type" in cols


async def test_v29_adds_code_set_tables(v2_db):
    """v29 adds the code_set tables + member index."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v31" in applied
    objects = await _objects(v2_db)
    assert {"code_set", "code_set_member"} <= objects
    cur = await v2_db.cursor()
    await cur.execute("PRAGMA table_info(code_set)")
    cols = {row[1] for row in await cur.fetchall()}
    assert {"id", "name", "owner", "created"} <= cols
    await cur.execute("PRAGMA table_info(code_set_member)")
    member_cols = {row[1] for row in await cur.fetchall()}
    assert {"set_id", "cid"} <= member_cols


async def test_v36_adds_sync_rev_row_json(v2_db):
    """v36 adds the tombstone-content column to sync_rev (idempotent)."""
    chain = MigrationChain(v2_db)
    applied = await chain.run_all("4.0-test", "tester")
    assert "v36" in applied
    cur = await v2_db.cursor()
    await cur.execute("PRAGMA table_info(sync_rev)")
    cols = {row[1] for row in await cur.fetchall()}
    assert "row_json" in cols
    second = await chain.run_all("4.0-test", "tester")
    assert "v36" not in second


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


async def test_v32_adds_unique_sync_log_seq_index(tmp_path):
    """A database whose sync_log lacks the unique (user, seq) index gets it
    via migrate_v32, deduplicates colliding rows, and is stamped v32. A fresh
    schema (index already present) is a no-op."""
    from qualcoder_api.persistence.schema import create_new_project_schema

    db = tmp_path / "v31.qda"
    conn = await aiosqlite.connect(db)
    await create_new_project_schema(conn, app_version="4.0-test", codername="tester")
    cur = await conn.cursor()
    # Drop the index to simulate a pre-v32 database, then seed a duplicate
    # (user, seq) pair.
    await cur.execute("DROP INDEX IF EXISTS idx_sync_log_user_seq")
    await cur.execute(
        "INSERT INTO sync_log (ts, user, seq, entity, action, pk_name, pk_value, row_json) "
        "VALUES ('t','anna',1,'code_name','insert','cid','1','{}')"
    )
    await cur.execute(
        "INSERT INTO sync_log (ts, user, seq, entity, action, pk_name, pk_value, row_json) "
        "VALUES ('t','anna',1,'code_name','insert','cid','2','{}')"
    )
    await conn.commit()

    applied = await MigrationChain(conn).run_all("4.0-test", "tester")
    assert "v32" in applied
    await cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_sync_log_user_seq'"
    )
    assert await cur.fetchone() is not None
    # Duplicate (user, seq) was deduplicated.
    await cur.execute("SELECT COUNT(*) FROM sync_log WHERE user='anna'")
    assert (await cur.fetchone())[0] == 1
    # Re-running is a no-op (idempotent).
    second = await MigrationChain(conn).run_all("4.0-test", "tester")
    assert "v32" not in second
    await conn.close()


async def test_v34_adds_ai_chat_tables(tmp_path):
    """v34 creates the persistent AI chat/template tables on legacy projects
    and is a no-op on a fresh schema (which already contains them)."""
    from qualcoder_api.persistence.schema import create_new_project_schema

    db = tmp_path / "legacy.qda"
    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    for sql in LEGACY_TABLES:
        await cur.execute(sql)
    await cur.execute("INSERT INTO project VALUES ('v2', '2020-01-01', '', 'QualCoder 1.0')")
    await conn.commit()

    applied = await MigrationChain(conn).run_all("4.0-test", "tester")
    assert "v34" in applied
    objects = await _objects(conn)
    assert {"ai_chat", "ai_chat_message", "ai_prompt"} <= objects
    await cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_ai_chat_message_chat_id'"
    )
    assert await cur.fetchone() is not None
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v39"
    await conn.close()

    # Fresh schema: tables already exist → v34, v35 and v36 are no-ops.
    fresh = tmp_path / "fresh.qda"
    conn = await aiosqlite.connect(fresh)
    await create_new_project_schema(conn, app_version="4.0-test", codername="tester")
    applied = await MigrationChain(conn).run_all("4.0-test", "tester")
    assert "v34" not in applied
    assert applied == []
    await conn.close()


_V37_META_DDL = [
    "CREATE TABLE project (databaseversion text, date text, memo text, about text)",
    "CREATE TABLE meta_criterion (id integer primary key autoincrement, position integer not null default 0, "
    "key text not null, label text not null, prompt_text text not null, created text)",
    "CREATE TABLE meta_screening (id integer primary key autoincrement, hit_id integer not null, "
    "owner text not null, run_id text not null default '', verdicts text, intervention_type text, "
    "rationale text, origin text not null default 'manual', model text, prompt_hash text, "
    "created text, updated text, unique(hit_id, owner, run_id))",
    "CREATE TABLE meta_extraction (id integer primary key autoincrement, hit_id integer not null, "
    "source_id integer, owner text not null, scheme text not null, study_vars text, dv_metrics text, "
    "prescreen text, model text, prompt_hash text, status text not null default 'prescreen_pending', "
    "missing_reason text, created text, updated text, unique(hit_id))",
]


async def _unique_columns(conn: aiosqlite.Connection, table: str) -> set[tuple[str, ...]]:
    cur = await conn.cursor()
    await cur.execute(f"PRAGMA index_list({table})")
    out: set[tuple[str, ...]] = set()
    for row in await cur.fetchall():
        if not row[2]:
            continue
        await cur.execute(f"PRAGMA index_info({row[1]})")
        out.add(tuple(info[2] for info in await cur.fetchall()))
    return out


async def test_v38_migrates_v37_meta_schema(tmp_path):
    """A v37 project gains the v2 criterion/screening columns and the
    ``UNIQUE(hit_id, owner)`` extraction constraint, preserving rows."""
    db = tmp_path / "v37.qda"
    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    for sql in _V37_META_DDL:
        await cur.execute(sql)
    await cur.execute("INSERT INTO project VALUES ('v37', '2020-01-01', '', 'QualCoder 4.0')")
    await cur.execute(
        "INSERT INTO meta_criterion (position, key, label, prompt_text, created) "
        "VALUES (0, 'c1', 'Intervention', 'Targets misinformation?', '')"
    )
    await cur.execute(
        "INSERT INTO meta_screening (hit_id, owner, run_id, verdicts, created, updated) "
        "VALUES (1, 'anna', '', '{\"c1\": {\"applies\": \"Yes\"}}', '', '')"
    )
    await cur.execute(
        "INSERT INTO meta_extraction (hit_id, owner, scheme, study_vars, dv_metrics, status, created, updated) "
        "VALUES (1, 'anna', 'scheme1', '{\"records\": []}', '[]', 'extracted', '', '')"
    )
    await conn.commit()

    applied = await MigrationChain(conn).migrate_v38("4.0-test")
    assert applied == ["v38"]

    cur = await conn.cursor()
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v38"

    criterion_cols = await _columns(conn, "meta_criterion")
    assert {"kind", "options", "pass_values", "exclude_reason", "gating", "help"} <= criterion_cols
    screening_cols = await _columns(conn, "meta_screening")
    assert {"stage", "reason"} <= screening_cols

    # Rows preserved, defaults applied.
    await cur.execute("SELECT kind, pass_values, gating FROM meta_criterion WHERE key='c1'")
    assert await cur.fetchone() == ("verdict", '["yes"]', 1)
    await cur.execute("SELECT stage, reason FROM meta_screening WHERE hit_id=1")
    assert await cur.fetchone() == ("abstract", "")

    # The extraction row survived and the constraint now allows a second owner.
    assert ("hit_id", "owner") in await _unique_columns(conn, "meta_extraction")
    await cur.execute("SELECT COUNT(*) FROM meta_extraction WHERE hit_id=1")
    assert (await cur.fetchone())[0] == 1
    await cur.execute(
        "INSERT INTO meta_extraction (hit_id, owner, scheme, status) "
        "VALUES (1, 'bob', 'scheme1', 'extracted')"
    )
    await conn.commit()
    await cur.execute("SELECT COUNT(DISTINCT owner) FROM meta_extraction WHERE hit_id=1")
    assert (await cur.fetchone())[0] == 2

    # Idempotent: a second run is a no-op.
    assert await MigrationChain(conn).migrate_v38("4.0-test") == []
    await conn.close()


_V38_META_DDL = [
    "CREATE TABLE project (databaseversion text, date text, memo text, about text)",
    "CREATE TABLE meta_screening (id integer primary key autoincrement, hit_id integer not null, "
    "owner text not null, run_id text not null default '', verdicts text, intervention_type text, "
    "rationale text, origin text not null default 'manual', model text, prompt_hash text, "
    "created text, updated text, stage text not null default 'abstract', "
    "reason text not null default '', unique(hit_id, owner, run_id))",
    "CREATE TABLE meta_extraction (id integer primary key autoincrement, hit_id integer not null, "
    "source_id integer, owner text not null, scheme text not null, study_vars text, dv_metrics text, "
    "prescreen text, model text, prompt_hash text, status text not null default 'prescreen_pending', "
    "missing_reason text, created text, updated text, unique(hit_id, owner))",
]


async def test_v39_rebuilds_meta_uniqueness_preserving_rows(tmp_path):
    """v39 moves screening uniqueness to include stage and extraction
    uniqueness to include scheme, preserving every row."""
    db = tmp_path / "v38.qda"
    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    for sql in _V38_META_DDL:
        await cur.execute(sql)
    await cur.execute("INSERT INTO project VALUES ('v38', '2020-01-01', '', 'QualCoder 4.0')")
    await cur.execute(
        "INSERT INTO meta_screening (hit_id, owner, run_id, verdicts, stage, created, updated) "
        "VALUES (1, 'anna', 'r1', '{}', 'abstract', '', '')"
    )
    await cur.execute(
        "INSERT INTO meta_extraction (hit_id, owner, scheme, status, created, updated) "
        "VALUES (1, 'anna', 'scheme1', 'extracted', '', '')"
    )
    await conn.commit()

    applied = await MigrationChain(conn).migrate_v39("4.0-test")
    assert applied == ["v39"]

    cur = await conn.cursor()
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v39"
    assert ("hit_id", "owner", "run_id", "stage") in await _unique_columns(
        conn, "meta_screening"
    )
    assert ("hit_id", "owner", "scheme") in await _unique_columns(conn, "meta_extraction")

    # Rows preserved...
    await cur.execute("SELECT COUNT(*) FROM meta_screening")
    assert (await cur.fetchone())[0] == 1
    await cur.execute("SELECT COUNT(*) FROM meta_extraction")
    assert (await cur.fetchone())[0] == 1

    # ...and the new constraints permit the previously-colliding inserts.
    await cur.execute(
        "INSERT INTO meta_screening (hit_id, owner, run_id, verdicts, stage, created, updated) "
        "VALUES (1, 'anna', 'r1', '{}', 'fulltext', '', '')"
    )
    await cur.execute(
        "INSERT INTO meta_extraction (hit_id, owner, scheme, status, created, updated) "
        "VALUES (1, 'anna', 'scheme2', 'extracted', '', '')"
    )
    await conn.commit()
    await cur.execute("SELECT COUNT(*) FROM meta_screening")
    assert (await cur.fetchone())[0] == 2
    await cur.execute("SELECT COUNT(*) FROM meta_extraction")
    assert (await cur.fetchone())[0] == 2

    # Idempotent: a second run is a no-op.
    assert await MigrationChain(conn).migrate_v39("4.0-test") == []
    await conn.close()


async def test_fresh_schema_is_stamped_v39_without_migrations(tmp_path):
    """A fresh schema already matches v39; the chain stamps the version
    without reporting any migration step as applied."""
    from qualcoder_api.persistence.schema import create_new_project_schema

    db = tmp_path / "fresh.qda"
    conn = await aiosqlite.connect(db)
    await create_new_project_schema(conn, app_version="4.0-test", codername="tester")
    applied = await MigrationChain(conn).run_all("4.0-test", "tester")
    assert applied == []
    cur = await conn.cursor()
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v39"
    await conn.close()
