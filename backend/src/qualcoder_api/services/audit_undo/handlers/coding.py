"""Coding, annotation, edit, autocode, coding-undo and code-memo handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _coding_defaults,
    _delete_by_id,
    _detail,
    _ensure,
    _in_params,
    _insert_row,
    _missing_data,
    _sync_capture,
    _update_row,
)
from ..registry import register


@register("coding.create", "coding.delete")
async def _revert_coding(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """Coding create/delete pairs: invert insert↔delete using the full row."""
    action = row.get("action") or ""
    detail = _detail(row)
    table = row.get("entity") or ""  # code_text / code_image / code_av
    pk = {"code_text": "ctid", "code_image": "imid", "code_av": "avid"}.get(table)
    if pk is None:
        raise _missing_data()
    row_id = _ensure(detail, pk)
    if (action == "coding.create") == undo:
        await _delete_by_id(session, table, pk, row_id)
        # Do not orphan comments attached to the coding being removed.
        await session.execute(
            text("DELETE FROM comment WHERE target_kind = 'coding' AND target_id = :v"),
            {"v": row_id},
        )
        return f"deleted {table} #{row_id}"
    try:
        await _insert_row(session, table, detail)
    except Exception as err:
        # Unique-constraint collisions must surface as a clean 422, not 500.
        raise UnsupportedAction(f"cannot restore {table} #{row_id}: {err}") from err
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


@register("coding.update")
async def _revert_coding_update(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """coding.update (text/image/AV): restore the full pre-update row."""
    entity = row.get("entity") or ""  # code_text / code_image / code_av
    detail = _detail(row)
    pk = {"code_text": "ctid", "code_image": "imid", "code_av": "avid"}.get(entity)
    if pk is None:
        raise _missing_data()
    target = detail.get("before") if undo else detail.get("after")
    if not isinstance(target, dict):
        raise _missing_data()
    row_id = target.get(pk)
    if row_id is None:
        raise _missing_data()
    await _update_row(session, entity, pk, row_id, target)
    await _sync_capture(session, entity, "update", pk, row_id)
    return f"restored {entity} #{row_id}"


@register("annotation.create", "annotation.delete")
async def _revert_annotation(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    action = row.get("action") or ""
    detail = _detail(row)
    anid = _ensure(detail, "anid")
    if (action == "annotation.create") == undo:
        await _delete_by_id(session, "annotation", "anid", anid)
        return f"deleted annotation #{anid}"
    try:
        await _insert_row(session, "annotation", detail)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore annotation #{anid}: {err}") from err
    await _sync_capture(session, "annotation", "insert", "anid", anid)
    return f"restored annotation #{anid}"


@register("source.edit")
async def _revert_edit(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """source.edit: restore the before (undo) or after (redo) text via the
    shift-aware commit path."""
    from qualcoder_api.services.coding_service import commit_edit

    detail = _detail(row)
    fid = detail.get("fid") or row.get("source_id")
    if fid is None:
        raise _missing_data()
    target = detail.get("before") if undo else detail.get("after")
    if target is None:
        raise _missing_data()
    try:
        result = await commit_edit(session, fid=fid, new_text=target, owner=row.get("user") or "default")
    except ValueError as err:
        raise UnsupportedAction(f"cannot apply the edit undo: {err}") from err
    return f"restored text of source #{fid} ({result.get('updated', {})} shifts)"


@register("coding.autocode")
async def _revert_autocode(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """coding.autocode (text + dictionary): delete the codings this run
    created (undo) or re-insert them (redo) from the captured rows."""
    detail = _detail(row)
    if detail.get("batch") or detail.get("job_ids"):
        raise UnsupportedAction(
            "background autocode jobs cannot be undone — cancel the jobs or "
            "delete the created codings manually"
        )
    if detail.get("too_many"):
        raise UnsupportedAction(
            "this autocode run created more than 5000 codings — delete them manually"
        )
    text_ids = detail.get("text_ids") or []
    created_rows = detail.get("created_rows") or []
    if undo:
        if not text_ids:
            raise _missing_data()
        placeholders, params = _in_params(text_ids)
        await session.execute(
            text(f"DELETE FROM code_text WHERE ctid IN ({placeholders})"), params
        )
        return f"deleted {len(text_ids)} autocode-created coding(s)"
    if not created_rows:
        raise UnsupportedAction("cannot redo this autocode — run the autocode again")
    restored = 0
    for r in created_rows:
        try:
            await _insert_row(session, "code_text", _coding_defaults(r))
            restored += 1
        except Exception:
            continue  # duplicate span — skipped like the engine does
    return f"restored {restored} autocode-created coding(s)"


@register("coding.undo")
async def _revert_coding_undo(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """coding.undo (the user's own ctrl+z): the detail carries the restored
    rows, so undoing the undo deletes them again and redoing re-inserts them."""
    detail = _detail(row)
    items = detail.get("items") or []
    if not items:
        raise _missing_data()
    if undo:
        deleted = 0
        for item in items:
            result = await session.execute(
                text(
                    "DELETE FROM code_text WHERE cid = :c AND fid = :f AND pos0 = :p0 "
                    "AND pos1 = :p1 AND owner = :o"
                ),
                {
                    "c": item.get("cid"),
                    "f": item.get("fid"),
                    "p0": item.get("pos0"),
                    "p1": item.get("pos1"),
                    "o": item.get("owner"),
                },
            )
            deleted += int(getattr(result, "rowcount", 0) or 0)
        return f"re-deleted {deleted} coding(s)"
    restored = 0
    for item in items:
        try:
            await _insert_row(session, "code_text", _coding_defaults(item))
            restored += 1
        except Exception:
            continue
    return f"restored {restored} coding(s)"


@register("code.memo")
async def _revert_code_memo(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """code.memo (MCP): restore the previous memo (undo) or the new one (redo)."""
    detail = _detail(row)
    cid = row.get("entity_id") or detail.get("cid")
    if not cid:
        raise _missing_data()
    memo = detail.get("old_memo") if undo else detail.get("memo")
    if memo is None:
        raise _missing_data()
    await session.execute(
        text("UPDATE code_name SET memo = :m WHERE cid = :v"), {"m": memo, "v": cid}
    )
    await _sync_capture(session, "code_name", "update", "cid", cid)
    return f"code #{cid} memo {'restored' if undo else 're-applied'}"
