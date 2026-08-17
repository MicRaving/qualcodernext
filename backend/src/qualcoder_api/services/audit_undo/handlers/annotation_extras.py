"""Link / comment / bookmark / speakers / pseudonym handlers."""
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
