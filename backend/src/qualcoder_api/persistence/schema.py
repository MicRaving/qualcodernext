"""New-project schema creation — v14 tables + initial project row.

Port of the legacy ``create_new_project_schema``. Uses a raw ``aiosqlite``
connection so the SQL is byte-identical to the legacy chain.
"""

from __future__ import annotations

import aiosqlite

from qualcoder_api.core.timeutil import now
from qualcoder_api.persistence import tables

_SCHEMA_SQL: list[str] = [
    "CREATE TABLE project (databaseversion text, date text, memo text,about text, bookmarkfile integer, "
    "bookmarkpos integer, codername text, recently_used_codes text, avbookmarkfile integer, "
    "avbookmarkmsec integer, avbookmarktextpos integer)",
    "CREATE TABLE source (id integer primary key, name text, fulltext text, mediapath text, memo text, "
    "owner text, date text, av_text_id integer, risid integer, memo_type text not null default '', unique(name))",
    "CREATE TABLE code_image (imid integer primary key,id integer,x1 integer, y1 integer, width integer, "
    "height integer, cid integer, memo text, date text, owner text, important integer, pdf_page integer, "
    "weight integer)",
    "CREATE TABLE code_av (avid integer primary key,id integer,pos0 integer, pos1 integer, cid integer, "
    "memo text, date text, owner text, important integer, weight integer)",
    "CREATE TABLE annotation (anid integer primary key, fid integer,pos0 integer, pos1 integer, memo text, "
    "owner text, date text, unique(fid,pos0,pos1,owner))",
    "CREATE TABLE link (id integer primary key autoincrement, from_fid integer, from_pos0 integer, "
    "from_pos1 integer, to_fid integer, to_pos0 integer, to_pos1 integer, memo text, owner text, date text)",
    "CREATE TABLE creative_item (id integer primary key autoincrement, text text, "
    "source_fid integer, pos0 integer, pos1 integer, note text, owner text, date text)",
    "CREATE TABLE attribute_type (name text primary key, date text, owner text, memo text, caseOrFile text, "
    "valuetype text, value_labels text)",
    "CREATE TABLE attribute (attrid integer primary key, name text, attr_type text, value text, id integer, "
    "date text, owner text, unique(name,attr_type,id))",
    "CREATE TABLE case_text (id integer primary key, caseid integer, fid integer, pos0 integer, pos1 integer, "
    "owner text, date text, memo text)",
    "CREATE TABLE cases (caseid integer primary key, name text, memo text, owner text,date text, "
    "constraint ucm unique(name))",
    "CREATE TABLE code_cat (catid integer primary key, name text, owner text, date text, memo text, "
    "supercatid integer, position integer not null default 0, unique(name))",
    "CREATE TABLE code_text (ctid integer primary key, cid integer, fid integer,seltext text, pos0 integer, "
    "pos1 integer, owner text, date text, memo text, avid integer, important integer, weight integer, "
    "unique(cid,fid,pos0,pos1, owner))",
    "CREATE TABLE code_name (cid integer primary key, name text, memo text, catid integer, owner text,"
    "date text, color text, supercid integer, memo_type text not null default '', "
    "position integer not null default 0, unique(name))",
    "CREATE TABLE journal (jid integer primary key, name text, jentry text, date text, owner text, unique(name))",
    "CREATE TABLE stored_sql (title text, description text, grouper text, ssql text, unique(title))",
    "CREATE TABLE graph (grid integer primary key, name text, description text, "
    "date text, scene_width integer, scene_height integer, unique(name));",
    "CREATE TABLE gr_cdct_text_item (gtextid integer primary key, grid integer, x integer, y integer, "
    "supercatid integer, catid integer, cid integer, font_size integer, bold integer, "
    "isvisible integer, displaytext text);",
    "CREATE TABLE gr_case_text_item (gcaseid integer primary key, grid integer, x integer, "
    "y integer, caseid integer, font_size integer, bold integer, color text, displaytext text);",
    "CREATE TABLE gr_file_text_item (gfileid integer primary key, grid integer, x integer, "
    "y integer, fid integer, font_size integer, bold integer, color text, displaytext text);",
    "CREATE TABLE gr_free_text_item (gfreeid integer primary key, grid integer, freetextid integer,"
    "x integer, y integer, free_text text, font_size integer, bold integer, color text,"
    "tooltip text, ctid integer,memo_ctid integer, memo_imid integer, memo_avid integer);",
    "CREATE TABLE gr_cdct_line_item (glineid integer primary key, grid integer, "
    "fromcatid integer, fromcid integer, tocatid integer, tocid integer, color text, "
    "linewidth real, linetype text, isvisible integer, label text, arrow_mode text);",
    "CREATE TABLE gr_free_line_item (gflineid integer primary key, grid integer, "
    "fromfreetextid integer, fromcatid integer, fromcid integer, fromcaseid integer,"
    "fromfileid integer, fromimid integer, fromavid integer, tofreetextid integer, tocatid integer, "
    "tocid integer, tocaseid integer, tofileid integer, toimid integer, toavid integer, color text,"
    "linewidth real, linetype text, label text, arrow_mode text);",
    "CREATE TABLE gr_pix_item (grpixid integer primary key, grid integer, imid integer,"
    "x integer, y integer, px integer, py integer, w integer, h integer, filepath text,"
    "tooltip text, pdf_page integer);",
    "CREATE TABLE gr_av_item (gr_avid integer primary key, grid integer, avid integer,"
    "x integer, y integer, pos0 integer, pos1 integer, filepath text, tooltip text, color text);",
    "CREATE TABLE gr_memo_item (gmemoid integer primary key, grid integer, "
    "memo_source_type text, memo_source_id integer, x integer, y integer, "
    "color text, font_size integer);",
    "CREATE TABLE ris (risid integer, tag text, longtag text, value text);",
    "CREATE TABLE manage_files_display (mfid integer primary key, name text, tblrows text, tblcolumns text, owner text);",
    "CREATE TABLE files_filter (filterid integer primary key, name text, filter text, owner text);",
    "CREATE TABLE audit_log (id integer primary key autoincrement, ts text, user text, action text, "
    "entity text, entity_id integer, source_id integer, detail text);",
    "CREATE TABLE sync_log (id integer primary key autoincrement, ts text, user text, seq integer, "
    "entity text, action text, pk_name text, pk_value text, row_json text);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_log_user_seq ON sync_log(user, seq);",
    "CREATE TABLE dictionary (id integer primary key autoincrement, name text, owner text, created text, "
    "unique(name));",
    "CREATE TABLE dictionary_entry (id integer primary key autoincrement, dict_id integer, code_name text, "
    "term text, unique(dict_id, term));",
    "CREATE TABLE qtt_sheet (id integer primary key autoincrement, name text, kind text, sections_json text, "
    "research_question text, purpose text, framework text, owner text, date text);",
    "CREATE TABLE qtt_item (id integer primary key autoincrement, sheet_id integer, section text, kind text, "
    "payload_json text, owner text, date text);",
    "CREATE TABLE code_set (id integer primary key autoincrement, name text, owner text, created text, unique(name));",
    "CREATE TABLE code_set_member (set_id integer, cid integer, primary key(set_id, cid));",
    "CREATE TABLE comment (id integer primary key autoincrement, target_kind text, target_id integer, "
    "body text, owner TEXT, created text)",
    "CREATE TABLE r_script (id integer primary key autoincrement, name text, script text, "
    "owner text, created text, updated text, unique(name))",
]

# Hot-path indexes (created for new projects; the migration chain adds the
# same set to existing projects).
_INDEX_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_source_av_text_id ON source(av_text_id)",
    "CREATE INDEX IF NOT EXISTS idx_code_text_fid ON code_text(fid)",
    "CREATE INDEX IF NOT EXISTS idx_code_text_cid ON code_text(cid)",
    "CREATE INDEX IF NOT EXISTS idx_code_image_id ON code_image(id)",
    "CREATE INDEX IF NOT EXISTS idx_code_image_cid ON code_image(cid)",
    "CREATE INDEX IF NOT EXISTS idx_code_av_id ON code_av(id)",
    "CREATE INDEX IF NOT EXISTS idx_code_av_cid ON code_av(cid)",
    "CREATE INDEX IF NOT EXISTS idx_annotation_fid ON annotation(fid)",
    "CREATE INDEX IF NOT EXISTS idx_link_from_fid ON link(from_fid)",
    "CREATE INDEX IF NOT EXISTS idx_link_to_fid ON link(to_fid)",
    "CREATE INDEX IF NOT EXISTS idx_creative_item_source_fid ON creative_item(source_fid)",
    "CREATE INDEX IF NOT EXISTS idx_qtt_item_sheet_id ON qtt_item(sheet_id)",
    "CREATE INDEX IF NOT EXISTS idx_case_text_caseid ON case_text(caseid)",
    "CREATE INDEX IF NOT EXISTS idx_case_text_fid ON case_text(fid)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_source ON audit_log(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_entity_id ON audit_log(entity, entity_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_sync_log_user ON sync_log(user)",
    "CREATE INDEX IF NOT EXISTS idx_code_cat_super ON code_cat(supercatid)",
    "CREATE INDEX IF NOT EXISTS idx_code_name_cat ON code_name(catid)",
    "CREATE INDEX IF NOT EXISTS idx_code_name_super ON code_name(supercid)",
    "CREATE INDEX IF NOT EXISTS idx_attribute_name ON attribute(name)",
    "CREATE INDEX IF NOT EXISTS idx_comment_target ON comment(target_kind, target_id)",
]

# Extra tables/views beyond the v14 core (added at project-open time).
_CODER_NAMES_SQL = """
    CREATE TABLE IF NOT EXISTS coder_names (
        name TEXT UNIQUE NOT NULL,
        visibility INTEGER NOT NULL DEFAULT 1 CHECK (visibility IN (0, 1))
    );
"""


def _visibility_view_sql(view_name: str) -> str:
    tbl = view_name.replace("_visible", "")
    return (
        f"CREATE VIEW IF NOT EXISTS {view_name} AS "
        f"SELECT t.* FROM {tbl} t WHERE NOT EXISTS ("
        f"SELECT 1 FROM coder_names c WHERE c.name = t.owner AND c.visibility = 0)"
    )


async def create_new_project_schema(
    conn: aiosqlite.Connection,
    app_version: str,
    codername: str,
) -> None:
    """Create all v14 tables and insert the initial project row."""
    if conn is None:
        return

    cur = await conn.cursor()
    for sql in _SCHEMA_SQL:
        await cur.execute(sql)
    for sql in _INDEX_SQL:
        await cur.execute(sql)
    await cur.execute(_CODER_NAMES_SQL)
    for view_name in tables.VISIBILITY_VIEWS:
        await cur.execute(_visibility_view_sql(view_name))

    await cur.execute(
        "INSERT INTO project VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "v31",
            now(),
            "",
            app_version,
            0,
            0,
            codername,
            "",
            None,
            None,
            None,
        ),
    )
    await conn.commit()


async def table_names(conn: aiosqlite.Connection) -> set[str]:
    """Return the set of user table names in the database."""
    cur = await conn.cursor()
    await cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    rows = await cur.fetchall()
    return {row[0] for row in rows}
