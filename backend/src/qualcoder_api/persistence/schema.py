"""New-project schema creation — v14 tables + initial project row.

Port of the legacy ``create_new_project_schema``. Uses a raw ``aiosqlite``
connection so the SQL is byte-identical to the legacy chain.
"""

from __future__ import annotations

import datetime

import aiosqlite

from qualcoder_api.persistence import tables

_SCHEMA_SQL: list[str] = [
    "CREATE TABLE project (databaseversion text, date text, memo text,about text, bookmarkfile integer, "
    "bookmarkpos integer, codername text, recently_used_codes text, avbookmarkfile integer, "
    "avbookmarkmsec integer, avbookmarktextpos integer)",
    "CREATE TABLE source (id integer primary key, name text, fulltext text, mediapath text, memo text, "
    "owner text, date text, av_text_id integer, risid integer, unique(name))",
    "CREATE TABLE code_image (imid integer primary key,id integer,x1 integer, y1 integer, width integer, "
    "height integer, cid integer, memo text, date text, owner text, important integer, pdf_page integer)",
    "CREATE TABLE code_av (avid integer primary key,id integer,pos0 integer, pos1 integer, cid integer, "
    "memo text, date text, owner text, important integer)",
    "CREATE TABLE annotation (anid integer primary key, fid integer,pos0 integer, pos1 integer, memo text, "
    "owner text, date text, unique(fid,pos0,pos1,owner))",
    "CREATE TABLE attribute_type (name text primary key, date text, owner text, memo text, caseOrFile text, "
    "valuetype text)",
    "CREATE TABLE attribute (attrid integer primary key, name text, attr_type text, value text, id integer, "
    "date text, owner text, unique(name,attr_type,id))",
    "CREATE TABLE case_text (id integer primary key, caseid integer, fid integer, pos0 integer, pos1 integer, "
    "owner text, date text, memo text)",
    "CREATE TABLE cases (caseid integer primary key, name text, memo text, owner text,date text, "
    "constraint ucm unique(name))",
    "CREATE TABLE code_cat (catid integer primary key, name text, owner text, date text, memo text, "
    "supercatid integer, unique(name))",
    "CREATE TABLE code_text (ctid integer primary key, cid integer, fid integer,seltext text, pos0 integer, "
    "pos1 integer, owner text, date text, memo text, avid integer, important integer, "
    "unique(cid,fid,pos0,pos1, owner))",
    "CREATE TABLE code_name (cid integer primary key, name text, memo text, catid integer, owner text,"
    "date text, color text, supercid integer, unique(name))",
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
    await cur.execute(_CODER_NAMES_SQL)
    for view_name in tables.VISIBILITY_VIEWS:
        await cur.execute(_visibility_view_sql(view_name))

    await cur.execute(
        "INSERT INTO project VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "v18",
            datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
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
