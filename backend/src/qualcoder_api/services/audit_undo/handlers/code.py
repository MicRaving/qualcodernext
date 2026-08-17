"""Code and category handlers (create/delete/rename/move/merge)."""
from __future__ import annotations

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables

from ..base import (
    UnsupportedAction,
    _coding_table_for,
    _delete_by_id,
    _detail,
    _ensure,
    _in_params,
    _insert_row,
    _missing_data,
    _restore_row,
    _sync_capture,
    _update_row,
)
from ..registry import register

_TREE_FIELDS = ("catid", "supercid", "position")


@register("code.rename")
async def _revert_rename(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """code.rename: restore the full pre-update row when recorded, else the
    old/new name only (legacy rows)."""
    detail = _detail(row)
    cid = _ensure(detail, "cid")
    before = detail.get("before")
    after = detail.get("after")
    if isinstance(before, dict) and isinstance(after, dict):
        await _update_row(session, "code_name", "cid", cid, before if undo else after)
        await _sync_capture(session, "code_name", "update", "cid", cid)
        return f"restored code #{cid}"
    name = detail.get("old_name") if undo else detail.get("new_name")
    if not name:
        raise _missing_data()
    await session.execute(
        update(tables.code_name).where(tables.code_name.c.cid == cid).values(name=name)
    )
    await _sync_capture(session, "code_name", "update", "cid", cid)
    return f"renamed code #{cid} to {name!r}"


@register("code.create")
async def _revert_code_create(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    detail = _detail(row)
    cid = _ensure(detail, "cid")
    if undo:
        # Mirror delete_code: remove the code AND its codings so the undo
        # of a code.create does not orphan segments. Also drop the comments
        # attached to the code and its codings so none are orphaned.
        coding_ids: list[int] = []
        for tbl, col, pk in (
            ("code_text", "cid", "ctid"),
            ("code_av", "cid", "avid"),
            ("code_image", "cid", "imid"),
        ):
            ids = (
                await session.execute(text(f"SELECT {pk} FROM {tbl} WHERE {col} = :v"), {"v": cid})
            ).scalars().all()
            coding_ids.extend(ids)
            await session.execute(text(f"DELETE FROM {tbl} WHERE {col} = :v"), {"v": cid})
            for i in ids:
                await _sync_capture(session, tbl, "delete", pk, i)
        await session.execute(text("DELETE FROM code_name WHERE cid = :v"), {"v": cid})
        await _sync_capture(session, "code_name", "delete", "cid", cid)
        if coding_ids:
            placeholders, params = _in_params(coding_ids)
            await session.execute(
                text(f"DELETE FROM comment WHERE target_kind = 'coding' AND target_id IN ({placeholders})"),
                params,
            )
        await session.execute(
            text("DELETE FROM comment WHERE target_kind = 'code' AND target_id = :v"),
            {"v": cid},
        )
        return f"deleted code #{cid} (and its codings)"
    await _insert_row(session, "code_name", detail)
    await _sync_capture(session, "code_name", "insert", "cid", cid)
    return f"restored code #{cid}"


@register("code.delete")
async def _revert_code_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    detail = _detail(row)
    cid = _ensure(detail, "cid")
    if undo:
        await _insert_row(session, "code_name", detail)
        await _sync_capture(session, "code_name", "insert", "cid", cid)
        return f"restored code #{cid}"
    # Mirror delete_code: remove the code AND its codings again.
    for tbl, col in (("code_text", "cid"), ("code_av", "cid"), ("code_image", "cid")):
        await session.execute(text(f"DELETE FROM {tbl} WHERE {col} = :v"), {"v": cid})
    await _delete_by_id(session, "code_name", "cid", cid)
    return f"deleted code #{cid}"


@register("code.move", "code.promote", "code.demote")
async def _revert_code_tree_move(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """code.move / code.promote / code.demote: restore the pre-move
    catid/supercid/position (undo) or the post-move values (redo)."""
    detail = _detail(row)
    cid = row.get("entity_id") or detail.get("cid")
    if not cid:
        raise _missing_data()
    before = detail.get("before")
    after = detail.get("after")
    target = before if undo else after
    if not isinstance(target, dict):
        raise _missing_data()
    await _update_row(session, "code_name", "cid", cid, {f: target.get(f) for f in _TREE_FIELDS})
    await _sync_capture(session, "code_name", "update", "cid", cid)
    return f"code #{cid} tree position {'restored' if undo else 're-applied'}"


@register("code.merge")
async def _revert_code_merge(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """code.merge: recreate the merged-away code and move its codings back
    (undo); move them to the target again and drop the code (redo)."""
    detail = _detail(row)
    from_cid = _ensure(detail, "from_cid")
    target_cid = row.get("entity_id") or detail.get("target_cid")
    if not target_cid:
        raise _missing_data()
    from_code = detail.get("from_code")
    from_rows = detail.get("from_rows") or []
    subcodes = detail.get("subcodes") or []
    if not isinstance(from_code, dict):
        raise _missing_data()
    if undo:
        try:
            await _insert_row(session, "code_name", from_code)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore code #{from_cid}: {err}") from err
        await _sync_capture(session, "code_name", "insert", "cid", from_cid)
        for r in from_rows:
            table, pk = _coding_table_for(r)
            try:
                action = await _restore_row(session, table, pk, r)
            except Exception as err:
                raise UnsupportedAction(f"cannot restore {table} row: {err}") from err
            await _sync_capture(session, table, action, pk, r.get(pk))
        if subcodes:
            placeholders, params = _in_params(list(subcodes))
            await session.execute(
                text(
                    "UPDATE code_name SET supercid = :from_c WHERE supercid = :to_c "
                    f"AND cid IN ({placeholders})"
                ),
                {**params, "from_c": from_cid, "to_c": target_cid},
            )
        return f"restored code #{from_cid} and its codings"
    # Redo: re-apply the merge (mirror merge_codes semantics).
    for r in from_rows:
        table, pk = _coding_table_for(r)
        if table == "code_text":
            dup = (
                await session.execute(
                    text(
                        "SELECT ctid FROM code_text WHERE cid = :to AND fid = :fid "
                        "AND pos0 = :p0 AND pos1 = :p1 AND owner = :owner"
                    ),
                    {"to": target_cid, "fid": r.get("fid"), "p0": r.get("pos0"),
                     "p1": r.get("pos1"), "owner": r.get("owner")},
                )
            ).first()
            if dup is not None:
                await _delete_by_id(session, table, pk, r.get(pk))
                continue
        await session.execute(
            text(f"UPDATE {table} SET cid = :to WHERE {pk} = :v"),
            {"to": target_cid, "v": r.get(pk)},
        )
    if subcodes:
        placeholders, params = _in_params(list(subcodes))
        await session.execute(
            text(
                "UPDATE code_name SET supercid = :to_c "
                f"WHERE cid IN ({placeholders})"
            ),
            {**params, "to_c": target_cid},
        )
    await _delete_by_id(session, "code_name", "cid", from_cid)
    return f"merged code #{from_cid} into #{target_cid}"


@register("category.create")
async def _revert_category_create(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise _missing_data()
    if undo:
        # Mirror delete_category: orphans are reassigned to the root.
        await session.execute(
            text("UPDATE code_name SET catid = NULL WHERE catid = :v"), {"v": catid}
        )
        await session.execute(
            text("UPDATE code_cat SET supercatid = NULL WHERE supercatid = :v"), {"v": catid}
        )
        await _delete_by_id(session, "code_cat", "catid", catid)
        return f"deleted category #{catid}"
    row_dict = detail.get("row") or detail
    if not isinstance(row_dict, dict) or not row_dict.get("catid"):
        raise _missing_data()
    await _insert_row(session, "code_cat", row_dict)
    await _sync_capture(session, "code_cat", "insert", "catid", catid)
    return f"restored category #{catid}"


@register("category.delete")
async def _revert_category_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise _missing_data()
    if undo:
        row_dict = detail.get("row") or detail
        if not isinstance(row_dict, dict) or not row_dict.get("catid"):
            raise _missing_data()
        try:
            await _insert_row(session, "code_cat", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore category #{catid}: {err}") from err
        await _sync_capture(session, "code_cat", "insert", "catid", catid)
        return f"restored category #{catid}"
    # Redo: delete again like delete_category.
    await session.execute(
        text("UPDATE code_name SET catid = NULL WHERE catid = :v"), {"v": catid}
    )
    await session.execute(
        text("UPDATE code_cat SET supercatid = NULL WHERE supercatid = :v"), {"v": catid}
    )
    await _delete_by_id(session, "code_cat", "catid", catid)
    return f"deleted category #{catid}"


@register("category.rename")
async def _revert_category_rename(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise _missing_data()
    name = detail.get("old_name") if undo else detail.get("new_name")
    if not name:
        raise _missing_data()
    await session.execute(
        text("UPDATE code_cat SET name = :n WHERE catid = :id"), {"n": name, "id": catid}
    )
    await _sync_capture(session, "code_cat", "update", "catid", catid)
    return f"category #{catid} renamed to {name!r}"


@register("category.move", "category.promote", "category.demote")
async def _revert_category_tree_move(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """category.move / category.promote / category.demote."""
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise _missing_data()
    before = detail.get("before")
    after = detail.get("after")
    target = before if undo else after
    if not isinstance(target, dict):
        raise _missing_data()
    await _update_row(session, "code_cat", "catid", catid, {f: target.get(f) for f in _TREE_FIELDS})
    await _sync_capture(session, "code_cat", "update", "catid", catid)
    return f"category #{catid} tree position {'restored' if undo else 're-applied'}"


@register("category.merge")
async def _revert_category_merge(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """category.merge: recreate the merged-away category and move its codes
    and subcategories back (undo); re-apply the merge (redo)."""
    detail = _detail(row)
    from_catid = _ensure(detail, "from_catid")
    target_catid = row.get("entity_id") or detail.get("target_catid")
    if not target_catid:
        raise _missing_data()
    from_category = detail.get("from_category")
    codes = detail.get("codes") or []
    subcats = detail.get("subcats") or []
    if undo:
        if not isinstance(from_category, dict):
            raise _missing_data()
        try:
            await _insert_row(session, "code_cat", from_category)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore category #{from_catid}: {err}") from err
        await _sync_capture(session, "code_cat", "insert", "catid", from_catid)
        if codes:
            placeholders, params = _in_params(list(codes))
            await session.execute(
                text(
                    "UPDATE code_name SET catid = :from_c WHERE catid = :to_c "
                    f"AND cid IN ({placeholders})"
                ),
                {**params, "from_c": from_catid, "to_c": target_catid},
            )
        if subcats:
            placeholders, params = _in_params(list(subcats))
            await session.execute(
                text(
                    "UPDATE code_cat SET supercatid = :from_c WHERE supercatid = :to_c "
                    f"AND catid IN ({placeholders})"
                ),
                {**params, "from_c": from_catid, "to_c": target_catid},
            )
        return f"restored category #{from_catid}"
    if codes:
        placeholders, params = _in_params(list(codes))
        await session.execute(
            text(
                "UPDATE code_name SET catid = :to_c WHERE catid = :from_c "
                f"AND cid IN ({placeholders})"
            ),
            {**params, "to_c": target_catid, "from_c": from_catid},
        )
    if subcats:
        placeholders, params = _in_params(list(subcats))
        await session.execute(
            text(
                "UPDATE code_cat SET supercatid = :to_c WHERE supercatid = :from_c "
                f"AND catid IN ({placeholders})"
            ),
            {**params, "to_c": target_catid, "from_c": from_catid},
        )
    await _delete_by_id(session, "code_cat", "catid", from_catid)
    return f"merged category #{from_catid} into #{target_catid}"
