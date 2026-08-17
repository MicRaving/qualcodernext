"""Reference delete / attach / detach handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _in_params,
    _insert_row,
    _missing_data,
    _sync_capture,
)
from ..registry import register


@register("reference.delete")
async def _revert_reference_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """reference.delete: re-insert the captured ris rows and re-link the
    sources that pointed at the reference (undo); delete again (redo)."""
    detail = _detail(row)
    risid = row.get("entity_id")
    if not risid:
        raise _missing_data()
    if undo:
        ris_rows = detail.get("rows") or []
        if not ris_rows:
            raise _missing_data()
        for r in ris_rows:
            try:
                await _insert_row(session, "ris", r)
            except Exception as err:
                raise UnsupportedAction(f"cannot restore ris row: {err}") from err
        source_ids = detail.get("source_ids") or []
        if source_ids:
            placeholders, params = _in_params(source_ids)
            await session.execute(
                text(f"UPDATE source SET risid = :r WHERE id IN ({placeholders})"),
                {**params, "r": risid},
            )
        return f"restored reference #{risid} ({len(ris_rows)} ris row(s))"
    await session.execute(text("DELETE FROM ris WHERE risid = :v"), {"v": risid})
    await session.execute(
        text("UPDATE source SET risid = NULL WHERE risid = :v"), {"v": risid}
    )
    return f"deleted reference #{risid}"


@register("reference.attach")
async def _revert_reference_attach(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """reference.attach: unlink and delete the imported attachment source
    (undo); re-insert it and re-link (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    if not source_id:
        raise _missing_data()
    if undo:
        await session.execute(
            text("UPDATE source SET risid = NULL WHERE id = :v"), {"v": source_id}
        )
        for table, col in (
            ("code_text", "fid"),
            ("code_image", "id"),
            ("code_av", "id"),
            ("annotation", "fid"),
            ("case_text", "fid"),
        ):
            await session.execute(text(f"DELETE FROM {table} WHERE {col} = :v"), {"v": source_id})
        await _delete_by_id(session, "source", "id", source_id)
        return f"deleted attached source #{source_id}"
    row_dict = detail.get("row")
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise _missing_data()
    try:
        await _insert_row(session, "source", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore attached source #{source_id}: {err}") from err
    await _sync_capture(session, "source", "insert", "id", source_id)
    risid = detail.get("risid")
    if risid:
        await session.execute(
            text("UPDATE source SET risid = :r WHERE id = :v"),
            {"r": risid, "v": source_id},
        )
    return f"restored attached source #{source_id}"


@register("reference.detach")
async def _revert_reference_detach(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """reference.detach: re-link the source to its reference (undo) or unlink
    it again (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    risid = detail.get("risid")
    if not source_id or not risid:
        raise _missing_data()
    if undo:
        await session.execute(
            text("UPDATE source SET risid = :r WHERE id = :v"),
            {"r": risid, "v": source_id},
        )
        return f"re-linked source #{source_id} to reference #{risid}"
    await session.execute(
        text("UPDATE source SET risid = NULL WHERE id = :v AND risid = :r"),
        {"v": source_id, "r": risid},
    )
    return f"detached source #{source_id} from reference #{risid}"
