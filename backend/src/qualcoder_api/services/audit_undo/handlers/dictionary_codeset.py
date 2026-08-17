"""Dictionary / code set / R script / R run handlers."""
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


@register("dictionary.create", "dictionary.update", "dictionary.entry_add", "dictionary.entry_delete")
async def _revert_dictionary(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """dictionary.create / dictionary.update / entry_add / entry_delete."""
    action = row.get("action") or ""
    detail = _detail(row)
    if action == "dictionary.update":
        dict_id = row.get("entity_id") or detail.get("id")
        if not dict_id:
            raise _missing_data()
        name = detail.get("old_name") if undo else detail.get("new_name")
        if not name:
            raise _missing_data()
        await session.execute(
            text("UPDATE dictionary SET name = :n WHERE id = :v"), {"n": name, "v": dict_id}
        )
        await _sync_capture(session, "dictionary", "update", "id", dict_id)
        return f"dictionary #{dict_id} {'restored' if undo else 're-applied'}"
    if action == "dictionary.create":
        return await _revert_row_pair(
            session, row, undo=undo, table="dictionary", pk="id",
            create_actions=("dictionary.create",),
        )
    return await _revert_row_pair(
        session, row, undo=undo, table="dictionary_entry", pk="id",
        create_actions=("dictionary.entry_add",),
        delete_actions=("dictionary.entry_delete",),
    )


@register("dictionary.delete")
async def _revert_dictionary_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """dictionary.delete: restore the dictionary row plus its entries (undo);
    delete again (redo)."""
    detail = _detail(row)
    dict_id = row.get("entity_id")
    if not dict_id:
        raise _missing_data()
    if undo:
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("id"):
            raise _missing_data()
        try:
            await _insert_row(session, "dictionary", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore dictionary #{dict_id}: {err}") from err
        await _sync_capture(session, "dictionary", "insert", "id", dict_id)
        for entry in detail.get("entries") or []:
            try:
                await _insert_row(session, "dictionary_entry", entry)
            except Exception as err:
                raise UnsupportedAction(f"cannot restore dictionary entry: {err}") from err
        return f"restored dictionary #{dict_id} with its entries"
    await session.execute(
        text("DELETE FROM dictionary_entry WHERE dict_id = :v"), {"v": dict_id}
    )
    await _delete_by_id(session, "dictionary", "id", dict_id)
    return f"deleted dictionary #{dict_id}"


@register("dictionary.import")
async def _revert_dictionary_import(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """dictionary.import: undo deletes the imported dictionary (and its
    entries); redo is not invertible without re-importing."""
    if undo:
        dict_id = row.get("entity_id")
        if not dict_id:
            raise _missing_data()
        await session.execute(
            text("DELETE FROM dictionary_entry WHERE dict_id = :v"), {"v": dict_id}
        )
        await _delete_by_id(session, "dictionary", "id", dict_id)
        return f"deleted imported dictionary #{dict_id}"
    raise UnsupportedAction("cannot redo a dictionary import — re-import the dictionary file")


@register("code_set.create", "code_set.rename", "code_set.delete")
async def _revert_code_set(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """code_set.create / rename / delete (with members)."""
    action = row.get("action") or ""
    detail = _detail(row)
    set_id = row.get("entity_id")
    if not set_id:
        raise _missing_data()
    if action == "code_set.rename":
        name = detail.get("old_name") if undo else detail.get("new_name")
        if not name:
            raise _missing_data()
        await session.execute(
            text("UPDATE code_set SET name = :n WHERE id = :v"), {"n": name, "v": set_id}
        )
        await _sync_capture(session, "code_set", "update", "id", set_id)
        return f"code set #{set_id} {'restored' if undo else 're-applied'}"
    if action == "code_set.create" and undo:
        await session.execute(
            text("DELETE FROM code_set_member WHERE set_id = :v"), {"v": set_id}
        )
        await _delete_by_id(session, "code_set", "id", set_id)
        return f"deleted code set #{set_id}"
    if action == "code_set.create":
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("id"):
            raise _missing_data()
        try:
            await _insert_row(session, "code_set", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore code set #{set_id}: {err}") from err
        await _sync_capture(session, "code_set", "insert", "id", set_id)
        return f"restored code set #{set_id}"
    # code_set.delete
    if undo:
        row_dict = detail.get("row")
        if row_dict is None and detail.get("id") is not None:
            row_dict = detail  # legacy/delete rows record the row as the detail
        if not isinstance(row_dict, dict) or not row_dict.get("id"):
            raise _missing_data()
        try:
            await _insert_row(session, "code_set", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore code set #{set_id}: {err}") from err
        await _sync_capture(session, "code_set", "insert", "id", set_id)
        for member in detail.get("members") or []:
            await session.execute(
                text("INSERT OR IGNORE INTO code_set_member (set_id, cid) VALUES (:s, :c)"),
                {"s": member.get("set_id"), "c": member.get("cid")},
            )
        return f"restored code set #{set_id}"
    await session.execute(
        text("DELETE FROM code_set_member WHERE set_id = :v"), {"v": set_id}
    )
    await _delete_by_id(session, "code_set", "id", set_id)
    return f"deleted code set #{set_id}"


@register("code_set.members_add", "code_set.members_remove")
async def _revert_code_set_members(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """code_set.members_add / members_remove: invert the member rows."""
    detail = _detail(row)
    set_id = row.get("entity_id")
    if not set_id:
        raise _missing_data()
    is_add = row.get("action") == "code_set.members_add"
    cids = detail.get("added_cids") if is_add else detail.get("removed_cids")
    cids = cids or []
    if undo == is_add:
        # Undo of an add removes the added members; redo of a remove re-adds.
        for cid in cids:
            await session.execute(
                text("DELETE FROM code_set_member WHERE set_id = :s AND cid = :c"),
                {"s": set_id, "c": cid},
            )
        return f"removed {len(cids)} member(s) of code set #{set_id}"
    for cid in cids:
        await session.execute(
            text("INSERT OR IGNORE INTO code_set_member (set_id, cid) VALUES (:s, :c)"),
            {"s": set_id, "c": cid},
        )
    verb = "re-added" if is_add else "restored"
    return f"{verb} {len(cids)} member(s) to code set #{set_id}"


@register("r_script.create", "r_script.update", "r_script.delete")
async def _revert_r_script(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """r_script.create / update / delete."""
    action = row.get("action") or ""
    if action == "r_script.update":
        return await _revert_row_update(session, row, undo=undo, table="r_script", pk="id")
    return await _revert_row_pair(
        session, row, undo=undo, table="r_script", pk="id",
        create_actions=("r_script.create",), delete_actions=("r_script.delete",),
    )


@register("r.run")
async def _revert_r_run(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """r.run: cancel the R job while it is queued/running; finished jobs only
    left artifacts under ``r_exchange/out`` (delete those manually)."""
    from qualcoder_api.services import r_service

    detail = _detail(row)
    job_id = detail.get("job_id")
    if not job_id:
        raise _missing_data()
    if not undo:
        raise UnsupportedAction("cannot redo an R run — run the script again")
    job = r_service.get_r_job(job_id)
    if job is None:
        raise UnsupportedAction("R job is gone — delete its outputs under r_exchange/out manually")
    state = job.get("state")
    if state in ("queued", "running"):
        r_service.control_r_job(job_id, "cancel")
        return f"cancelled R job {job_id}"
    if state == "done":
        raise UnsupportedAction(
            "R job already finished — delete its outputs under r_exchange/out manually"
        )
    return f"R job {job_id} already {state} — nothing to undo"
