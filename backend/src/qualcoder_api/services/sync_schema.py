"""Sync schema — constants, entity sets, PK helpers, export order.

Pure data and simple helpers with no I/O or async.  Every other sync
submodule imports from here; nothing imports *from* sync_schema's
dependents, so the dependency arrow is one-way.
"""

from __future__ import annotations

import asyncio
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────

SYNC_DIR_NAME = "changes"
SYNC_INTERVAL_SECS = 60
SYNC_LOCK = asyncio.Lock()
SIDECAR_PRUNE_AFTER_SECS = 86400  # prune sidecars from instances offline >24h

# Cleanup thresholds for sidecar compaction.
SIDECAR_COMPACT_THRESHOLD_ENTRIES = 10_000
SIDECAR_COMPACT_THRESHOLD_BYTES = 2 * 1024 * 1024

# ── Entity registry ──────────────────────────────────────────────────────

# Tables whose rows travel through the sidecar change log.
SYNC_ENTITIES = {
    "project", "source", "code_name", "code_cat", "code_text", "code_image",
    "code_av", "annotation", "cases", "case_text", "attribute_type",
    "attribute", "journal", "stored_sql", "files_filter",
    "graph", "gr_cdct_text_item", "gr_case_text_item", "gr_file_text_item",
    "gr_free_text_item", "gr_memo_item", "gr_cdct_line_item",
    "gr_free_line_item", "gr_pix_item", "gr_av_item",
    "link", "dictionary", "dictionary_entry", "qtt_sheet", "qtt_item",
    "creative_item", "comment", "code_set", "code_set_member", "r_script",
}

# Natural (business) keys — the columns that identify the SAME logical row
# across instances even when their autoincrement PKs diverge (every instance
# starts its counters at 1, so two independently created rows collide).  These
# mirror the schema's UNIQUE constraints.  Replay matches by natural key FIRST
# and only falls back to PK for tables without one.
NATURAL_KEYS: dict[str, list[str]] = {
    "source": ["name"],
    "annotation": ["fid", "pos0", "pos1", "owner"],
    "attribute": ["name", "attr_type", "id"],
    "cases": ["name"],
    "code_cat": ["name"],
    "code_text": ["cid", "fid", "pos0", "pos1", "owner"],
    "code_name": ["name"],
    "journal": ["name"],
    "stored_sql": ["title"],
    "r_script": ["name"],
    "graph": ["name"],
    "dictionary": ["name"],
    "dictionary_entry": ["dict_id", "term"],
    "code_set": ["name"],
    # Composite-PK table: the pair (set_id, cid) is both the natural key and
    # the primary key.  FK translation normalises the values to local ids
    # before matching, so it is safe to treat both columns as natural.
    "code_set_member": ["set_id", "cid"],
}

# Foreign-key columns: ``column`` on a row stores the autoincrement PK of
# ``referenced entity``.  Because those PKs diverge between instances too, an
# incoming row's FK values must be translated (remote PK -> local PK) before
# it can be matched by natural key or inserted.  The special value
# "case_or_source" means the column refers to either ``cases`` or ``source``
# depending on the row's ``attr_type`` ("case" vs "file").
FK_REFERENCES: dict[str, dict[str, str]] = {
    "code_text": {"cid": "code_name", "fid": "source", "avid": "code_av"},
    "code_image": {"cid": "code_name", "id": "source"},
    "code_av": {"cid": "code_name", "id": "source"},
    "annotation": {"fid": "source"},
    "attribute": {"id": "case_or_source"},
    "case_text": {"caseid": "cases", "fid": "source"},
    "code_name": {"catid": "code_cat", "supercid": "code_name"},
    "code_cat": {"supercatid": "code_cat"},
    "dictionary_entry": {"dict_id": "dictionary"},
    "code_set_member": {"set_id": "code_set", "cid": "code_name"},
    "link": {"from_fid": "source", "to_fid": "source"},
    "creative_item": {"source_fid": "source"},
    "gr_cdct_text_item": {"grid": "graph", "supercatid": "code_cat", "catid": "code_cat", "cid": "code_name"},
    "gr_case_text_item": {"grid": "graph", "caseid": "cases"},
    "gr_file_text_item": {"grid": "graph", "fid": "source"},
    "gr_free_text_item": {"grid": "graph", "ctid": "code_text", "memo_ctid": "code_text", "memo_imid": "code_image", "memo_avid": "code_av"},
    "gr_pix_item": {"grid": "graph", "imid": "code_image"},
    "gr_av_item": {"grid": "graph", "avid": "code_av"},
    "gr_memo_item": {"grid": "graph"},
    "qtt_item": {"sheet_id": "qtt_sheet"},
}

# Primary-key column per synced entity.
ENTITY_PKS: dict[str, str] = {
    "project": "rowid",
    "source": "id",
    "code_name": "cid",
    "code_cat": "catid",
    "code_text": "ctid",
    "code_image": "imid",
    "code_av": "avid",
    "annotation": "anid",
    "cases": "caseid",
    "case_text": "id",
    "attribute_type": "name",
    "attribute": "attrid",
    "journal": "jid",
    "stored_sql": "title",
    "files_filter": "filterid",
    "graph": "grid",
    "gr_cdct_text_item": "gtextid",
    "gr_case_text_item": "gcaseid",
    "gr_file_text_item": "gfileid",
    "gr_free_text_item": "gfreeid",
    "gr_memo_item": "gmemoid",
    "gr_cdct_line_item": "glineid",
    "gr_free_line_item": "gflineid",
    "gr_pix_item": "grpixid",
    "gr_av_item": "gr_avid",
    "link": "id",
    "dictionary": "id",
    "dictionary_entry": "id",
    "qtt_sheet": "id",
    "qtt_item": "id",
    "creative_item": "id",
    "comment": "id",
    "code_set": "id",
    "code_set_member": "set_id,cid",
    "r_script": "id",
}

# Dependency-ordered export/rebuild sequence: parent tables come before the
# tables that reference them (via FK_REFERENCES), so FK translation on the
# receiving side always has a recorded remap for the referenced row.
EXPORT_ORDER: list[str] = [
    "project",
    "source",
    "cases",
    "code_cat",
    "code_name",
    "attribute_type",
    "code_image",
    "code_av",
    "code_text",
    "annotation",
    "attribute",
    "case_text",
    "journal",
    "stored_sql",
    "files_filter",
    "graph",
    "gr_memo_item",
    "gr_cdct_text_item",
    "gr_case_text_item",
    "gr_file_text_item",
    "gr_free_text_item",
    "gr_pix_item",
    "gr_av_item",
    "gr_cdct_line_item",
    "gr_free_line_item",
    "dictionary",
    "dictionary_entry",
    "qtt_sheet",
    "qtt_item",
    "link",
    "creative_item",
    "comment",
    "code_set",
    "code_set_member",
    "r_script",
]

# ── PK helpers ───────────────────────────────────────────────────────────


def _pk_cols(pk_name: str) -> list[str]:
    """The column(s) that make up a primary key (composite = comma-joined)."""
    if not pk_name:
        return []
    return [c.strip() for c in pk_name.split(",")]


def _as_pk(value: Any) -> int | str:
    """Coerce a sidecar PK to int when it looks numeric."""
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        return int(value)
    return str(value)


def _pk_values(pk_name: str, pk_value: Any) -> list[Any]:
    """Split a pk_value back into per-column values (composite = ":"-joined)."""
    cols = _pk_cols(pk_name)
    if len(cols) <= 1:
        return [_as_pk(pk_value)]
    return [_as_pk(p) for p in str(pk_value).split(":")]


def _row_pk(pk_name: str, row: dict) -> Any:
    """The pk_value (single value, or composite ":"-joined) for a row dict."""
    cols = _pk_cols(pk_name)
    if len(cols) == 1:
        return row.get(pk_name)
    return ":".join(str(row.get(c, "")) for c in cols)


def _pk_where(pk_name: str, alias: str = "pk") -> tuple[str, list[str]]:
    """A ``WHERE`` clause matching all PK columns plus its bind parameter names."""
    cols = _pk_cols(pk_name)
    if len(cols) == 1:
        return f"{cols[0]} = :{alias}", [alias]
    params = [f"{alias}_{i}" for i in range(len(cols))]
    return " AND ".join(f"{c} = :{p}" for c, p in zip(cols, params, strict=True)), params
