"""Undo / redo for audit-log actions (edit review).

Each supported action records enough detail to invert itself: full rows
for coding/annotation inserts and deletes, before/after text for edits,
old/new names for renames, before/after row snapshots for updates and
tree moves, full rows + captured children for merges and transcript
companions. ``undo`` applies the inverse; ``redo`` applies the inverse
of the inverse (i.e. re-applies the original change).

Unsupported actions raise ``UnsupportedAction`` — the UI hides the undo
button for those. Import/autocode/transcription bulk actions are
deliberately not invertible (they create unbounded sets of rows); the
raised message says so instead of a bare "no undo".
"""

from __future__ import annotations

import json

from sqlalchemy import select, text, update
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


async def _sync_capture(session: AsyncSession, entity: str, action: str, pk: str, pk_value) -> None:
    """Capture the current state of one row after an undo/redo write."""
    from qualcoder_api.persistence import tables
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    table = getattr(tables, entity, None)
    if table is None:
        return
    row = (await session.execute(select(table).where(table.c[pk] == pk_value))).first()
    if row is not None:
        await _capture(session, entity, action, pk, pk_value, _rowdict(row))
    await session.flush()


async def _insert_row(session: AsyncSession, table: str, row: dict) -> None:
    cols = ", ".join(row.keys())
    placeholders = ", ".join(f":{k}" for k in row)
    await session.execute(
        text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), row
    )


async def _delete_by_id(session: AsyncSession, table: str, pk: str, value) -> None:
    await session.execute(text(f"DELETE FROM {table} WHERE {pk} = :v"), {"v": value})


async def _update_row(session: AsyncSession, table: str, pk: str, pk_value, values: dict) -> None:
    """UPDATE all columns of ``values`` (except the pk) for one row."""
    cols = {k: v for k, v in values.items() if k != pk}
    if not cols:
        return
    assignments = ", ".join(f"{k} = :{k}" for k in cols)
    await session.execute(
        text(f"UPDATE {table} SET {assignments} WHERE {pk} = :pk"),
        {**cols, "pk": pk_value},
    )


def _in_params(ids: list) -> tuple[str, dict]:
    """Named-parameter placeholders for an ``IN (...)`` clause plus params."""
    return (
        ", ".join(f":in{i}" for i in range(len(ids))),
        {f"in{i}": v for i, v in enumerate(ids)},
    )


async def _restore_row(session: AsyncSession, table: str, pk: str, row_dict: dict) -> str:
    """Update the row by pk when it still exists, else insert it back.

    Returns the sync action actually performed ("update" or "insert").
    """
    existing = (
        await session.execute(
            text(f"SELECT {pk} FROM {table} WHERE {pk} = :v"), {"v": row_dict.get(pk)}
        )
    ).first()
    if existing is not None:
        await _update_row(session, table, pk, row_dict.get(pk), row_dict)
        return "update"
    await _insert_row(session, table, row_dict)
    return "insert"


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
    try:
        await _insert_row(session, table, detail)
    except Exception as err:
        # Unique-constraint collisions must surface as a clean 422, not 500.
        raise UnsupportedAction(f"cannot restore {table} #{row_id}: {err}") from err
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


async def _revert_coding_update(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """coding.update (text/image/AV): restore the full pre-update row."""
    entity = row["entity"]  # code_text / code_image / code_av
    detail = _detail(row)
    pk = {"code_text": "ctid", "code_image": "imid", "code_av": "avid"}[entity]
    target = detail.get("before") if undo else detail.get("after")
    if not isinstance(target, dict):
        raise UnsupportedAction("missing before/after row")
    row_id = target.get(pk)
    if row_id is None:
        raise UnsupportedAction(f"missing {pk}")
    await _update_row(session, entity, pk, row_id, target)
    await _sync_capture(session, entity, "update", pk, row_id)
    return f"restored {entity} #{row_id}"


async def _revert_annotation(session: AsyncSession, row: dict, *, undo: bool) -> str:
    action = row["action"]
    detail = _detail(row)
    anid = _ensure(detail, "anid")
    if (action == "annotation.create") == undo:
        await _delete_by_id(session, "annotation", "anid", anid)
        return f"deleted annotation #{anid}"
    await _insert_row(session, "annotation", detail)
    await _sync_capture(session, "annotation", "insert", "anid", anid)
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
    """code.rename: restore the full pre-update row when recorded, else the
    old/new name only (legacy rows)."""
    from qualcoder_api.persistence import tables

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
        raise UnsupportedAction("missing name")
    await session.execute(
        update(tables.code_name).where(tables.code_name.c.cid == cid).values(name=name)
    )
    await _sync_capture(session, "code_name", "update", "cid", cid)
    return f"renamed code #{cid} to {name!r}"


async def _revert_code_create(session: AsyncSession, row: dict, *, undo: bool) -> str:

    detail = _detail(row)
    cid = _ensure(detail, "cid")
    if undo:
        # Mirror delete_code: remove the code AND its codings so the undo
        # of a code.create does not orphan segments.
        for tbl, col, pk in (
            ("code_name", "cid", "cid"),
            ("code_text", "cid", "ctid"),
            ("code_av", "cid", "avid"),
            ("code_image", "cid", "imid"),
        ):
            await session.execute(text(f"DELETE FROM {tbl} WHERE {col} = :v"), {"v": cid})
            await _sync_capture(session, tbl, "delete", pk, cid)
        return f"deleted code #{cid} (and its codings)"
    await _insert_row(session, "code_name", detail)
    await _sync_capture(session, "code_name", "insert", "cid", cid)
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


async def _revert_entity_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """case.delete / journal.delete: re-insert the row (undo) or delete it
    again (redo, mirroring the repository's delete path)."""
    action = row["action"]
    detail = _detail(row)
    if action == "case.delete":
        table, pk = "cases", "caseid"
    elif action == "journal.delete":
        table, pk = "journal", "jid"
    else:
        raise UnsupportedAction(f"no undo for {action}")
    row_id = row.get("entity_id")
    if not row_id:
        raise UnsupportedAction("missing entity id")
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
        raise UnsupportedAction(f"missing {table} row")
    try:
        await _insert_row(session, table, row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore {table} #{row_id}: {err}") from err
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


async def _revert_update(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """annotation.update / journal.update / case.update: restore the
    pre-edit values recorded in the detail."""
    action = row["action"]
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


async def _revert_source_update(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """source.update (rename/memo): restore the before values (undo) or the
    after values (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id") or row.get("source_id")
    if not source_id:
        raise UnsupportedAction("missing source id")
    name = detail.get("before_name") if undo else detail.get("after_name")
    memo = detail.get("before_memo") if undo else detail.get("after_memo")
    await session.execute(
        text("UPDATE source SET name = :n, memo = :m WHERE id = :id"),
        {"n": name, "m": memo, "id": source_id},
    )
    await _sync_capture(session, "source", "update", "id", source_id)
    return f"source #{source_id} {'restored' if undo else 're-applied'}"


async def _revert_code_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
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


async def _revert_source_import(session: AsyncSession, row: dict, *, undo: bool) -> str:
    source_id = row.get("entity_id")
    if not source_id:
        raise UnsupportedAction("missing source id")
    if undo:
        # Remove the source AND everything attached to it (codings,
        # annotations, case links) so the undo does not orphan rows.
        for tbl, col in (
            ("code_text", "fid"),
            ("code_image", "id"),
            ("code_av", "id"),
            ("annotation", "fid"),
            ("case_text", "fid"),
        ):
            await session.execute(text(f"DELETE FROM {tbl} WHERE {col} = :v"), {"v": source_id})
        await _delete_by_id(session, "source", "id", source_id)
        return f"deleted source #{source_id}"
    raise UnsupportedAction("cannot redo a source import")


async def _revert_transcript(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """transcript.create / transcript.delete: companion row + av_text_id link.

    The detail carries the full companion ``source`` row, so both directions
    are invertible: undo of create removes the companion, undo of delete
    re-inserts it and re-links the media source.
    """
    action = row["action"]
    detail = _detail(row)
    trans_id = row.get("entity_id")
    media_id = row.get("source_id")
    if not trans_id or not media_id:
        raise UnsupportedAction("missing transcript ids")
    companion = detail.get("companion") or detail.get("row")
    if action == "transcript.create":
        if undo:
            await session.execute(
                text("UPDATE source SET av_text_id = NULL WHERE id = :v"), {"v": media_id}
            )
            await _delete_by_id(session, "source", "id", trans_id)
            return f"deleted transcript #{trans_id}"
        if not isinstance(companion, dict):
            raise UnsupportedAction("missing companion row")
        await _insert_row(session, "source", companion)
        await _sync_capture(session, "source", "insert", "id", trans_id)
        await session.execute(
            text("UPDATE source SET av_text_id = :t WHERE id = :v"),
            {"t": trans_id, "v": media_id},
        )
        return f"restored transcript #{trans_id}"
    if action == "transcript.delete":
        if undo:
            if not isinstance(companion, dict):
                raise UnsupportedAction("missing companion row")
            await _insert_row(session, "source", companion)
            await _sync_capture(session, "source", "insert", "id", trans_id)
            await session.execute(
                text("UPDATE source SET av_text_id = :t WHERE id = :v"),
                {"t": trans_id, "v": media_id},
            )
            return f"restored transcript #{trans_id}"
        await session.execute(
            text("UPDATE source SET av_text_id = NULL WHERE id = :v"), {"v": media_id}
        )
        await _delete_by_id(session, "source", "id", trans_id)
        return f"deleted transcript #{trans_id}"
    raise UnsupportedAction(f"no undo for {action}")


_TREE_FIELDS = ("catid", "supercid", "position")


async def _revert_code_tree_move(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """code.move / code.promote / code.demote: restore the pre-move
    catid/supercid/position (undo) or the post-move values (redo)."""
    detail = _detail(row)
    cid = row.get("entity_id") or detail.get("cid")
    if not cid:
        raise UnsupportedAction("missing cid")
    before = detail.get("before")
    after = detail.get("after")
    target = before if undo else after
    if not isinstance(target, dict):
        raise UnsupportedAction("missing before/after row")
    await _update_row(session, "code_name", "cid", cid, {f: target.get(f) for f in _TREE_FIELDS})
    await _sync_capture(session, "code_name", "update", "cid", cid)
    return f"code #{cid} tree position {'restored' if undo else 're-applied'}"


async def _revert_category_tree_move(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """category.move / category.promote / category.demote."""
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise UnsupportedAction("missing catid")
    before = detail.get("before")
    after = detail.get("after")
    target = before if undo else after
    if not isinstance(target, dict):
        raise UnsupportedAction("missing before/after row")
    await _update_row(session, "code_cat", "catid", catid, {f: target.get(f) for f in _TREE_FIELDS})
    await _sync_capture(session, "code_cat", "update", "catid", catid)
    return f"category #{catid} tree position {'restored' if undo else 're-applied'}"


def _coding_table_for(row: dict) -> tuple[str, str]:
    if "ctid" in row:
        return "code_text", "ctid"
    if "avid" in row:
        return "code_av", "avid"
    if "imid" in row:
        return "code_image", "imid"
    raise UnsupportedAction("coding row carries no primary key")


async def _revert_code_merge(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """code.merge: recreate the merged-away code and move its codings back
    (undo); move them to the target again and drop the code (redo)."""
    detail = _detail(row)
    from_cid = _ensure(detail, "from_cid")
    target_cid = row.get("entity_id") or detail.get("target_cid")
    from_code = detail.get("from_code")
    from_rows = detail.get("from_rows") or []
    subcodes = detail.get("subcodes") or []
    if not isinstance(from_code, dict):
        raise UnsupportedAction("missing from_code row")
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


async def _revert_category_create(session: AsyncSession, row: dict, *, undo: bool) -> str:
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise UnsupportedAction("missing catid")
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
        raise UnsupportedAction("missing category row")
    await _insert_row(session, "code_cat", row_dict)
    await _sync_capture(session, "code_cat", "insert", "catid", catid)
    return f"restored category #{catid}"


async def _revert_category_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise UnsupportedAction("missing catid")
    if undo:
        row_dict = detail.get("row") or detail
        if not isinstance(row_dict, dict) or not row_dict.get("catid"):
            raise UnsupportedAction("missing category row")
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


async def _revert_category_rename(session: AsyncSession, row: dict, *, undo: bool) -> str:
    detail = _detail(row)
    catid = row.get("entity_id")
    if not catid:
        raise UnsupportedAction("missing catid")
    name = detail.get("old_name") if undo else detail.get("new_name")
    if not name:
        raise UnsupportedAction("missing name")
    await session.execute(
        text("UPDATE code_cat SET name = :n WHERE catid = :id"), {"n": name, "id": catid}
    )
    await _sync_capture(session, "code_cat", "update", "catid", catid)
    return f"category #{catid} renamed to {name!r}"


async def _revert_category_merge(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """category.merge: recreate the merged-away category and move its codes
    and subcategories back (undo); re-apply the merge (redo)."""
    detail = _detail(row)
    from_catid = _ensure(detail, "from_catid")
    target_catid = row.get("entity_id") or detail.get("target_catid")
    from_category = detail.get("from_category")
    codes = detail.get("codes") or []
    subcats = detail.get("subcats") or []
    if undo:
        if not isinstance(from_category, dict):
            raise UnsupportedAction("missing from_category row")
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


async def _revert_case_link(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """case.link_file / case.link_span / case.unlink_file: invert the
    case_text insert/delete using the captured rows."""
    action = row["action"]
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
        raise UnsupportedAction("missing case_text id")
    if undo:
        await _delete_by_id(session, "case_text", "id", row_id)
        return f"deleted case_text #{row_id}"
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise UnsupportedAction("missing case_text row")
    await _insert_row(session, "case_text", row_dict)
    await _sync_capture(session, "case_text", "insert", "id", row_id)
    return f"restored case_text #{row_id}"


async def _revert_attribute_type(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """attribute.create / attribute.delete (attribute_type rows)."""
    action = row["action"]
    detail = _detail(row)
    name = detail.get("name")
    if not name:
        raise UnsupportedAction("missing attribute type name")
    row_dict = detail.get("row") or detail
    if action == "attribute.create":
        if undo:
            # Mirror delete_type: the type and all its values go away.
            await session.execute(text("DELETE FROM attribute WHERE name = :v"), {"v": name})
            await _delete_by_id(session, "attribute_type", "name", name)
            return f"deleted attribute type {name!r}"
        if not isinstance(row_dict, dict) or not row_dict.get("name"):
            raise UnsupportedAction("missing attribute type row")
        await _insert_row(session, "attribute_type", row_dict)
        await _sync_capture(session, "attribute_type", "insert", "name", name)
        return f"restored attribute type {name!r}"
    if action == "attribute.delete":
        if undo:
            if not isinstance(row_dict, dict) or not row_dict.get("name"):
                raise UnsupportedAction("missing attribute type row")
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


async def _revert_attribute_set(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """attribute.set_value: restore the previous value (undo) or re-apply
    the recorded one (redo). The ``before`` row is None for first-time
    assignments."""
    detail = _detail(row)
    before = detail.get("before")
    after = detail.get("after")
    if not isinstance(after, dict) or not after.get("attrid"):
        raise UnsupportedAction("missing attribute row")
    if undo:
        await _delete_by_id(session, "attribute", "attrid", after["attrid"])
        if isinstance(before, dict) and before.get("attrid"):
            await _insert_row(session, "attribute", before)
        return "attribute value restored"
    if isinstance(before, dict) and before.get("attrid"):
        await _delete_by_id(session, "attribute", "attrid", before["attrid"])
    await _insert_row(session, "attribute", after)
    return "attribute value re-applied"


async def _revert_link(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """link.create / link.delete: invert the link insert/delete."""
    action = row["action"]
    detail = _detail(row)
    row_dict = detail.get("row") or detail
    link_id = row.get("entity_id") or row_dict.get("id")
    if not link_id:
        raise UnsupportedAction("missing link id")
    if (action == "link.create") == undo:
        await _delete_by_id(session, "link", "id", link_id)
        return f"deleted link #{link_id}"
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise UnsupportedAction("missing link row")
    try:
        await _insert_row(session, "link", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore link #{link_id}: {err}") from err
    await _sync_capture(session, "link", "insert", "id", link_id)
    return f"restored link #{link_id}"


async def _revert_comment(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """comment.create / comment.update / comment.delete."""
    action = row["action"]
    detail = _detail(row)
    comment_id = row.get("entity_id")
    if not comment_id:
        raise UnsupportedAction("missing comment id")
    if action == "comment.update":
        body = detail.get("old_body") if undo else detail.get("new_body")
        if body is None:
            raise UnsupportedAction("missing comment body")
        await session.execute(
            text("UPDATE comment SET body = :b WHERE id = :id"),
            {"b": body, "id": comment_id},
        )
        await _sync_capture(session, "comment", "update", "id", comment_id)
        return f"comment #{comment_id} body {'restored' if undo else 're-applied'}"
    row_dict = detail.get("row") or detail
    if (action == "comment.create") == undo:
        await _delete_by_id(session, "comment", "id", comment_id)
        return f"deleted comment #{comment_id}"
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise UnsupportedAction("missing comment row")
    try:
        await _insert_row(session, "comment", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore comment #{comment_id}: {err}") from err
    await _sync_capture(session, "comment", "insert", "id", comment_id)
    return f"restored comment #{comment_id}"


async def _revert_creative(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """creative.create / creative.update / creative.delete."""
    action = row["action"]
    detail = _detail(row)
    item_id = row.get("entity_id")
    if not item_id:
        raise UnsupportedAction("missing creative item id")
    if action == "creative.update":
        before = detail.get("before")
        if not isinstance(before, dict):
            raise UnsupportedAction("missing before row")
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
        raise UnsupportedAction("missing creative item row")
    try:
        await _insert_row(session, "creative_item", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore creative item #{item_id}: {err}") from err
    await _sync_capture(session, "creative_item", "insert", "id", item_id)
    return f"restored creative item #{item_id}"


async def _revert_creative_promote(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """creative.promote: remove the created code + its coding (undo) or
    restore both (redo) from the captured rows."""
    detail = _detail(row)
    code = detail.get("code")
    coding = detail.get("coding")
    cid = (code or {}).get("cid") or detail.get("cid")
    if not cid:
        raise UnsupportedAction("missing promoted code id")
    if undo:
        await _delete_by_id(session, "code_name", "cid", cid)
        if isinstance(coding, dict) and coding.get("ctid"):
            await _delete_by_id(session, "code_text", "ctid", coding["ctid"])
        return f"deleted code #{cid} and its coding"
    if not isinstance(code, dict) or not code.get("cid"):
        raise UnsupportedAction("missing promoted code row")
    try:
        await _insert_row(session, "code_name", code)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore code #{cid}: {err}") from err
    await _sync_capture(session, "code_name", "insert", "cid", cid)
    if isinstance(coding, dict) and coding.get("ctid"):
        await _insert_row(session, "code_text", coding)
        await _sync_capture(session, "code_text", "insert", "ctid", coding["ctid"])
    return f"restored code #{cid} and its coding"


#: Actions that record a single audit row for an unbounded set of created
#: rows. They stay unsupported on purpose — the message says so instead of
#: a bare "no undo".
_NOT_INVERTIBLE_MESSAGES = {
    "interchange.import": "Import actions cannot be undone — delete the affected rows manually",
    "scrape.import": "Import actions cannot be undone — delete the affected rows manually",
    "coding.autocode": "Autocode actions cannot be undone — delete the affected codings manually",
    "transcribe.start": "Transcription cannot be undone — delete the transcript source manually",
}


async def apply(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """Apply the inverse (undo=True) or re-apply (undo=False) of one audit row."""
    action = row.get("action") or ""
    if action in ("coding.create", "coding.delete"):
        return await _revert_coding(session, row, undo=undo)
    if action == "coding.update":
        return await _revert_coding_update(session, row, undo=undo)
    if action in ("annotation.create", "annotation.delete"):
        return await _revert_annotation(session, row, undo=undo)
    if action == "source.edit":
        return await _revert_edit(session, row, undo=undo)
    if action == "source.update":
        return await _revert_source_update(session, row, undo=undo)
    if action == "code.rename":
        return await _revert_rename(session, row, undo=undo)
    if action == "code.create":
        return await _revert_code_create(session, row, undo=undo)
    if action == "code.delete":
        return await _revert_code_delete(session, row, undo=undo)
    if action in ("code.move", "code.promote", "code.demote"):
        return await _revert_code_tree_move(session, row, undo=undo)
    if action == "code.merge":
        return await _revert_code_merge(session, row, undo=undo)
    if action == "category.create":
        return await _revert_category_create(session, row, undo=undo)
    if action == "category.delete":
        return await _revert_category_delete(session, row, undo=undo)
    if action == "category.rename":
        return await _revert_category_rename(session, row, undo=undo)
    if action in ("category.move", "category.promote", "category.demote"):
        return await _revert_category_tree_move(session, row, undo=undo)
    if action == "category.merge":
        return await _revert_category_merge(session, row, undo=undo)
    if action in ("case.create", "journal.create"):
        return await _revert_entity_create(session, row, undo=undo)
    if action in ("case.delete", "journal.delete"):
        return await _revert_entity_delete(session, row, undo=undo)
    if action in ("annotation.update", "journal.update", "case.update"):
        return await _revert_update(session, row, undo=undo)
    if action in ("case.link_file", "case.link_span", "case.unlink_file"):
        return await _revert_case_link(session, row, undo=undo)
    if action in ("attribute.create", "attribute.delete"):
        return await _revert_attribute_type(session, row, undo=undo)
    if action == "attribute.set_value":
        return await _revert_attribute_set(session, row, undo=undo)
    if action in ("link.create", "link.delete"):
        return await _revert_link(session, row, undo=undo)
    if action in ("comment.create", "comment.update", "comment.delete"):
        return await _revert_comment(session, row, undo=undo)
    if action in ("creative.create", "creative.update", "creative.delete"):
        return await _revert_creative(session, row, undo=undo)
    if action == "creative.promote":
        return await _revert_creative_promote(session, row, undo=undo)
    if action in ("transcript.create", "transcript.delete"):
        return await _revert_transcript(session, row, undo=undo)
    if action == "source.import":
        return await _revert_source_import(session, row, undo=undo)
    message = _NOT_INVERTIBLE_MESSAGES.get(action)
    if message:
        raise UnsupportedAction(message)
    raise UnsupportedAction(f"no undo for {action}")
