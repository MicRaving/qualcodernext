"""SQLAlchemy 2.0 table definitions matching the legacy v14 SQLite schema.

Column names, types and constraints mirror ``create_new_project_schema``
from the v3/v4 codebase byte-for-byte so that existing ``.qda`` files keep
working. Foreign keys are deliberately absent (the legacy schema never used
them; enforcement would break legacy data).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

metadata = MetaData()

project = Table(
    "project",
    metadata,
    Column("databaseversion", String),
    Column("date", String),
    Column("memo", Text),
    Column("about", Text),
    Column("bookmarkfile", Integer),
    Column("bookmarkpos", Integer),
    Column("codername", String),
    Column("recently_used_codes", String),
    Column("avbookmarkfile", Integer),
    Column("avbookmarkmsec", Integer),
    Column("avbookmarktextpos", Integer),
)

source = Table(
    "source",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False, unique=True),
    Column("fulltext", Text),
    Column("mediapath", String),
    Column("memo", Text),
    Column("owner", String),
    Column("date", String),
    Column("av_text_id", Integer),
    Column("risid", Integer),
)

code_image = Table(
    "code_image",
    metadata,
    Column("imid", Integer, primary_key=True, autoincrement=True),
    Column("id", Integer),
    Column("x1", Integer),
    Column("y1", Integer),
    Column("width", Integer),
    Column("height", Integer),
    Column("cid", Integer),
    Column("memo", Text),
    Column("date", String),
    Column("owner", String),
    Column("important", Integer),
    Column("pdf_page", Integer),
)

code_av = Table(
    "code_av",
    metadata,
    Column("avid", Integer, primary_key=True, autoincrement=True),
    Column("id", Integer),
    Column("pos0", Integer),
    Column("pos1", Integer),
    Column("cid", Integer),
    Column("memo", Text),
    Column("date", String),
    Column("owner", String),
    Column("important", Integer),
)

annotation = Table(
    "annotation",
    metadata,
    Column("anid", Integer, primary_key=True, autoincrement=True),
    Column("fid", Integer),
    Column("pos0", Integer),
    Column("pos1", Integer),
    Column("memo", Text),
    Column("owner", String),
    Column("date", String),
    UniqueConstraint("fid", "pos0", "pos1", "owner", name="u_annotation"),
)

link = Table(
    "link",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("from_fid", Integer),
    Column("from_pos0", Integer),
    Column("from_pos1", Integer),
    Column("to_fid", Integer),
    Column("to_pos0", Integer),
    Column("to_pos1", Integer),
    Column("memo", Text),
    Column("owner", String),
    Column("date", String),
)

creative_item = Table(
    "creative_item",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("text", Text),
    Column("source_fid", Integer),
    Column("pos0", Integer),
    Column("pos1", Integer),
    Column("note", Text),
    Column("owner", String),
    Column("date", String),
)

attribute_type = Table(
    "attribute_type",
    metadata,
    Column("name", String, primary_key=True),
    Column("date", String),
    Column("owner", String),
    Column("memo", Text),
    Column("caseOrFile", String),
    Column("valuetype", String),
    Column("value_labels", Text),
)

attribute = Table(
    "attribute",
    metadata,
    Column("attrid", Integer, primary_key=True, autoincrement=True),
    Column("name", String),
    Column("attr_type", String),
    Column("value", Text),
    Column("id", Integer),
    Column("date", String),
    Column("owner", String),
    UniqueConstraint("name", "attr_type", "id", name="u_attribute"),
)

case_text = Table(
    "case_text",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("caseid", Integer),
    Column("fid", Integer),
    Column("pos0", Integer),
    Column("pos1", Integer),
    Column("owner", String),
    Column("date", String),
    Column("memo", Text),
)

cases = Table(
    "cases",
    metadata,
    Column("caseid", Integer, primary_key=True, autoincrement=True),
    Column("name", String, unique=True, nullable=False),
    Column("memo", Text),
    Column("owner", String),
    Column("date", String),
)

code_cat = Table(
    "code_cat",
    metadata,
    Column("catid", Integer, primary_key=True, autoincrement=True),
    Column("name", String, unique=True, nullable=False),
    Column("owner", String),
    Column("date", String),
    Column("memo", Text),
    Column("supercatid", Integer),
)

code_text = Table(
    "code_text",
    metadata,
    Column("ctid", Integer, primary_key=True, autoincrement=True),
    Column("cid", Integer),
    Column("fid", Integer),
    Column("seltext", Text),
    Column("pos0", Integer),
    Column("pos1", Integer),
    Column("owner", String),
    Column("date", String),
    Column("memo", Text),
    Column("avid", Integer),
    Column("important", Integer),
    UniqueConstraint("cid", "fid", "pos0", "pos1", "owner", name="u_code_text"),
)

code_name = Table(
    "code_name",
    metadata,
    Column("cid", Integer, primary_key=True, autoincrement=True),
    Column("name", String, unique=True, nullable=False),
    Column("memo", Text),
    Column("catid", Integer),
    Column("owner", String),
    Column("date", String),
    Column("color", String),
    Column("supercid", Integer),
)

journal = Table(
    "journal",
    metadata,
    Column("jid", Integer, primary_key=True, autoincrement=True),
    Column("name", String, unique=True, nullable=False),
    Column("jentry", Text),
    Column("date", String),
    Column("owner", String),
)

stored_sql = Table(
    "stored_sql",
    metadata,
    Column("title", String, unique=True),
    Column("description", Text),
    Column("grouper", String),
    Column("ssql", Text),
)

graph = Table(
    "graph",
    metadata,
    Column("grid", Integer, primary_key=True, autoincrement=True),
    Column("name", String, unique=True, nullable=False),
    Column("description", Text),
    Column("date", String),
    Column("scene_width", Integer),
    Column("scene_height", Integer),
)

gr_cdct_text_item = Table(
    "gr_cdct_text_item",
    metadata,
    Column("gtextid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("x", Integer),
    Column("y", Integer),
    Column("supercatid", Integer),
    Column("catid", Integer),
    Column("cid", Integer),
    Column("font_size", Integer),
    Column("bold", Integer),
    Column("isvisible", Integer),
    Column("displaytext", Text),
)

gr_case_text_item = Table(
    "gr_case_text_item",
    metadata,
    Column("gcaseid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("x", Integer),
    Column("y", Integer),
    Column("caseid", Integer),
    Column("font_size", Integer),
    Column("bold", Integer),
    Column("color", String),
    Column("displaytext", Text),
)

gr_file_text_item = Table(
    "gr_file_text_item",
    metadata,
    Column("gfileid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("x", Integer),
    Column("y", Integer),
    Column("fid", Integer),
    Column("font_size", Integer),
    Column("bold", Integer),
    Column("color", String),
    Column("displaytext", Text),
)

gr_free_text_item = Table(
    "gr_free_text_item",
    metadata,
    Column("gfreeid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("freetextid", Integer),
    Column("x", Integer),
    Column("y", Integer),
    Column("free_text", Text),
    Column("font_size", Integer),
    Column("bold", Integer),
    Column("color", String),
    Column("tooltip", Text),
    Column("ctid", Integer),
    Column("memo_ctid", Integer),
    Column("memo_imid", Integer),
    Column("memo_avid", Integer),
)

gr_cdct_line_item = Table(
    "gr_cdct_line_item",
    metadata,
    Column("glineid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("fromcatid", Integer),
    Column("fromcid", Integer),
    Column("tocatid", Integer),
    Column("tocid", Integer),
    Column("color", String),
    Column("linewidth", Integer),  # legacy: REAL, keep as float-tolerant
    Column("linetype", String),
    Column("isvisible", Integer),
    Column("label", String),
    Column("arrow_mode", String),
)

gr_free_line_item = Table(
    "gr_free_line_item",
    metadata,
    Column("gflineid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("fromfreetextid", Integer),
    Column("fromcatid", Integer),
    Column("fromcid", Integer),
    Column("fromcaseid", Integer),
    Column("fromfileid", Integer),
    Column("fromimid", Integer),
    Column("fromavid", Integer),
    Column("tofreetextid", Integer),
    Column("tocatid", Integer),
    Column("tocid", Integer),
    Column("tocaseid", Integer),
    Column("tofileid", Integer),
    Column("toimid", Integer),
    Column("toavid", Integer),
    Column("color", String),
    Column("linewidth", Integer),
    Column("linetype", String),
    Column("label", String),
    Column("arrow_mode", String),
)

gr_memo_item = Table(
    "gr_memo_item",
    metadata,
    Column("gmemoid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("memo_source_type", String),
    Column("memo_source_id", Integer),
    Column("x", Integer),
    Column("y", Integer),
    Column("color", String),
    Column("font_size", Integer),
)

gr_pix_item = Table(
    "gr_pix_item",
    metadata,
    Column("grpixid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("imid", Integer),
    Column("x", Integer),
    Column("y", Integer),
    Column("px", Integer),
    Column("py", Integer),
    Column("w", Integer),
    Column("h", Integer),
    Column("filepath", Text),
    Column("tooltip", Text),
    Column("pdf_page", Integer),
)

gr_av_item = Table(
    "gr_av_item",
    metadata,
    Column("gr_avid", Integer, primary_key=True, autoincrement=True),
    Column("grid", Integer),
    Column("avid", Integer),
    Column("x", Integer),
    Column("y", Integer),
    Column("pos0", Integer),
    Column("pos1", Integer),
    Column("filepath", Text),
    Column("tooltip", Text),
    Column("color", String),
)

ris = Table(
    "ris",
    metadata,
    Column("risid", Integer),
    Column("tag", String),
    Column("longtag", String),
    Column("value", Text),
)

manage_files_display = Table(
    "manage_files_display",
    metadata,
    Column("mfid", Integer, primary_key=True, autoincrement=True),
    Column("name", String),
    Column("tblrows", Text),
    Column("tblcolumns", Text),
    Column("owner", String),
)

files_filter = Table(
    "files_filter",
    metadata,
    Column("filterid", Integer, primary_key=True, autoincrement=True),
    Column("name", String),
    Column("filter", Text),
    Column("owner", String),
)

coder_names = Table(
    "coder_names",
    metadata,
    Column("name", String, unique=True, nullable=False),
    Column(
        "visibility",
        Boolean,
        nullable=False,
        server_default=text("1"),
        default=True,
    ),
)

sync_log = Table(
    "sync_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", String),
    Column("user", String),
    Column("seq", Integer),  # per-user monotonic counter (used by importers)
    Column("entity", String),  # table name
    Column("action", String),  # insert | update | delete
    Column("pk_name", String),
    Column("pk_value", String),  # primary key value (int or name string)
    Column("row_json", Text),  # full row snapshot (JSON)
)

audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", String),
    Column("user", String),
    Column("action", String),
    Column("entity", String),
    Column("entity_id", Integer),
    Column("source_id", Integer),
    Column("detail", Text),
)

dictionary = Table(
    "dictionary",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("owner", String),
    Column("created", String),
    UniqueConstraint("name", name="u_dictionary_name"),
)

dictionary_entry = Table(
    "dictionary_entry",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dict_id", Integer, nullable=False),
    Column("code_name", String, nullable=False),
    Column("term", String, nullable=False),
    UniqueConstraint("dict_id", "term", name="u_dictionary_entry_term"),
)

qtt_sheet = Table(
    "qtt_sheet",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    # "qual" | "mixed" — mixed worksheets seed the Creswell 14-step sections.
    Column("kind", String, nullable=False),
    # JSON array of section names (authoritative order).
    Column("sections_json", Text, nullable=False),
    Column("research_question", Text),
    Column("purpose", Text),
    Column("framework", Text),
    Column("owner", String),
    Column("date", String),
)

qtt_item = Table(
    "qtt_item",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sheet_id", Integer, nullable=False),
    # Section NAME the item lives in (must be one of the sheet's sections).
    Column("section", String, nullable=False),
    # "segment" | "note" | "chart" | "link"
    Column("kind", String, nullable=False),
    # JSON payload: {fid,pos0,pos1,text} segments, {text} notes,
    # {report,params} charts, {url} links.
    Column("payload_json", Text, nullable=False),
    Column("owner", String),
    Column("date", String),
)

# Tables whose `owner` column feeds the coder_names table.
OWNER_TABLES = [
    "code_image",
    "code_text",
    "code_av",
    "code_name",
    "code_cat",
    "cases",
    "case_text",
    "attribute",
    "attribute_type",
    "source",
    "annotation",
    "link",
    "creative_item",
    "qtt_sheet",
    "qtt_item",
    "journal",
    "manage_files_display",
    "files_filter",
]

# Visibility views over the coding/annotation tables.
VISIBILITY_VIEWS = (
    "code_image_visible",
    "code_text_visible",
    "code_av_visible",
    "annotation_visible",
)

# system coder name from the legacy speakers module
SYSTEM_CODER_NAME = "system"
