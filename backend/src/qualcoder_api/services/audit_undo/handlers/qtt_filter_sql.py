"""QTT sheet / QTT item / filter / stored SQL handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _insert_row,
    _missing_data,
    _revert_row_pair,
    _revert_row_update,
    _sync_capture,
)
from ..registry import register


@register("qtt.create")
async def _revert_qtt_sheet_create(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """qtt.create: remove the worksheet (and its items) or restore it."""
    detail = _detail(row)
    sheet_id = row.get("entity_id")
    if not sheet_id:
        raise _missing_data()
    if undo:
        await session.execute(text("DELETE FROM qtt_item WHERE sheet_id = :v"), {"v": sheet_id})
        await _delete_by_id(session, "qtt_sheet", "id", sheet_id)
        return f"deleted worksheet #{sheet_id}"
    row_dict = detail.get("row")
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise _missing_data()
    try:
        await _insert_row(session, "qtt_sheet", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore worksheet #{sheet_id}: {err}") from err
    await _sync_capture(session, "qtt_sheet", "insert", "id", sheet_id)
    return f"restored worksheet #{sheet_id}"


@register("qtt.delete")
async def _revert_qtt_sheet_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """qtt.delete: restore the worksheet plus its items (undo) or remove them
    again (redo)."""
    detail = _detail(row)
    sheet_id = row.get("entity_id")
    if not sheet_id:
        raise _missing_data()
    if undo:
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("id"):
            raise _missing_data()
        try:
            await _insert_row(session, "qtt_sheet", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore worksheet #{sheet_id}: {err}") from err
        await _sync_capture(session, "qtt_sheet", "insert", "id", sheet_id)
        for item in detail.get("items") or []:
            try:
                await _insert_row(session, "qtt_item", item)
            except Exception as err:
                raise UnsupportedAction(f"cannot restore worksheet item: {err}") from err
        return f"restored worksheet #{sheet_id} with its items"
    await session.execute(text("DELETE FROM qtt_item WHERE sheet_id = :v"), {"v": sheet_id})
    await _delete_by_id(session, "qtt_sheet", "id", sheet_id)
    return f"deleted worksheet #{sheet_id}"


@register("qtt.item.create", "qtt.item.delete", "qtt.send_segment")
async def _revert_qtt_item(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """QTT item create/delete/send_segment: generic single-row inversion."""
    return await _revert_row_pair(
        session, row, undo=undo, table="qtt_item", pk="id",
        create_actions=("qtt.item.create", "qtt.send_segment"),
        delete_actions=("qtt.item.delete",),
    )


@register("qtt.update", "qtt.item.update")
async def _revert_qtt_update(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """QTT sheet/item updates: generic before/after row inversion."""
    action = row.get("action") or ""
    table = "qtt_sheet" if action == "qtt.update" else "qtt_item"
    return await _revert_row_update(session, row, undo=undo, table=table, pk="id")


@register("filter.create", "filter.delete")
async def _revert_filter(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """files_filter create/delete: generic single-row inversion."""
    return await _revert_row_pair(
        session, row, undo=undo, table="files_filter", pk="filterid",
        create_actions=("filter.create",), delete_actions=("filter.delete",),
    )


@register("sql.save", "sql.delete")
async def _revert_sql(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """stored_sql save/delete: generic single-row inversion."""
    return await _revert_row_pair(
        session, row, undo=undo, table="stored_sql", pk="title",
        create_actions=("sql.save",), delete_actions=("sql.delete",),
    )
