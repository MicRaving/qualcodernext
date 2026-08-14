"""Undo / redo for audit-log actions (edit review).

Each supported action records enough detail to invert itself: full rows
for coding/annotation inserts and deletes, before/after text for edits,
old/new names for renames, before/after row snapshots for updates and
tree moves, full rows + captured children for merges, transcript
companions, source deletes/replaces, and the row-based families
(filters, stored SQL, dictionaries, code sets, R scripts, QTT sheets and
items, graph nodes/lines, references, coders, bookmarks, pseudonyms,
speaker marks and sync toggles). ``undo`` applies the inverse; ``redo``
applies the inverse of the inverse (i.e. re-applies the original change).

Unsupported actions raise ``UnsupportedAction`` — the UI hides the undo
button for those. Interchange/scrape imports, compaction, report-data
preparation and finished background jobs are deliberately not
invertible; the raised message says why instead of a bare "no undo".
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
    raise UnsupportedAction("cannot redo a source import/link — import the file again")


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


#: The graph item/line tables and their primary keys (row-pair inversion).
_GRAPH_PKS = {
    "gr_cdct_text_item": "gtextid",
    "gr_case_text_item": "gcaseid",
    "gr_file_text_item": "gfileid",
    "gr_memo_item": "gmemoid",
    "gr_cdct_line_item": "glineid",
    "gr_free_line_item": "gflineid",
}

_GRAPH_CHILD_TABLES = (
    "gr_cdct_text_item",
    "gr_case_text_item",
    "gr_file_text_item",
    "gr_free_text_item",
    "gr_memo_item",
    "gr_cdct_line_item",
    "gr_free_line_item",
)


async def _revert_source_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """source.delete: re-insert the full row plus every attached row (undo);
    delete again with the same cascade (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    if not source_id:
        raise UnsupportedAction("missing source id")
    if undo:
        source_row = detail.get("row")
        if not isinstance(source_row, dict) or not source_row.get("id"):
            raise UnsupportedAction("missing source row")
        try:
            await _insert_row(session, "source", source_row)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore source #{source_id}: {err}") from err
        await _sync_capture(session, "source", "insert", "id", source_id)
        for table, _pk in (
            ("code_text", "ctid"),
            ("code_image", "imid"),
            ("code_av", "avid"),
            ("annotation", "anid"),
            ("case_text", "id"),
            ("attribute", "attrid"),
        ):
            for r in detail.get(table) or []:
                try:
                    await _insert_row(session, table, r)
                except Exception as err:
                    raise UnsupportedAction(f"cannot restore {table} row: {err}") from err
        # Re-link media sources whose transcript pointer was cleared.
        for media_id in detail.get("av_text_pointers") or []:
            await session.execute(
                text("UPDATE source SET av_text_id = :t WHERE id = :v"),
                {"t": source_id, "v": media_id},
            )
        return f"restored source #{source_id}"
    # Redo: mirror SourceRepository.delete_source's cascade.
    for table, col in (
        ("code_text", "fid"),
        ("code_image", "id"),
        ("code_av", "id"),
        ("annotation", "fid"),
        ("case_text", "fid"),
        ("attribute", "id"),
    ):
        await session.execute(text(f"DELETE FROM {table} WHERE {col} = :v"), {"v": source_id})
    await session.execute(
        text("UPDATE source SET av_text_id = NULL WHERE av_text_id = :v"), {"v": source_id}
    )
    await _delete_by_id(session, "source", "id", source_id)
    return f"deleted source #{source_id} (and its codings/annotations/links)"


async def _revert_source_link_fix(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """source.link_fix: restore the previous mediapath (undo) or re-apply the
    new one (redo). The bulk variant carries one [sid, old, new] triple per
    updated source."""
    detail = _detail(row)
    if detail.get("bulk"):
        triples = detail.get("rows") or []
        if not triples:
            raise UnsupportedAction("bulk link rename recorded no per-source rows")
        for sid, old, new in triples:
            target = old if undo else new
            await session.execute(
                text("UPDATE source SET mediapath = :mp WHERE id = :v"),
                {"mp": target, "v": sid},
            )
        return f"{'restored' if undo else 're-applied'} {len(triples)} mediapath(s)"
    source_id = row.get("entity_id")
    if not source_id:
        raise UnsupportedAction("missing source id")
    old = detail.get("old")
    new = detail.get("new")
    if old is None or new is None:
        raise UnsupportedAction("missing mediapath before/after")
    await session.execute(
        text("UPDATE source SET mediapath = :mp WHERE id = :v"),
        {"mp": old if undo else new, "v": source_id},
    )
    await _sync_capture(session, "source", "update", "id", source_id)
    return f"source #{source_id} mediapath {'restored' if undo else 're-applied'}"


async def _revert_source_replace(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """source.replace: restore the pre-replacement source row and put every
    captured segment (codings/annotations/case links) back at its old
    position. Redo is not invertible — the replacement file bytes are gone."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    if not source_id:
        raise UnsupportedAction("missing source id")
    if not undo:
        raise UnsupportedAction(
            "cannot redo a source replacement — upload the replacement file again"
        )
    before = detail.get("before_source")
    if not isinstance(before, dict) or not before.get("id"):
        raise UnsupportedAction("missing before source row")
    await _update_row(session, "source", "id", source_id, before)
    await _sync_capture(session, "source", "update", "id", source_id)
    restored = 0
    for table, pk in (("code_text", "ctid"), ("annotation", "anid"), ("case_text", "id")):
        for r in detail.get(table) or []:
            action = await _restore_row(session, table, pk, r)
            await _sync_capture(session, table, action, pk, r.get(pk))
            restored += 1
    return f"restored source #{source_id} and {restored} re-anchored segment(s)"


async def _revert_transcribe_start(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """transcribe.start: cancel the job while it is still queued/running (the
    transcript source has not been created yet). Finished jobs leave the
    transcript in the project — undo the resulting ``source.import`` row."""
    from qualcoder_api.services.transcription import control_job, get_job

    detail = _detail(row)
    job_id = detail.get("job_id")
    if not job_id:
        raise UnsupportedAction("missing job id")
    if not undo:
        raise UnsupportedAction("cannot redo a transcription start — start the job again from the media file")
    job = get_job(job_id)
    if job is None:
        raise UnsupportedAction(
            "transcription job is gone — delete the transcript source manually"
        )
    state = job.get("state")
    if state in ("queued", "running"):
        control_job(job_id, "cancel")
        return f"cancelled transcription job {job_id}"
    if state == "done":
        raise UnsupportedAction(
            "transcription already finished — undo the source.import row of the "
            "transcript (or delete the transcript source manually)"
        )
    return f"transcription job {job_id} already {state} — nothing to undo"


async def _revert_r_run(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """r.run: cancel the R job while it is queued/running; finished jobs only
    left artifacts under ``r_exchange/out`` (delete those manually)."""
    from qualcoder_api.services import r_service

    detail = _detail(row)
    job_id = detail.get("job_id")
    if not job_id:
        raise UnsupportedAction("missing job id")
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


def _coding_defaults(row: dict) -> dict:
    """A code_text row with the NOT NULL-ish model fields defaulted (the
    autocode/speaker engines create rows without weight)."""
    out = dict(row)
    out.setdefault("weight", 0)
    out.setdefault("important", 0)
    return out


async def _revert_autocode(session: AsyncSession, row: dict, *, undo: bool) -> str:
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
            raise UnsupportedAction(
                "this autocode run recorded no created codings — delete the affected codings manually"
            )
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


async def _revert_coding_undo(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """coding.undo (the user's own ctrl+z): the detail carries the restored
    rows, so undoing the undo deletes them again and redoing re-inserts them."""
    detail = _detail(row)
    items = detail.get("items") or []
    if not items:
        raise UnsupportedAction("missing restored coding rows")
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


async def _revert_code_memo(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """code.memo (MCP): restore the previous memo (undo) or the new one (redo)."""
    detail = _detail(row)
    cid = row.get("entity_id") or detail.get("cid")
    if not cid:
        raise UnsupportedAction("missing cid")
    memo = detail.get("old_memo") if undo else detail.get("memo")
    if memo is None:
        raise UnsupportedAction("missing memo value")
    await session.execute(
        text("UPDATE code_name SET memo = :m WHERE cid = :v"), {"m": memo, "v": cid}
    )
    await _sync_capture(session, "code_name", "update", "cid", cid)
    return f"code #{cid} memo {'restored' if undo else 're-applied'}"


async def _revert_bookmark(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """bookmark.set: restore the five bookmark columns of the project row
    from the captured before/after snapshots."""
    detail = _detail(row)
    target = detail.get("before") if undo else detail.get("after")
    if not isinstance(target, dict):
        raise UnsupportedAction("missing before/after bookmark values")
    columns = (
        "bookmarkfile",
        "bookmarkpos",
        "avbookmarkfile",
        "avbookmarkmsec",
        "avbookmarktextpos",
    )
    # The repository returns camel-case response keys; accept both forms.
    aliases = {
        "bookmarkfile": "bookmark_file_id",
        "bookmarkpos": "bookmark_pos",
        "avbookmarkfile": "av_bookmark_file_id",
        "avbookmarkmsec": "av_bookmark_msec",
        "avbookmarktextpos": "av_bookmark_textpos",
    }
    params: dict = {}
    for column in columns:
        if column in target:
            params[column] = target.get(column)
        else:
            params[column] = target.get(aliases[column])
    assignments = ", ".join(f"{c} = :{c}" for c in columns)
    await session.execute(text(f"UPDATE project SET {assignments}"), params)
    return f"bookmark {'restored' if undo else 're-applied'}"


async def _revert_speakers_mark(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """speakers.mark: delete the codes and codings this run created (undo).
    Codes that existed before the run (or still carry codings from earlier
    runs) are kept. Redo needs the detection re-run."""
    detail = _detail(row)
    if detail.get("too_many_codings"):
        raise UnsupportedAction(
            "this speaker run created more than 5000 codings — delete them manually"
        )
    code_ids = detail.get("created_code_ids") or []
    ctids = detail.get("created_ctids") or []
    if not undo:
        raise UnsupportedAction("cannot redo speaker marking — run the speaker detection again")
    if ctids:
        placeholders, params = _in_params(ctids)
        await session.execute(
            text(f"DELETE FROM code_text WHERE ctid IN ({placeholders})"), params
        )
    removed_codes = 0
    for cid in code_ids:
        leftover = (
            await session.execute(text("SELECT 1 FROM code_text WHERE cid = :v LIMIT 1"), {"v": cid})
        ).first()
        if leftover is None:
            await session.execute(
                text("DELETE FROM code_av WHERE cid = :v"), {"v": cid}
            )
            await session.execute(
                text("DELETE FROM code_image WHERE cid = :v"), {"v": cid}
            )
            await _delete_by_id(session, "code_name", "cid", cid)
            removed_codes += 1
    return (
        f"deleted {len(ctids)} speaker coding(s) and {removed_codes} "
        f"newly created speaker code(s)"
    )


async def _revert_pseudonym(session: AsyncSession, row: dict, *, undo: bool, project_path: str | None) -> str:
    """pseudonym.add / pseudonym.delete: invert the pseudonyms.json pair."""
    from qualcoder_api.services import pseudonyms

    action = row["action"]
    detail = _detail(row)
    original = detail.get("original")
    if not original:
        raise UnsupportedAction("missing pseudonym original")
    if not project_path:
        raise UnsupportedAction("no project is open — cannot restore pseudonyms.json")
    pseudonym = detail.get("pseudonym")
    if action == "pseudonym.add":
        if undo:
            pseudonyms.delete_pseudonym(project_path, original)
            return f"deleted pseudonym {original!r}"
        if not pseudonym:
            raise UnsupportedAction("missing pseudonym value")
        try:
            pseudonyms.add_pseudonym(project_path, original, pseudonym)
        except ValueError as err:
            raise UnsupportedAction(f"cannot restore pseudonym: {err}") from err
        return f"restored pseudonym {original!r}"
    if action == "pseudonym.delete":
        if undo:
            if not pseudonym:
                raise UnsupportedAction("missing pseudonym value")
            try:
                pseudonyms.add_pseudonym(project_path, original, pseudonym)
            except ValueError as err:
                raise UnsupportedAction(f"cannot restore pseudonym: {err}") from err
            return f"restored pseudonym {original!r}"
        pseudonyms.delete_pseudonym(project_path, original)
        return f"deleted pseudonym {original!r}"
    raise UnsupportedAction(f"no undo for {action}")


async def _revert_reference_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """reference.delete: re-insert the captured ris rows and re-link the
    sources that pointed at the reference (undo); delete again (redo)."""
    detail = _detail(row)
    risid = row.get("entity_id")
    if not risid:
        raise UnsupportedAction("missing risid")
    if undo:
        ris_rows = detail.get("rows") or []
        for r in ris_rows:
            await _insert_row(session, "ris", r)
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


async def _revert_reference_attach(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """reference.attach: unlink and delete the imported attachment source
    (undo); re-insert it and re-link (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    if not source_id:
        raise UnsupportedAction("missing source id")
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
        raise UnsupportedAction("missing source row")
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


async def _revert_reference_detach(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """reference.detach: re-link the source to its reference (undo) or unlink
    it again (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    risid = detail.get("risid")
    if not source_id or not risid:
        raise UnsupportedAction("missing source/ris id")
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


async def _revert_row_pair(
    session: AsyncSession,
    row: dict,
    *,
    undo: bool,
    table: str,
    pk: str,
    create_actions: tuple[str, ...],
    delete_actions: tuple[str, ...] = (),
) -> str:
    """Generic create/delete inversion for single-row entities: the detail
    carries the full ``row``, the audit row's ``entity_id`` (or the row's own
    pk) identifies it. Undo of a create deletes the row; undo of a delete
    re-inserts it."""
    action = row["action"]
    detail = _detail(row)
    row_dict = detail.get("row")
    if row_dict is None and detail.get(pk) is not None:
        # Some actions record the row as the whole detail (e.g.
        # dictionary.entry_add, r_script.delete).
        row_dict = detail
    row_id = row.get("entity_id")
    if row_id is None and isinstance(row_dict, dict):
        row_id = row_dict.get(pk)
    if row_id is None:
        raise UnsupportedAction(f"missing {pk}")
    if (action in create_actions) == undo:
        await _delete_by_id(session, table, pk, row_id)
        return f"deleted {table} #{row_id}"
    if not isinstance(row_dict, dict) or not row_dict.get(pk):
        raise UnsupportedAction(f"missing {table} row")
    try:
        await _insert_row(session, table, row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore {table} #{row_id}: {err}") from err
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


async def _revert_row_update(
    session: AsyncSession, row: dict, *, undo: bool, table: str, pk: str
) -> str:
    """Generic update inversion: the detail carries full ``before``/``after``
    rows; undo restores the before state, redo re-applies the after state."""
    detail = _detail(row)
    target = detail.get("before") if undo else detail.get("after")
    if not isinstance(target, dict):
        raise UnsupportedAction("missing before/after row")
    pk_value = target.get(pk) or row.get("entity_id")
    if pk_value is None:
        raise UnsupportedAction(f"missing {pk}")
    await _update_row(session, table, pk, pk_value, target)
    await _sync_capture(session, table, "update", pk, pk_value)
    return f"{table} #{pk_value} {'restored' if undo else 're-applied'}"


async def _revert_coder(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """coder.create / coder.delete / coder.rename / coder.visibility: the
    coder list lives in the per-machine settings; visibility lives in the
    project's ``coder_names`` table."""
    from qualcoder_api.persistence import tables
    from qualcoder_api.services.user_settings import get_coders, set_coders

    action = row["action"]
    detail = _detail(row)
    if action == "coder.create":
        name = detail.get("name")
        if not name:
            raise UnsupportedAction("missing coder name")
        names = get_coders()
        if undo:
            if name in names:
                set_coders([n for n in names if n != name])
            return f"removed coder {name!r} from the coder list"
        if name not in names:
            set_coders([*names, name])
        return f"re-added coder {name!r} to the coder list"
    if action == "coder.delete":
        name = detail.get("name")
        if not name:
            raise UnsupportedAction("missing coder name")
        names = get_coders()
        if undo:
            if name not in names:
                set_coders([*names, name])
            message = f"restored coder {name!r} to the coder list"
            if detail.get("reassign_to"):
                message += " (their records stay reassigned)"
            return message
        if name in names:
            set_coders([n for n in names if n != name])
        return f"removed coder {name!r} from the coder list"
    if action == "coder.rename":
        old = detail.get("from")
        new = detail.get("to")
        if not old or not new:
            raise UnsupportedAction("missing coder names")
        source, target = (new, old) if undo else (old, new)
        names = get_coders()
        renamed = [target if n == source else n for n in names]
        set_coders(renamed)
        for table in tables.OWNER_TABLES:
            await session.execute(
                text(f'UPDATE "{table}" SET owner = :to WHERE owner = :from'),
                {"to": target, "from": source},
            )
        await session.execute(
            text("UPDATE coder_names SET name = :to WHERE name = :from"),
            {"to": target, "from": source},
        )
        return f"coder {source!r} {'renamed back to' if undo else 'renamed to'} {target!r}"
    if action == "coder.visibility":
        name = detail.get("name")
        if not name:
            raise UnsupportedAction("missing coder name")
        applied = 1 if detail.get("visible") else 0
        if undo:
            before = detail.get("before")
            if before is None:
                await session.execute(
                    text("DELETE FROM coder_names WHERE name = :n"), {"n": name}
                )
            else:
                await session.execute(
                    text(
                        "INSERT INTO coder_names (name, visibility) VALUES (:n, :v) "
                        "ON CONFLICT(name) DO UPDATE SET visibility = :v"
                    ),
                    {"n": name, "v": 1 if before else 0},
                )
            return f"coder {name!r} visibility restored"
        await session.execute(
            text(
                "INSERT INTO coder_names (name, visibility) VALUES (:n, :v) "
                "ON CONFLICT(name) DO UPDATE SET visibility = :v"
            ),
            {"n": name, "v": applied},
        )
        return f"coder {name!r} visibility re-applied"
    raise UnsupportedAction(f"no undo for {action}")


async def _revert_sync_toggle(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """sync.toggle: restore the previously stored sync switch state."""
    from qualcoder_api.services.user_settings import save_sync_settings

    detail = _detail(row)
    enabled = detail.get("before") if undo else detail.get("enabled")
    if enabled is None:
        raise UnsupportedAction("missing sync enabled state")
    save_sync_settings(bool(enabled))
    return f"sync {'restored' if undo else 're-applied'} (enabled={bool(enabled)})"


async def _revert_dictionary(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """dictionary.create / dictionary.update / entry_add / entry_delete."""
    action = row["action"]
    detail = _detail(row)
    if action == "dictionary.update":
        dict_id = row.get("entity_id") or detail.get("id")
        if not dict_id:
            raise UnsupportedAction("missing dictionary id")
        name = detail.get("old_name") if undo else detail.get("new_name")
        if not name:
            raise UnsupportedAction("missing dictionary name")
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


async def _revert_dictionary_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """dictionary.delete: restore the dictionary row plus its entries (undo);
    delete again (redo)."""
    detail = _detail(row)
    dict_id = row.get("entity_id")
    if not dict_id:
        raise UnsupportedAction("missing dictionary id")
    if undo:
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("id"):
            raise UnsupportedAction("missing dictionary row")
        try:
            await _insert_row(session, "dictionary", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore dictionary #{dict_id}: {err}") from err
        await _sync_capture(session, "dictionary", "insert", "id", dict_id)
        for entry in detail.get("entries") or []:
            await _insert_row(session, "dictionary_entry", entry)
        return f"restored dictionary #{dict_id} with its entries"
    await session.execute(
        text("DELETE FROM dictionary_entry WHERE dict_id = :v"), {"v": dict_id}
    )
    await _delete_by_id(session, "dictionary", "id", dict_id)
    return f"deleted dictionary #{dict_id}"


async def _revert_dictionary_import(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """dictionary.import: undo deletes the imported dictionary (and its
    entries); redo is not invertible without re-importing."""
    if undo:
        dict_id = row.get("entity_id")
        if not dict_id:
            raise UnsupportedAction("missing dictionary id")
        await session.execute(
            text("DELETE FROM dictionary_entry WHERE dict_id = :v"), {"v": dict_id}
        )
        await _delete_by_id(session, "dictionary", "id", dict_id)
        return f"deleted imported dictionary #{dict_id}"
    raise UnsupportedAction("cannot redo a dictionary import — re-import the dictionary file")


async def _revert_code_set(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """code_set.create / rename / delete (with members)."""
    action = row["action"]
    detail = _detail(row)
    set_id = row.get("entity_id")
    if not set_id:
        raise UnsupportedAction("missing code set id")
    if action == "code_set.rename":
        name = detail.get("old_name") if undo else detail.get("new_name")
        if not name:
            raise UnsupportedAction("missing code set name")
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
            raise UnsupportedAction("missing code set row")
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
            raise UnsupportedAction("missing code set row")
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


async def _revert_code_set_members(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """code_set.members_add / members_remove: invert the member rows."""
    detail = _detail(row)
    set_id = row.get("entity_id")
    if not set_id:
        raise UnsupportedAction("missing code set id")
    is_add = row["action"] == "code_set.members_add"
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


async def _revert_r_script(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """r_script.create / update / delete."""
    action = row["action"]
    if action == "r_script.update":
        return await _revert_row_update(session, row, undo=undo, table="r_script", pk="id")
    return await _revert_row_pair(
        session, row, undo=undo, table="r_script", pk="id",
        create_actions=("r_script.create",), delete_actions=("r_script.delete",),
    )


async def _revert_qtt_sheet_create(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """qtt.create: remove the worksheet (and its items) or restore it."""
    detail = _detail(row)
    sheet_id = row.get("entity_id")
    if not sheet_id:
        raise UnsupportedAction("missing worksheet id")
    if undo:
        await session.execute(text("DELETE FROM qtt_item WHERE sheet_id = :v"), {"v": sheet_id})
        await _delete_by_id(session, "qtt_sheet", "id", sheet_id)
        return f"deleted worksheet #{sheet_id}"
    row_dict = detail.get("row")
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise UnsupportedAction("missing worksheet row")
    try:
        await _insert_row(session, "qtt_sheet", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore worksheet #{sheet_id}: {err}") from err
    await _sync_capture(session, "qtt_sheet", "insert", "id", sheet_id)
    return f"restored worksheet #{sheet_id}"


async def _revert_qtt_sheet_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """qtt.delete: restore the worksheet plus its items (undo) or remove them
    again (redo)."""
    detail = _detail(row)
    sheet_id = row.get("entity_id")
    if not sheet_id:
        raise UnsupportedAction("missing worksheet id")
    if undo:
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("id"):
            raise UnsupportedAction("missing worksheet row")
        try:
            await _insert_row(session, "qtt_sheet", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore worksheet #{sheet_id}: {err}") from err
        await _sync_capture(session, "qtt_sheet", "insert", "id", sheet_id)
        for item in detail.get("items") or []:
            await _insert_row(session, "qtt_item", item)
        return f"restored worksheet #{sheet_id} with its items"
    await session.execute(text("DELETE FROM qtt_item WHERE sheet_id = :v"), {"v": sheet_id})
    await _delete_by_id(session, "qtt_sheet", "id", sheet_id)
    return f"deleted worksheet #{sheet_id}"


async def _delete_graph_rows(session: AsyncSession, grid: int) -> None:
    for table in _GRAPH_CHILD_TABLES:
        await session.execute(text(f"DELETE FROM {table} WHERE grid = :v"), {"v": grid})


async def _revert_graph_create(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """graph.create (manual or model-generated): remove the whole graph on
    undo; restore the graph row on redo (model graphs are not redoable)."""
    detail = _detail(row)
    grid = row.get("entity_id")
    if not grid:
        raise UnsupportedAction("missing grid")
    if undo:
        await _delete_graph_rows(session, grid)
        await _delete_by_id(session, "graph", "grid", grid)
        return f"deleted graph #{grid} and its items/lines"
    if detail.get("model"):
        raise UnsupportedAction("cannot redo a model-generated graph — run the model generator again")
    row_dict = detail.get("row")
    if not isinstance(row_dict, dict) or not row_dict.get("grid"):
        raise UnsupportedAction("missing graph row")
    try:
        await _insert_row(session, "graph", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore graph #{grid}: {err}") from err
    await _sync_capture(session, "graph", "insert", "grid", grid)
    return f"restored graph #{grid}"


async def _revert_graph_delete(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """graph.delete: restore the graph row and every captured item/line row
    (undo); delete everything again (redo)."""
    detail = _detail(row)
    grid = row.get("entity_id")
    if not grid:
        raise UnsupportedAction("missing grid")
    if undo:
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("grid"):
            raise UnsupportedAction("missing graph row")
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


async def _revert_graph_row(session: AsyncSession, row: dict, *, undo: bool) -> str:
    """graph.item_add / item_delete / line_add / line_delete."""
    action = row["action"]
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
        raise UnsupportedAction(f"missing {pk}")
    is_create = action in ("graph.item_add", "graph.line_add")
    if is_create == undo:
        await _delete_by_id(session, entity, pk, row_id)
        return f"deleted {entity} #{row_id}"
    if not isinstance(row_dict, dict) or not row_dict.get(pk):
        raise UnsupportedAction(f"missing {entity} row")
    try:
        await _insert_row(session, entity, row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore {entity} #{row_id}: {err}") from err
    await _sync_capture(session, entity, "insert", pk, row_id)
    return f"restored {entity} #{row_id}"


#: Actions that record a single audit row for an unbounded set of created
#: rows. They stay unsupported on purpose — the message says so instead of
#: a bare "no undo".
_NOT_INVERTIBLE_MESSAGES = {
    "interchange.import": "Import actions cannot be undone — delete the affected rows manually",
    "scrape.import": "Import actions cannot be undone — delete the affected rows manually",
    "project.compact": "Compaction cannot be undone — the database was rebuilt (checkpoint + VACUUM)",
    "r_script.prepare_report": "Report data was written to r_exchange/in — delete those files manually",
}


async def apply(
    session: AsyncSession, row: dict, *, undo: bool, project_path: str | None = None
) -> str:
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
    if action in ("source.import", "source.link"):
        return await _revert_source_import(session, row, undo=undo)
    if action == "source.delete":
        return await _revert_source_delete(session, row, undo=undo)
    if action == "source.link_fix":
        return await _revert_source_link_fix(session, row, undo=undo)
    if action == "source.replace":
        return await _revert_source_replace(session, row, undo=undo)
    if action == "transcribe.start":
        return await _revert_transcribe_start(session, row, undo=undo)
    if action == "r.run":
        return await _revert_r_run(session, row, undo=undo)
    if action == "coding.autocode":
        return await _revert_autocode(session, row, undo=undo)
    if action == "coding.undo":
        return await _revert_coding_undo(session, row, undo=undo)
    if action == "code.memo":
        return await _revert_code_memo(session, row, undo=undo)
    if action == "bookmark.set":
        return await _revert_bookmark(session, row, undo=undo)
    if action == "speakers.mark":
        return await _revert_speakers_mark(session, row, undo=undo)
    if action in ("pseudonym.add", "pseudonym.delete"):
        return await _revert_pseudonym(session, row, undo=undo, project_path=project_path)
    if action == "reference.delete":
        return await _revert_reference_delete(session, row, undo=undo)
    if action == "reference.attach":
        return await _revert_reference_attach(session, row, undo=undo)
    if action == "reference.detach":
        return await _revert_reference_detach(session, row, undo=undo)
    if action in ("filter.create", "filter.delete"):
        return await _revert_row_pair(
            session, row, undo=undo, table="files_filter", pk="filterid",
            create_actions=("filter.create",), delete_actions=("filter.delete",),
        )
    if action in ("sql.save", "sql.delete"):
        return await _revert_row_pair(
            session, row, undo=undo, table="stored_sql", pk="title",
            create_actions=("sql.save",), delete_actions=("sql.delete",),
        )
    if action in ("coder.create", "coder.delete", "coder.rename", "coder.visibility"):
        return await _revert_coder(session, row, undo=undo)
    if action == "sync.toggle":
        return await _revert_sync_toggle(session, row, undo=undo)
    if action in ("dictionary.create", "dictionary.update", "dictionary.entry_add", "dictionary.entry_delete"):
        return await _revert_dictionary(session, row, undo=undo)
    if action == "dictionary.delete":
        return await _revert_dictionary_delete(session, row, undo=undo)
    if action == "dictionary.import":
        return await _revert_dictionary_import(session, row, undo=undo)
    if action in ("code_set.create", "code_set.rename", "code_set.delete"):
        return await _revert_code_set(session, row, undo=undo)
    if action in ("code_set.members_add", "code_set.members_remove"):
        return await _revert_code_set_members(session, row, undo=undo)
    if action in ("r_script.create", "r_script.update", "r_script.delete"):
        return await _revert_r_script(session, row, undo=undo)
    if action == "qtt.create":
        return await _revert_qtt_sheet_create(session, row, undo=undo)
    if action == "qtt.delete":
        return await _revert_qtt_sheet_delete(session, row, undo=undo)
    if action in ("qtt.item.create", "qtt.item.delete", "qtt.send_segment"):
        return await _revert_row_pair(
            session, row, undo=undo, table="qtt_item", pk="id",
            create_actions=("qtt.item.create", "qtt.send_segment"),
            delete_actions=("qtt.item.delete",),
        )
    if action in ("qtt.update", "qtt.item.update"):
        table = "qtt_sheet" if action == "qtt.update" else "qtt_item"
        return await _revert_row_update(session, row, undo=undo, table=table, pk="id")
    if action == "graph.create":
        return await _revert_graph_create(session, row, undo=undo)
    if action == "graph.delete":
        return await _revert_graph_delete(session, row, undo=undo)
    if action in ("graph.item_add", "graph.item_delete", "graph.line_add", "graph.line_delete"):
        return await _revert_graph_row(session, row, undo=undo)
    if action in ("graph.update", "graph.item_update", "graph.line_update"):
        entity = row.get("entity") or "graph"
        pk = _GRAPH_PKS.get(entity, "grid")
        return await _revert_row_update(session, row, undo=undo, table=entity, pk=pk)
    message = _NOT_INVERTIBLE_MESSAGES.get(action)
    if message:
        raise UnsupportedAction(message)
    raise UnsupportedAction(f"no undo for {action}")
