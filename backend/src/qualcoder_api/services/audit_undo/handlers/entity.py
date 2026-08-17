"""Core case / journal / annotation update handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _ensure,
    _insert_row,
    _missing_data,
    _sync_capture,
)
from ..registry import register


@register("case.create", "journal.create")
async def _revert_entity_create(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """case.create / journal.create."""
    action = row.get("action") or ""
    detail = _detail(row)
    if action == "case.create":
        table, pk = "cases", "caseid"
    elif action == "journal.create":
        table, pk = "journal", "jid"
    else:
        raise UnsupportedAction(f"no undo for {action}")
    row_id = _ensure(detail, pk)
    if undo:
        await _delete_by_id(session, table, pk, row_id)
        if table == "cases":
            # Do not orphan the case-file links created with the case.
            await session.execute(text("DELETE FROM case_text WHERE caseid = :v"), {"v": row_id})
            await session.execute(
                text("DELETE FROM attribute WHERE attr_type = 'case' AND id = :v"),
                {"v": row_id},
            )
        return f"deleted {table} #{row_id}"
    await _insert_row(session, table, detail)
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


@register("case.delete", "journal.delete")
async def _revert_entity_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """case.delete / journal.delete: re-insert the row (undo) or delete it
    again (redo, mirroring the repository's delete path)."""
    action = row.get("action") or ""
    detail = _detail(row)
    if action == "case.delete":
        table, pk = "cases", "caseid"
    elif action == "journal.delete":
        table, pk = "journal", "jid"
    else:
        raise UnsupportedAction(f"no undo for {action}")
    row_id = row.get("entity_id")
    if not row_id:
        raise _missing_data()
    if not undo:
        if table == "cases":
            await session.execute(text("DELETE FROM case_text WHERE caseid = :v"), {"v": row_id})
            await session.execute(
                text("DELETE FROM attribute WHERE attr_type = 'case' AND id = :v"),
                {"v": row_id},
            )
        await _delete_by_id(session, table, pk, row_id)
        return f"deleted {table} #{row_id}"
    row_dict = detail.get("row") or detail
    if not isinstance(row_dict, dict) or not row_dict.get(pk):
        raise _missing_data()
    try:
        await _insert_row(session, table, row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore {table} #{row_id}: {err}") from err
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


@register("annotation.update", "journal.update", "case.update")
async def _revert_update(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """annotation.update / journal.update / case.update: restore the
    pre-edit values recorded in the detail."""
    action = row.get("action") or ""
    detail = _detail(row)
    if action == "annotation.update":
        anid = _ensure(detail, "anid")
        memo = detail.get("old_memo") if undo else detail.get("new_memo")
        pos0 = detail.get("old_pos0") if undo else detail.get("new_pos0")
        pos1 = detail.get("old_pos1") if undo else detail.get("new_pos1")
        sets = "memo = :m"
        params = {"m": memo, "id": anid}
        if pos0 is not None:
            sets += ", pos0 = :p0"
            params["p0"] = pos0
        if pos1 is not None:
            sets += ", pos1 = :p1"
            params["p1"] = pos1
        await session.execute(text(f"UPDATE annotation SET {sets} WHERE anid = :id"), params)
        await _sync_capture(session, "annotation", "update", "anid", anid)
        return f"annotation #{anid} {'restored' if undo else 're-applied'}"
    if action == "journal.update":
        jid = _ensure(detail, "jid")
        name = detail.get("old_name") if undo else detail.get("new_name")
        jentry = detail.get("old_jentry") if undo else detail.get("new_jentry")
        await session.execute(
            text("UPDATE journal SET name = :n, jentry = :j WHERE jid = :id"),
            {"n": name, "j": jentry, "id": jid},
        )
        await _sync_capture(session, "journal", "update", "jid", jid)
        return f"journal #{jid} {'restored' if undo else 're-applied'}"
    if action == "case.update":
        caseid = _ensure(detail, "caseid")
        name = detail.get("old_name") if undo else detail.get("new_name")
        memo = detail.get("old_memo") if undo else detail.get("new_memo")
        await session.execute(
            text("UPDATE cases SET name = :n, memo = :m WHERE caseid = :id"),
            {"n": name, "m": memo, "id": caseid},
        )
        await _sync_capture(session, "cases", "update", "caseid", caseid)
        return f"case #{caseid} {'restored' if undo else 're-applied'}"
    raise UnsupportedAction(f"no undo for {action}")
