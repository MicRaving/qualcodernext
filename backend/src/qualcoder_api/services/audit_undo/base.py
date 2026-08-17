"""Shared helpers and constants for the audit undo/redo handlers.

Each supported action records enough detail to invert itself: full rows
for coding/annotation inserts and deletes, before/after text for edits,
old/new names for renames, before/after row snapshots for updates and
tree moves, full rows + captured children for merges, transcript
companions, source deletes/replaces, and the row-based families
(filters, stored SQL, dictionaries, code sets, R scripts, QTT sheets and
items, graph nodes/lines, references, coders, bookmarks, pseudonyms,
speaker marks and sync toggles). ``undo`` applies the inverse; ``redo``
applies the inverse of the inverse (i.e. re-applies the original change).

Unsupported actions raise ``UnsupportedAction`` — the UI hides the undo
button for those. Interchange/scrape imports, compaction, report-data
preparation and finished background jobs are deliberately not
invertible; the raised message says why instead of a bare "no undo".
"""
from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables


class UnsupportedAction(Exception):
    pass


#: Rows recorded before the undo service captured enough detail (legacy
#: projects) cannot be inverted automatically. Keep this message stable —
#: tests and the frontend rely on it.
MISSING_DATA_MESSAGE = (
    "This action was recorded before its undo data was available — it "
    "cannot be undone automatically; delete/adjust the affected rows manually."
)


def _missing_data() -> UnsupportedAction:
    return UnsupportedAction(MISSING_DATA_MESSAGE)


def _detail(row: dict) -> dict:
    d = row.get("detail")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except json.JSONDecodeError:
            d = {}
    return dict(d or {})


def _ensure(detail: dict, key: str):
    if detail.get(key) is None:
        raise _missing_data()
    return detail[key]


async def _sync_capture(session: AsyncSession, entity: str, action: str, pk: str, pk_value) -> None:
    """Capture the current state of one row after an undo/redo write."""
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    table = getattr(tables, entity, None)
    if table is None:
        return
    row = (await session.execute(select(table).where(table.c[pk] == pk_value))).first()
    if row is not None:
        await _capture(session, entity, action, pk, pk_value, _rowdict(row))
    await session.flush()


async def _insert_row(session: AsyncSession, table: str, row: dict) -> None:
    cols = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row)
    await session.execute(
        text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), row
    )


async def _delete_by_id(session: AsyncSession, table: str, pk: str, value) -> None:
    await session.execute(text(f"DELETE FROM {table} WHERE {pk} = :v"), {"v": value})


async def _update_row(session: AsyncSession, table: str, pk: str, pk_value, values: dict) -> None:
    """UPDATE all columns of ``values`` (except the pk) for one row."""
    cols = {k: v for k, v in values.items() if k != pk}
    if not cols:
        return
    assignments = ", ".join(f"{k} = :{k}" for k in cols)
    await session.execute(
        text(f"UPDATE {table} SET {assignments} WHERE {pk} = :pk"),
        {**cols, "pk": pk_value},
    )


def _in_params(ids: list) -> tuple[str, dict]:
    """Named-parameter placeholders for an ``IN (...)`` clause plus params."""
    return (
        ", ".join(f":in{i}" for i in range(len(ids))),
        {f"in{i}": v for i, v in enumerate(ids)},
    )


async def _restore_row(session: AsyncSession, table: str, pk: str, row_dict: dict) -> str:
    """Update the row by pk when it still exists, else insert it back.

    Returns the sync action actually performed ("update" or "insert").
    """
    existing = (
        await session.execute(
            text(f"SELECT {pk} FROM {table} WHERE {pk} = :v"), {"v": row_dict.get(pk)}
        )
    ).first()
    if existing is not None:
        await _update_row(session, table, pk, row_dict.get(pk), row_dict)
        return "update"
    await _insert_row(session, table, row_dict)
    return "insert"


def _coding_table_for(row: dict) -> tuple[str, str]:
    if "ctid" in row:
        return "code_text", "ctid"
    if "avid" in row:
        return "code_av", "avid"
    if "imid" in row:
        return "code_image", "imid"
    raise _missing_data()


def _coding_defaults(row: dict) -> dict:
    """A code_text row with the NOT NULL-ish model fields defaulted (the
    autocode/speaker engines create rows without weight)."""
    out = dict(row)
    out.setdefault("weight", 0)
    out.setdefault("important", 0)
    return out


#: The graph item/line tables and their primary keys (row-pair inversion).
_GRAPH_PKS = {
    "gr_cdct_text_item": "gtextid",
    "gr_case_text_item": "gcaseid",
    "gr_file_text_item": "gfileid",
    "gr_memo_item": "gmemoid",
    "gr_cdct_line_item": "glineid",
    "gr_free_line_item": "gflineid",
}

_GRAPH_CHILD_TABLES = (
    "gr_cdct_text_item",
    "gr_case_text_item",
    "gr_file_text_item",
    "gr_free_text_item",
    "gr_memo_item",
    "gr_cdct_line_item",
    "gr_free_line_item",
)

#: Actions that record a single audit row for an unbounded set of created
#: rows. They stay unsupported on purpose — the message says so instead of
#: a bare "no undo".
_NOT_INVERTIBLE_MESSAGES = {
    "interchange.import": "Import actions cannot be undone — delete the affected rows manually",
    "scrape.import": "Import actions cannot be undone — delete the affected rows manually",
    "project.compact": "Compaction cannot be undone — the database was rebuilt (checkpoint + VACUUM)",
    "r_script.prepare_report": "Report data was written to r_exchange/in — delete those files manually",
}


async def _revert_row_pair(
    session: AsyncSession,
    row: dict,
    *,
    undo: bool,
    table: str,
    pk: str,
    create_actions: tuple[str, ...],
    delete_actions: tuple[str, ...] = (),
) -> str:
    """Generic create/delete inversion for single-row entities: the detail
    carries the full ``row``, the audit row's ``entity_id`` (or the row's own
    pk) identifies it. Undo of a create deletes the row; undo of a delete
    re-inserts it."""
    action = row.get("action") or ""
    detail = _detail(row)
    row_dict = detail.get("row")
    if row_dict is None and detail.get(pk) is not None:
        # Some actions record the row as the whole detail (e.g.
        # dictionary.entry_add, r_script.delete).
        row_dict = detail
    row_id = row.get("entity_id")
    if row_id is None and isinstance(row_dict, dict):
        row_id = row_dict.get(pk)
    if row_id is None:
        raise _missing_data()
    if (action in create_actions) == undo:
        await _delete_by_id(session, table, pk, row_id)
        return f"deleted {table} #{row_id}"
    if not isinstance(row_dict, dict) or not row_dict.get(pk):
        raise _missing_data()
    try:
        await _insert_row(session, table, row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore {table} #{row_id}: {err}") from err
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


async def _revert_row_update(
    session: AsyncSession, row: dict, *, undo: bool, table: str, pk: str
) -> str:
    """Generic update inversion: the detail carries full ``before``/``after``
    rows; undo restores the before state, redo re-applies the after state."""
    detail = _detail(row)
    target = detail.get("before") if undo else detail.get("after")
    if not isinstance(target, dict):
        raise _missing_data()
    pk_value = target.get(pk) or row.get("entity_id")
    if pk_value is None:
        raise _missing_data()
    await _update_row(session, table, pk, pk_value, target)
    await _sync_capture(session, table, "update", pk, pk_value)
    return f"{table} #{pk_value} {'restored' if undo else 're-applied'}"
