"""Case link / attribute type / attribute value handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _insert_row,
    _missing_data,
    _sync_capture,
)
from ..registry import register


@register("case.link_file", "case.link_span", "case.unlink_file")
async def _revert_case_link(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """case.link_file / case.link_span / case.unlink_file: invert the
    case_text insert/delete using the captured rows."""
    action = row.get("action") or ""
    detail = _detail(row)
    if action == "case.unlink_file":
        rows = detail.get("rows") or []
        if undo:
            for r in rows:
                try:
                    await _insert_row(session, "case_text", r)
                except Exception as err:
                    raise UnsupportedAction(f"cannot restore case_text row: {err}") from err
                await _sync_capture(session, "case_text", "insert", "id", r.get("id"))
            return f"restored {len(rows)} case_text row(s)"
        for r in rows:
            await _delete_by_id(session, "case_text", "id", r.get("id"))
        return f"deleted {len(rows)} case_text row(s)"
    row_dict = detail.get("row") or {}
    row_id = row.get("entity_id") or row_dict.get("id")
    if not row_id:
        raise _missing_data()
    if undo:
        await _delete_by_id(session, "case_text", "id", row_id)
        return f"deleted case_text #{row_id}"
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise _missing_data()
    try:
        await _insert_row(session, "case_text", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore case_text #{row_id}: {err}") from err
    await _sync_capture(session, "case_text", "insert", "id", row_id)
    return f"restored case_text #{row_id}"


@register("attribute.create", "attribute.delete")
async def _revert_attribute_type(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """attribute.create / attribute.delete (attribute_type rows)."""
    action = row.get("action") or ""
    detail = _detail(row)
    name = detail.get("name")
    if not name:
        raise _missing_data()
    row_dict = detail.get("row") or detail
    if action == "attribute.create":
        if undo:
            # Mirror delete_type: the type and all its values go away.
            await session.execute(text("DELETE FROM attribute WHERE name = :v"), {"v": name})
            await _delete_by_id(session, "attribute_type", "name", name)
            return f"deleted attribute type {name!r}"
        if not isinstance(row_dict, dict) or not row_dict.get("name"):
            raise _missing_data()
        await _insert_row(session, "attribute_type", row_dict)
        await _sync_capture(session, "attribute_type", "insert", "name", name)
        return f"restored attribute type {name!r}"
    if action == "attribute.delete":
        if undo:
            if not isinstance(row_dict, dict) or not row_dict.get("name"):
                raise _missing_data()
            try:
                await _insert_row(session, "attribute_type", row_dict)
            except Exception as err:
                raise UnsupportedAction(f"cannot restore attribute type {name!r}: {err}") from err
            await _sync_capture(session, "attribute_type", "insert", "name", name)
            return f"restored attribute type {name!r}"
        await session.execute(text("DELETE FROM attribute WHERE name = :v"), {"v": name})
        await _delete_by_id(session, "attribute_type", "name", name)
        return f"deleted attribute type {name!r}"
    raise UnsupportedAction(f"no undo for {action}")


@register("attribute.set_value")
async def _revert_attribute_set(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """attribute.set_value: restore the previous value (undo) or re-apply
    the recorded one (redo). The ``before`` row is None for first-time
    assignments."""
    detail = _detail(row)
    before = detail.get("before")
    after = detail.get("after")
    if not isinstance(after, dict) or not after.get("attrid"):
        raise _missing_data()

    async def _insert_guarded(values: dict, what: str) -> None:
        try:
            await _insert_row(session, "attribute", values)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore {what}: {err}") from err

    if undo:
        await _delete_by_id(session, "attribute", "attrid", after["attrid"])
        if isinstance(before, dict) and before.get("attrid"):
            await _insert_guarded(before, "attribute value")
        return "attribute value restored"
    if isinstance(before, dict) and before.get("attrid"):
        await _delete_by_id(session, "attribute", "attrid", before["attrid"])
    await _insert_guarded(after, "attribute value")
    return "attribute value re-applied"
