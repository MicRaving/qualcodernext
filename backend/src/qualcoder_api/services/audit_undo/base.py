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
from collections.abc import Callable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables

from .registry import HANDLERS


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
    "audit.undo": "Undo/redo marker rows themselves cannot be undone",
    "audit.redo": "Undo/redo marker rows themselves cannot be undone",
}

#: Per-action, per-direction detail-key requirements used by the
#: ``can_undo``/``can_redo`` predicates (and exposed via ``GET /audit/{id}/
#: undoable``) so the UI can grey out undo before a round trip. A value is
#: one of:
#:   * a list of keys — each entry is a required detail key (must be
#:     present and non-None), or a tuple of alternatives (any one present);
#:   * a string — that direction is never invertible; the string is the
#:     user-facing reason.
#: Legacy rows recorded before the undo data existed carry an empty detail,
#: so every data-dependent action must list its essential keys here or the
#: UI cannot distinguish "not undoable" from "missing legacy data".
_REQUIRED: dict[str, dict[str, object]] = {
    # --- coding / annotations ---
    "coding.create": {"undo": (("ctid", "imid", "avid"),), "redo": (("ctid", "imid", "avid"),)},
    "coding.delete": {"undo": (("ctid", "imid", "avid"),), "redo": (("ctid", "imid", "avid"),)},
    "coding.update": {"undo": ("before",), "redo": ("after",)},
    "annotation.create": {"undo": ("anid",), "redo": ("anid",)},
    "annotation.delete": {"undo": ("anid",), "redo": ("anid",)},
    "annotation.update": {"undo": ("anid", "old_memo"), "redo": ("anid", "new_memo")},
    "coding.undo": {"undo": ("items",), "redo": ("items",)},
    "code.memo": {"undo": ("old_memo",), "redo": ("memo",)},
    # --- code / category tree ---
    "code.create": {"undo": ("cid",), "redo": ("cid",)},
    "code.delete": {"undo": ("cid",), "redo": ("cid",)},
    "code.rename": {"undo": (("old_name", "before"),), "redo": (("new_name", "after"),)},
    "code.move": {"undo": ("before",), "redo": ("after",)},
    "code.promote": {"undo": ("before",), "redo": ("after",)},
    "code.demote": {"undo": ("before",), "redo": ("after",)},
    "code.merge": {"undo": ("from_cid", "from_code"), "redo": ("from_cid", "from_code")},
    "category.create": {"undo": [], "redo": ("catid",)},
    "category.delete": {"undo": ("catid",), "redo": []},
    "category.rename": {"undo": ("old_name",), "redo": ("new_name",)},
    "category.move": {"undo": ("before",), "redo": ("after",)},
    "category.promote": {"undo": ("before",), "redo": ("after",)},
    "category.demote": {"undo": ("before",), "redo": ("after",)},
    "category.merge": {"undo": ("from_catid", "from_category"), "redo": ("from_catid", "from_category")},
    # --- cases / journals ---
    "case.create": {"undo": ("caseid",), "redo": ("caseid",)},
    "case.delete": {"undo": (("caseid", "row"),), "redo": []},
    "case.update": {"undo": ("old_name",), "redo": ("new_name",)},
    "case.link_file": {"undo": [], "redo": (("row", "id"),)},
    "case.link_span": {"undo": [], "redo": (("row", "id"),)},
    "case.unlink_file": {"undo": ("rows",), "redo": ("rows",)},
    "journal.create": {"undo": ("jid",), "redo": ("jid",)},
    "journal.delete": {"undo": (("jid", "row"),), "redo": []},
    "journal.update": {"undo": ("old_name",), "redo": ("new_name",)},
    # --- attributes / links / comments ---
    "attribute.create": {"undo": [], "redo": ("name",)},
    "attribute.delete": {"undo": ("name",), "redo": []},
    "attribute.set_value": {"undo": ("after",), "redo": ("after",)},
    "link.create": {"undo": [], "redo": (("row", "id"),)},
    "link.delete": {"undo": (("row", "id"),), "redo": []},
    "comment.create": {"undo": [], "redo": (("row", "id"),)},
    "comment.update": {"undo": ("old_body",), "redo": ("new_body",)},
    "comment.delete": {"undo": (("row", "id"),), "redo": []},
    "bookmark.set": {"undo": ("before",), "redo": ("after",)},
    # --- creative ---
    "creative.create": {"undo": [], "redo": (("row", "id"),)},
    "creative.update": {"undo": ("before",), "redo": (("text", "note"),)},
    "creative.delete": {"undo": (("row", "id"),), "redo": []},
    "creative.promote": {"undo": (("code", "cid"),), "redo": ("code",)},
    # --- sources / transcripts ---
    "source.update": {"undo": (("before_name", "before_memo"),), "redo": (("after_name", "after_memo"),)},
    "source.import": {"undo": [], "redo": "import the file again"},
    "source.link": {"undo": [], "redo": "import the file again"},
    "source.delete": {"undo": ("row",), "redo": []},
    "source.link_fix": {"undo": (("rows", "old"),), "redo": (("rows", "new"),)},
    "source.replace": {"undo": ("before_source",), "redo": "upload the replacement file again"},
    "transcript.create": {"undo": [], "redo": (("companion", "row"),)},
    "transcript.delete": {"undo": (("companion", "row"),), "redo": []},
    # --- dictionaries / code sets / r scripts ---
    "dictionary.create": {"undo": [], "redo": (("row", "id"),)},
    "dictionary.update": {"undo": ("old_name",), "redo": ("new_name",)},
    "dictionary.entry_add": {"undo": [], "redo": (("row", "id"),)},
    "dictionary.entry_delete": {"undo": (("row", "id"),), "redo": []},
    "dictionary.delete": {"undo": (("row", "id"),), "redo": []},
    "dictionary.import": {"undo": ("id",), "redo": "re-import the dictionary file"},
    "code_set.create": {"undo": [], "redo": (("row", "id"),)},
    "code_set.rename": {"undo": ("old_name",), "redo": ("new_name",)},
    "code_set.delete": {"undo": (("row", "id"),), "redo": []},
    "code_set.members_add": {"undo": ("added_cids",), "redo": ("added_cids",)},
    "code_set.members_remove": {"undo": ("removed_cids",), "redo": ("removed_cids",)},
    "r_script.create": {"undo": [], "redo": (("row", "id"),)},
    "r_script.update": {"undo": ("before",), "redo": ("after",)},
    "r_script.delete": {"undo": (("row", "id"),), "redo": []},
    # --- qtt / filters / stored sql ---
    "qtt.create": {"undo": [], "redo": (("row", "id"),)},
    "qtt.delete": {"undo": (("row", "id"),), "redo": []},
    "qtt.update": {"undo": ("before",), "redo": ("after",)},
    "qtt.item.create": {"undo": [], "redo": (("row", "id"),)},
    "qtt.item.update": {"undo": ("before",), "redo": ("after",)},
    "qtt.item.delete": {"undo": (("row", "id"),), "redo": []},
    "qtt.send_segment": {"undo": [], "redo": (("row", "id"),)},
    "filter.create": {"undo": [], "redo": (("row", "filterid"),)},
    "filter.delete": {"undo": (("row", "filterid"),), "redo": []},
    "sql.save": {"undo": [], "redo": (("row", "title"),)},
    "sql.delete": {"undo": (("row", "title"),), "redo": []},
    # --- graphs ---
    "graph.create": {"undo": [], "redo": (("row", "grid"),)},
    "graph.delete": {"undo": (("row", "grid"),), "redo": []},
    "graph.update": {"undo": ("before",), "redo": ("after",)},
    "graph.item_add": {"undo": [], "redo": ("row",)},
    "graph.item_delete": {"undo": ("row",), "redo": []},
    "graph.item_update": {"undo": ("before",), "redo": ("after",)},
    "graph.line_add": {"undo": [], "redo": ("row",)},
    "graph.line_delete": {"undo": ("row",), "redo": []},
    "graph.line_update": {"undo": ("before",), "redo": ("after",)},
    # --- references ---
    "reference.delete": {"undo": ("rows",), "redo": []},
    "reference.attach": {"undo": [], "redo": (("row", "id"),)},
    "reference.detach": {"undo": ("risid",), "redo": ("risid",)},
    # --- coders / settings ---
    "coder.create": {"undo": ("name",), "redo": ("name",)},
    "coder.delete": {"undo": ("name",), "redo": ("name",)},
    "coder.rename": {"undo": ("from", "to"), "redo": ("from", "to")},
    "coder.visibility": {"undo": ("name",), "redo": ("name",)},
    "sync.toggle": {"undo": ("before",), "redo": ("enabled",)},
    "pseudonym.add": {"undo": ("original",), "redo": ("original", "pseudonym")},
    "pseudonym.delete": {"undo": ("original", "pseudonym"), "redo": ("original",)},
    # --- jobs ---
    "transcribe.start": {"undo": ("job_id",), "redo": "start the job again from the media file"},
    "r.run": {"undo": ("job_id",), "redo": "run the script again"},
    "speakers.mark": {"undo": (("created_code_ids", "created_ctids"),), "redo": "run the speaker detection again"},
    "coding.autocode": {"undo": ("text_ids",), "redo": ("created_rows",)},
}

#: Actions whose undoability also depends on values in the detail beyond mere
#: key presence. Each returns a reason string when that direction is refused,
#: else None.
_CONDITIONAL: dict[str, Callable[[dict, bool], str | None]] = {
    "coding.autocode": lambda d, _undo: (
        "background autocode jobs cannot be undone — cancel the jobs or delete the created codings manually"
        if (d.get("batch") or d.get("job_ids"))
        else "this autocode run created more than 5000 codings — delete them manually"
        if d.get("too_many")
        else None
    ),
    "speakers.mark": lambda d, _undo: (
        "this speaker run created more than 5000 codings — delete them manually"
        if d.get("too_many_codings")
        else None
    ),
}


def _detail_has(detail: dict, spec: object) -> bool:
    """True when ``detail`` satisfies a single required-key entry."""
    if isinstance(spec, str):
        return detail.get(spec) is not None
    if isinstance(spec, tuple):
        return any(detail.get(k) is not None for k in spec)
    return False


def can_undoable(
    action: str, detail: dict, *, undo: bool
) -> tuple[bool, str | None]:
    """Predicate: could ``apply`` invert this row without needing missing data?

    Returns ``(False, reason)`` when the action is never invertible in this
    direction (or a required detail key is absent — legacy row), else
    ``(True, None)``. Does NOT inspect the live database, so job-state checks
    (transcribe/r.run) stay optimistic here and are resolved at apply time.
    """
    message = _NOT_INVERTIBLE_MESSAGES.get(action)
    if message:
        return False, message
    if action not in HANDLERS:
        return False, f"no undo for {action}"
    required = _REQUIRED.get(action)
    if required is None:
        # An action with a handler but no declared requirements: optimistically
        # undoable (the handler decides at apply time).
        return True, None
    spec = required.get("redo" if not undo else "undo")
    if isinstance(spec, str):
        return False, spec
    if not isinstance(spec, (list, tuple)):
        return True, None
    if not all(_detail_has(detail, s) for s in spec):
        return False, MISSING_DATA_MESSAGE
    cond = _CONDITIONAL.get(action)
    if cond is not None:
        reason = cond(detail, undo)
        if reason:
            return False, reason
    return True, None


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
