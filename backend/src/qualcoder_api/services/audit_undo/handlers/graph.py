"""Graph create/delete/item/line handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    _GRAPH_CHILD_TABLES,
    _GRAPH_PKS,
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _insert_row,
    _missing_data,
    _revert_row_update,
    _sync_capture,
)
from ..registry import register


async def _delete_graph_rows(session: AsyncSession, grid: int) -> None:
    for table in _GRAPH_CHILD_TABLES:
        await session.execute(text(f"DELETE FROM {table} WHERE grid = :v"), {"v": grid})


@register("graph.create")
async def _revert_graph_create(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """graph.create (manual or model-generated): remove the whole graph on
    undo; restore the graph row on redo (model graphs are not redoable)."""
    detail = _detail(row)
    grid = row.get("entity_id")
    if not grid:
        raise _missing_data()
    if undo:
        await _delete_graph_rows(session, grid)
        await _delete_by_id(session, "graph", "grid", grid)
        return f"deleted graph #{grid} and its items/lines"
    if detail.get("model"):
        raise UnsupportedAction("cannot redo a model-generated graph — run the model generator again")
    row_dict = detail.get("row")
    if not isinstance(row_dict, dict) or not row_dict.get("grid"):
        raise _missing_data()
    try:
        await _insert_row(session, "graph", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore graph #{grid}: {err}") from err
    await _sync_capture(session, "graph", "insert", "grid", grid)
    return f"restored graph #{grid}"


@register("graph.delete")
async def _revert_graph_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """graph.delete: restore the graph row and every captured item/line row
    (undo); delete everything again (redo)."""
    detail = _detail(row)
    grid = row.get("entity_id")
    if not grid:
        raise _missing_data()
    if undo:
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("grid"):
            raise _missing_data()
        try:
            await _insert_row(session, "graph", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore graph #{grid}: {err}") from err
        await _sync_capture(session, "graph", "insert", "grid", grid)
        restored = 0
        for table, _pk in (
            ("gr_cdct_text_item", "gtextid"),
            ("gr_case_text_item", "gcaseid"),
            ("gr_file_text_item", "gfileid"),
            ("gr_free_text_item", "gfreeid"),
            ("gr_memo_item", "gmemoid"),
            ("gr_cdct_line_item", "glineid"),
            ("gr_free_line_item", "gflineid"),
        ):
            for r in detail.get(table) or []:
                try:
                    await _insert_row(session, table, r)
                    restored += 1
                except Exception as err:
                    raise UnsupportedAction(f"cannot restore {table} row: {err}") from err
        return f"restored graph #{grid} with {restored} item/line row(s)"
    await _delete_graph_rows(session, grid)
    await _delete_by_id(session, "graph", "grid", grid)
    return f"deleted graph #{grid}"


@register("graph.item_add", "graph.item_delete", "graph.line_add", "graph.line_delete")
async def _revert_graph_row(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """graph.item_add / item_delete / line_add / line_delete."""
    action = row.get("action") or ""
    entity = row.get("entity") or ""
    pk = _GRAPH_PKS.get(entity)
    if pk is None:
        raise UnsupportedAction(f"no undo for {action}")
    detail = _detail(row)
    row_dict = detail.get("row")
    row_id = row.get("entity_id")
    if row_id is None and isinstance(row_dict, dict):
        row_id = row_dict.get(pk)
    if row_id is None:
        raise _missing_data()
    is_create = action in ("graph.item_add", "graph.line_add")
    if is_create == undo:
        await _delete_by_id(session, entity, pk, row_id)
        return f"deleted {entity} #{row_id}"
    if not isinstance(row_dict, dict) or not row_dict.get(pk):
        raise _missing_data()
    try:
        await _insert_row(session, entity, row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore {entity} #{row_id}: {err}") from err
    await _sync_capture(session, entity, "insert", pk, row_id)
    return f"restored {entity} #{row_id}"


@register("graph.update", "graph.item_update", "graph.line_update")
async def _revert_graph_update(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """graph / graph item / graph line updates: generic before/after row
    inversion."""
    entity = row.get("entity") or "graph"
    pk = _GRAPH_PKS.get(entity, "grid")
    return await _revert_row_update(session, row, undo=undo, table=entity, pk=pk)
