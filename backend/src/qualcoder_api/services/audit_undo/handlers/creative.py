"""Creative item / creative promote handlers."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _insert_row,
    _missing_data,
    _sync_capture,
    _update_row,
)
from ..registry import register


@register("creative.create", "creative.update", "creative.delete")
async def _revert_creative(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """creative.create / creative.update / creative.delete."""
    action = row.get("action") or ""
    detail = _detail(row)
    item_id = row.get("entity_id")
    if not item_id:
        raise _missing_data()
    if action == "creative.update":
        before = detail.get("before")
        if not isinstance(before, dict):
            raise _missing_data()
        if undo:
            await _update_row(session, "creative_item", "id", item_id, before)
        else:
            fields = {k: v for k, v in detail.items() if k in ("text", "note")}
            await _update_row(session, "creative_item", "id", item_id, fields)
        await _sync_capture(session, "creative_item", "update", "id", item_id)
        return f"creative item #{item_id} {'restored' if undo else 're-applied'}"
    row_dict = detail.get("row") or detail
    if (action == "creative.create") == undo:
        await _delete_by_id(session, "creative_item", "id", item_id)
        return f"deleted creative item #{item_id}"
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise _missing_data()
    try:
        await _insert_row(session, "creative_item", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore creative item #{item_id}: {err}") from err
    await _sync_capture(session, "creative_item", "insert", "id", item_id)
    return f"restored creative item #{item_id}"


@register("creative.promote")
async def _revert_creative_promote(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """creative.promote: remove the created code + its coding (undo) or
    restore both (redo) from the captured rows."""
    detail = _detail(row)
    code = detail.get("code")
    coding = detail.get("coding")
    cid = (code or {}).get("cid") or detail.get("cid")
    if not cid:
        raise _missing_data()
    if undo:
        await _delete_by_id(session, "code_name", "cid", cid)
        if isinstance(coding, dict) and coding.get("ctid"):
            await _delete_by_id(session, "code_text", "ctid", coding["ctid"])
        return f"deleted code #{cid} and its coding"
    if not isinstance(code, dict) or not code.get("cid"):
        raise _missing_data()
    try:
        await _insert_row(session, "code_name", code)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore code #{cid}: {err}") from err
    await _sync_capture(session, "code_name", "insert", "cid", cid)
    if isinstance(coding, dict) and coding.get("ctid"):
        try:
            await _insert_row(session, "code_text", coding)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore the coding of code #{cid}: {err}") from err
        await _sync_capture(session, "code_text", "insert", "ctid", coding["ctid"])
    return f"restored code #{cid} and its coding"
