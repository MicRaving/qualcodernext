"""Undo / redo for audit-log actions (edit review).

Each supported action records enough detail to invert itself: full rows
for coding/annotation inserts and deletes, before/after text for edits,
old/new names for renames. ``undo`` applies the inverse; ``redo`` applies
the inverse of the inverse (i.e. re-applies the original change).

Unsupported actions raise ``UnsupportedAction`` — the UI hides the undo
button for those.
"""

from __future__ import annotations

import json

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession


class UnsupportedAction(Exception):
    pass


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
        raise UnsupportedAction(f"missing detail field {key}")
    return detail[key]


async def _insert_row(session: AsyncSession, table: str, row: dict) -> None:
    cols = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row)
    await session.execute(
        text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), row
    )


async def _delete_by_id(session: AsyncSession, table: str, pk: str, value: int) -> None:
    await session.execute(text(f"DELETE FROM {table} WHERE {pk} = :v"), {"v": value})


async def _revert_coding(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """Coding create/delete pairs: invert insert↔delete using the full row."""
    action = row["action"]
    entity = row["entity"]
    detail = _detail(row)
    table = entity  # code_text / code_image / code_av
    pk = {"code_text": "ctid", "code_image": "imid", "code_av": "avid"}[table]
    row_id = _ensure(detail, pk)
    if (action == "coding.create") == undo:
        await _delete_by_id(session, table, pk, row_id)
        return f"deleted {table} #{row_id}"
    await _insert_row(session, table, detail)
    return f"restored {table} #{row_id}"


async def _revert_annotation(session: AsyncSession, row: dict, *, undo: bool) -> str:
    action = row["action"]
    detail = _detail(row)
    anid = _ensure(detail, "anid")
    if (action == "annotation.create") == undo:
        await _delete_by_id(session, "annotation", "anid", anid)
        return f"deleted annotation #{anid}"
    await _insert_row(session, "annotation", detail)
    return f"restored annotation #{anid}"


async def _revert_edit(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """source.edit: restore the before (undo) or after (redo) text via the
    shift-aware commit path."""
    from qualcoder_api.services.coding_service import commit_edit

    detail = _detail(row)
    fid = detail.get("fid") or row.get("source_id")
    if fid is None:
        raise UnsupportedAction("missing fid")
    target = detail.get("before") if undo else detail.get("after")
    if target is None:
        raise UnsupportedAction("missing before/after text")
    result = await commit_edit(session, fid=fid, new_text=target, owner=row.get("user") or "default")
    return f"restored text of source #{fid} ({result.get('updated', {})} shifts)"


async def _revert_rename(session: AsyncSession, row: dict, *, undo: bool) -> str:
    from qualcoder_api.persistence import tables

    detail = _detail(row)
    cid = _ensure(detail, "cid")
    name = detail.get("old_name") if undo else detail.get("new_name")
    if not name:
        raise UnsupportedAction("missing name")
    await session.execute(
        update(tables.code_name).where(tables.code_name.c.cid == cid).values(name=name)
    )
    return f"renamed code #{cid} to {name!r}"


async def _revert_code_create(session: AsyncSession, row: dict, *, undo: bool) -> str:

    detail = _detail(row)
    cid = _ensure(detail, "cid")
    if undo:
        await _delete_by_id(session, "code_name", "cid", cid)
        return f"deleted code #{cid} (and its codings)"
    await _insert_row(session, "code_name", detail)
    return f"restored code #{cid}"


async def _revert_entity_create(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """case.create / journal.create."""
    action = row["action"]
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
        return f"deleted {table} #{row_id}"
    await _insert_row(session, table, detail)
    return f"restored {table} #{row_id}"


async def _revert_update(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """annotation.update / journal.update / case.update: restore the
    pre-edit values recorded in the detail."""
    action = row["action"]
    detail = _detail(row)
    if action == "annotation.update":
        anid = _ensure(detail, "anid")
        memo = detail.get("old_memo") if undo else detail.get("new_memo")
        await session.execute(
            text("UPDATE annotation SET memo = :m WHERE anid = :id"), {"m": memo, "id": anid}
        )
        return f"annotation #{anid} memo {'restored' if undo else 're-applied'}"
    if action == "journal.update":
        jid = _ensure(detail, "jid")
        name = detail.get("old_name") if undo else detail.get("new_name")
        jentry = detail.get("old_jentry") if undo else detail.get("new_jentry")
        await session.execute(
            text("UPDATE journal SET name = :n, jentry = :j WHERE jid = :id"),
            {"n": name, "j": jentry, "id": jid},
        )
        return f"journal #{jid} {'restored' if undo else 're-applied'}"
    if action == "case.update":
        caseid = _ensure(detail, "caseid")
        name = detail.get("old_name") if undo else detail.get("new_name")
        memo = detail.get("old_memo") if undo else detail.get("new_memo")
        await session.execute(
            text("UPDATE cases SET name = :n, memo = :m WHERE caseid = :id"),
            {"n": name, "m": memo, "id": caseid},
        )
        return f"case #{caseid} {'restored' if undo else 're-applied'}"
    raise UnsupportedAction(f"no undo for {action}")


async def _revert_code_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    detail = _detail(row)
    cid = _ensure(detail, "cid")
    if undo:
        await _insert_row(session, "code_name", detail)
        return f"restored code #{cid}"
    await _delete_by_id(session, "code_name", "cid", cid)
    return f"deleted code #{cid}"


async def _revert_source_import(session: AsyncSession, row: dict, *, undo: bool) -> str:
    source_id = row.get("entity_id")
    if not source_id:
        raise UnsupportedAction("missing source id")
    if undo:
        await _delete_by_id(session, "source", "id", source_id)
        return f"deleted source #{source_id}"
    raise UnsupportedAction("cannot redo a source import")


async def apply(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """Apply the inverse (undo=True) or re-apply (undo=False) of one audit row."""
    action = row.get("action") or ""
    if action in ("coding.create", "coding.delete"):
        return await _revert_coding(session, row, undo=undo)
    if action in ("annotation.create", "annotation.delete"):
        return await _revert_annotation(session, row, undo=undo)
    if action == "source.edit":
        return await _revert_edit(session, row, undo=undo)
    if action == "code.rename":
        return await _revert_rename(session, row, undo=undo)
    if action == "code.create":
        return await _revert_code_create(session, row, undo=undo)
    if action == "code.delete":
        return await _revert_code_delete(session, row, undo=undo)
    if action in ("case.create", "journal.create"):
        return await _revert_entity_create(session, row, undo=undo)
    if action in ("annotation.update", "journal.update", "case.update"):
        return await _revert_update(session, row, undo=undo)
    if action == "source.import":
        return await _revert_source_import(session, row, undo=undo)
    raise UnsupportedAction(f"no undo for {action}")
