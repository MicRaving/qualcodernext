"""Case/journal/attribute/link/comment/creative/bookmark/speakers/pseudonym/
reference/coder/sync/dictionary/code_set/r_script/qtt/r_run handlers, plus
the row-pair families (filters, stored SQL, QTT items and updates)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _ensure,
    _in_params,
    _insert_row,
    _missing_data,
    _revert_row_pair,
    _revert_row_update,
    _sync_capture,
    _update_row,
)
from ..registry import register


@register("case.create", "journal.create")
async def _revert_entity_create(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """case.create / journal.create."""
    action = row.get("action") or ""
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


@register("case.delete", "journal.delete")
async def _revert_entity_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """case.delete / journal.delete: re-insert the row (undo) or delete it
    again (redo, mirroring the repository's delete path)."""
    action = row.get("action") or ""
    detail = _detail(row)
    if action == "case.delete":
        table, pk = "cases", "caseid"
    elif action == "journal.delete":
        table, pk = "journal", "jid"
    else:
        raise UnsupportedAction(f"no undo for {action}")
    row_id = row.get("entity_id")
    if not row_id:
        raise _missing_data()
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
        raise _missing_data()
    try:
        await _insert_row(session, table, row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore {table} #{row_id}: {err}") from err
    await _sync_capture(session, table, "insert", pk, row_id)
    return f"restored {table} #{row_id}"


@register("annotation.update", "journal.update", "case.update")
async def _revert_update(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """annotation.update / journal.update / case.update: restore the
    pre-edit values recorded in the detail."""
    action = row.get("action") or ""
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


@register("link.create", "link.delete")
async def _revert_link(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """link.create / link.delete: invert the link insert/delete."""
    action = row.get("action") or ""
    detail = _detail(row)
    row_dict = detail.get("row") or detail
    link_id = row.get("entity_id") or row_dict.get("id")
    if not link_id:
        raise _missing_data()
    if (action == "link.create") == undo:
        await _delete_by_id(session, "link", "id", link_id)
        return f"deleted link #{link_id}"
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise _missing_data()
    try:
        await _insert_row(session, "link", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore link #{link_id}: {err}") from err
    await _sync_capture(session, "link", "insert", "id", link_id)
    return f"restored link #{link_id}"


@register("comment.create", "comment.update", "comment.delete")
async def _revert_comment(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """comment.create / comment.update / comment.delete."""
    action = row.get("action") or ""
    detail = _detail(row)
    comment_id = row.get("entity_id")
    if not comment_id:
        raise _missing_data()
    if action == "comment.update":
        body = detail.get("old_body") if undo else detail.get("new_body")
        if body is None:
            raise _missing_data()
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
        raise _missing_data()
    try:
        await _insert_row(session, "comment", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore comment #{comment_id}: {err}") from err
    await _sync_capture(session, "comment", "insert", "id", comment_id)
    return f"restored comment #{comment_id}"


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


@register("bookmark.set")
async def _revert_bookmark(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """bookmark.set: restore the five bookmark columns of the project row
    from the captured before/after snapshots."""
    detail = _detail(row)
    target = detail.get("before") if undo else detail.get("after")
    if not isinstance(target, dict):
        raise _missing_data()
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


@register("speakers.mark")
async def _revert_speakers_mark(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
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


@register("pseudonym.add", "pseudonym.delete")
async def _revert_pseudonym(
    session: AsyncSession, row: dict, *, undo: bool, project_path: str | None
) -> str:
    """pseudonym.add / pseudonym.delete: invert the pseudonyms.json pair."""
    from qualcoder_api.services import pseudonyms

    action = row.get("action") or ""
    detail = _detail(row)
    original = detail.get("original")
    if not original:
        raise _missing_data()
    if not project_path:
        raise UnsupportedAction("no project is open — cannot restore pseudonyms.json")
    pseudonym = detail.get("pseudonym")

    async def _write(call, *args, what: str) -> None:
        try:
            call(*args)
        except (ValueError, OSError) as err:
            raise UnsupportedAction(f"cannot {what}: {err}") from err

    if action == "pseudonym.add":
        if undo:
            await _write(pseudonyms.delete_pseudonym, project_path, original, what="delete the pseudonym")
            return f"deleted pseudonym {original!r}"
        if not pseudonym:
            raise _missing_data()
        await _write(pseudonyms.add_pseudonym, project_path, original, pseudonym, what="restore the pseudonym")
        return f"restored pseudonym {original!r}"
    if action == "pseudonym.delete":
        if undo:
            if not pseudonym:
                raise _missing_data()
            await _write(pseudonyms.add_pseudonym, project_path, original, pseudonym, what="restore the pseudonym")
            return f"restored pseudonym {original!r}"
        await _write(pseudonyms.delete_pseudonym, project_path, original, what="delete the pseudonym")
        return f"deleted pseudonym {original!r}"
    raise UnsupportedAction(f"no undo for {action}")


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


@register("coder.create", "coder.delete", "coder.rename", "coder.visibility")
async def _revert_coder(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """coder.create / coder.delete / coder.rename / coder.visibility: the
    coder list lives in the per-machine settings; visibility lives in the
    project's ``coder_names`` table."""
    from qualcoder_api.persistence import tables
    from qualcoder_api.services.user_settings import get_coders, set_coders

    action = row.get("action") or ""
    detail = _detail(row)
    if action == "coder.create":
        name = detail.get("name")
        if not name:
            raise _missing_data()
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
            raise _missing_data()
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
            raise _missing_data()
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
            raise _missing_data()
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


@register("sync.toggle")
async def _revert_sync_toggle(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """sync.toggle: restore the previously stored sync switch state."""
    from qualcoder_api.services.user_settings import save_sync_settings

    detail = _detail(row)
    enabled = detail.get("before") if undo else detail.get("enabled")
    if enabled is None:
        raise _missing_data()
    save_sync_settings(bool(enabled))
    return f"sync {'restored' if undo else 're-applied'} (enabled={bool(enabled)})"


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


@register("qtt.create")
async def _revert_qtt_sheet_create(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """qtt.create: remove the worksheet (and its items) or restore it."""
    detail = _detail(row)
    sheet_id = row.get("entity_id")
    if not sheet_id:
        raise _missing_data()
    if undo:
        await session.execute(text("DELETE FROM qtt_item WHERE sheet_id = :v"), {"v": sheet_id})
        await _delete_by_id(session, "qtt_sheet", "id", sheet_id)
        return f"deleted worksheet #{sheet_id}"
    row_dict = detail.get("row")
    if not isinstance(row_dict, dict) or not row_dict.get("id"):
        raise _missing_data()
    try:
        await _insert_row(session, "qtt_sheet", row_dict)
    except Exception as err:
        raise UnsupportedAction(f"cannot restore worksheet #{sheet_id}: {err}") from err
    await _sync_capture(session, "qtt_sheet", "insert", "id", sheet_id)
    return f"restored worksheet #{sheet_id}"


@register("qtt.delete")
async def _revert_qtt_sheet_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """qtt.delete: restore the worksheet plus its items (undo) or remove them
    again (redo)."""
    detail = _detail(row)
    sheet_id = row.get("entity_id")
    if not sheet_id:
        raise _missing_data()
    if undo:
        row_dict = detail.get("row")
        if not isinstance(row_dict, dict) or not row_dict.get("id"):
            raise _missing_data()
        try:
            await _insert_row(session, "qtt_sheet", row_dict)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore worksheet #{sheet_id}: {err}") from err
        await _sync_capture(session, "qtt_sheet", "insert", "id", sheet_id)
        for item in detail.get("items") or []:
            try:
                await _insert_row(session, "qtt_item", item)
            except Exception as err:
                raise UnsupportedAction(f"cannot restore worksheet item: {err}") from err
        return f"restored worksheet #{sheet_id} with its items"
    await session.execute(text("DELETE FROM qtt_item WHERE sheet_id = :v"), {"v": sheet_id})
    await _delete_by_id(session, "qtt_sheet", "id", sheet_id)
    return f"deleted worksheet #{sheet_id}"


@register("qtt.item.create", "qtt.item.delete", "qtt.send_segment")
async def _revert_qtt_item(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """QTT item create/delete/send_segment: generic single-row inversion."""
    return await _revert_row_pair(
        session, row, undo=undo, table="qtt_item", pk="id",
        create_actions=("qtt.item.create", "qtt.send_segment"),
        delete_actions=("qtt.item.delete",),
    )


@register("qtt.update", "qtt.item.update")
async def _revert_qtt_update(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """QTT sheet/item updates: generic before/after row inversion."""
    action = row.get("action") or ""
    table = "qtt_sheet" if action == "qtt.update" else "qtt_item"
    return await _revert_row_update(session, row, undo=undo, table=table, pk="id")


@register("filter.create", "filter.delete")
async def _revert_filter(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """files_filter create/delete: generic single-row inversion."""
    return await _revert_row_pair(
        session, row, undo=undo, table="files_filter", pk="filterid",
        create_actions=("filter.create",), delete_actions=("filter.delete",),
    )


@register("sql.save", "sql.delete")
async def _revert_sql(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """stored_sql save/delete: generic single-row inversion."""
    return await _revert_row_pair(
        session, row, undo=undo, table="stored_sql", pk="title",
        create_actions=("sql.save",), delete_actions=("sql.delete",),
    )
