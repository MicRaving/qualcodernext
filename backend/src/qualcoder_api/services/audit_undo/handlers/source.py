"""Source import/delete/update/link_fix/replace, transcript and transcribe handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import (
    UnsupportedAction,
    _delete_by_id,
    _detail,
    _insert_row,
    _missing_data,
    _restore_row,
    _sync_capture,
    _update_row,
)
from ..registry import register


@register("source.update")
async def _revert_source_update(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """source.update (rename/memo): restore the before values (undo) or the
    after values (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id") or row.get("source_id")
    if not source_id:
        raise _missing_data()
    # Only restore the fields the audit row actually recorded — a legacy
    # row without before/after values must not overwrite columns with NULL.
    sets = []
    params: dict = {"id": source_id}
    for detail_key, column in (("before_name", "name"), ("before_memo", "memo")):
        if undo:
            value = detail.get(detail_key)
            if value is not None:
                sets.append(f"{column} = :{column}")
                params[column] = value
    for detail_key, column in (("after_name", "name"), ("after_memo", "memo")):
        if not undo:
            value = detail.get(detail_key)
            if value is not None:
                sets.append(f"{column} = :{column}")
                params[column] = value
    if not sets:
        raise _missing_data()
    await session.execute(
        text(f"UPDATE source SET {', '.join(sets)} WHERE id = :id"), params
    )
    await _sync_capture(session, "source", "update", "id", source_id)
    return f"source #{source_id} {'restored' if undo else 're-applied'}"


@register("source.import", "source.link")
async def _revert_source_import(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    source_id = row.get("entity_id")
    if not source_id:
        raise _missing_data()
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


@register("transcript.create", "transcript.delete")
async def _revert_transcript(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """transcript.create / transcript.delete: companion row + av_text_id link.

    The detail carries the full companion ``source`` row, so both directions
    are invertible: undo of create removes the companion, undo of delete
    re-inserts it and re-links the media source.
    """
    action = row.get("action") or ""
    detail = _detail(row)
    trans_id = row.get("entity_id")
    media_id = row.get("source_id")
    if not trans_id or not media_id:
        raise _missing_data()
    companion = detail.get("companion") or detail.get("row")

    async def _restore_companion() -> str:
        if not isinstance(companion, dict):
            raise _missing_data()
        try:
            await _insert_row(session, "source", companion)
        except Exception as err:
            raise UnsupportedAction(f"cannot restore transcript #{trans_id}: {err}") from err
        await _sync_capture(session, "source", "insert", "id", trans_id)
        await session.execute(
            text("UPDATE source SET av_text_id = :t WHERE id = :v"),
            {"t": trans_id, "v": media_id},
        )
        return f"restored transcript #{trans_id}"

    async def _remove_companion() -> str:
        await session.execute(
            text("UPDATE source SET av_text_id = NULL WHERE id = :v"), {"v": media_id}
        )
        await _delete_by_id(session, "source", "id", trans_id)
        return f"deleted transcript #{trans_id}"

    if action == "transcript.create":
        if undo:
            return await _remove_companion()
        return await _restore_companion()
    if action == "transcript.delete":
        if undo:
            return await _restore_companion()
        return await _remove_companion()
    raise UnsupportedAction(f"no undo for {action}")


@register("source.delete")
async def _revert_source_delete(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """source.delete: re-insert the full row plus every attached row (undo);
    delete again with the same cascade (redo)."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    if not source_id:
        raise _missing_data()
    if undo:
        source_row = detail.get("row")
        if not isinstance(source_row, dict) or not source_row.get("id"):
            raise _missing_data()
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


@register("source.link_fix")
async def _revert_source_link_fix(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """source.link_fix: restore the previous mediapath (undo) or re-apply the
    new one (redo). The bulk variant carries one [sid, old, new] triple per
    updated source."""
    detail = _detail(row)
    if detail.get("bulk"):
        triples = detail.get("rows") or []
        if not triples:
            raise _missing_data()
        for sid, old, new in triples:
            target = old if undo else new
            await session.execute(
                text("UPDATE source SET mediapath = :mp WHERE id = :v"),
                {"mp": target, "v": sid},
            )
        return f"{'restored' if undo else 're-applied'} {len(triples)} mediapath(s)"
    source_id = row.get("entity_id")
    if not source_id:
        raise _missing_data()
    old = detail.get("old")
    new = detail.get("new")
    if old is None or new is None:
        raise _missing_data()
    await session.execute(
        text("UPDATE source SET mediapath = :mp WHERE id = :v"),
        {"mp": old if undo else new, "v": source_id},
    )
    await _sync_capture(session, "source", "update", "id", source_id)
    return f"source #{source_id} mediapath {'restored' if undo else 're-applied'}"


@register("source.replace")
async def _revert_source_replace(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """source.replace: restore the pre-replacement source row and put every
    captured segment (codings/annotations/case links) back at its old
    position. Redo is not invertible — the replacement file bytes are gone."""
    detail = _detail(row)
    source_id = row.get("entity_id")
    if not source_id:
        raise _missing_data()
    if not undo:
        raise UnsupportedAction(
            "cannot redo a source replacement — upload the replacement file again"
        )
    before = detail.get("before_source")
    if not isinstance(before, dict) or not before.get("id"):
        raise _missing_data()
    await _update_row(session, "source", "id", source_id, before)
    await _sync_capture(session, "source", "update", "id", source_id)
    restored = 0
    for table, pk in (("code_text", "ctid"), ("annotation", "anid"), ("case_text", "id")):
        for r in detail.get(table) or []:
            action = await _restore_row(session, table, pk, r)
            await _sync_capture(session, table, action, pk, r.get(pk))
            restored += 1
    return f"restored source #{source_id} and {restored} re-anchored segment(s)"


@register("transcribe.start")
async def _revert_transcribe_start(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """transcribe.start: cancel the job while it is still queued/running (the
    transcript source has not been created yet). Finished jobs leave the
    transcript in the project — undo the resulting ``source.import`` row."""
    from qualcoder_api.services.transcription import control_job, get_job

    detail = _detail(row)
    job_id = detail.get("job_id")
    if not job_id:
        raise _missing_data()
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
