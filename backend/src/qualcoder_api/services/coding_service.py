"""Text coding engine — port of the legacy edit-mode and undo logic.

Pure backend: no Qt, no FastAPI. ``shift_positions`` is a faithful port of
``CodingTextEditModeMixin.update_positions`` (edit_mode_mixin.py) using
diff-match-patch; ``commit_edit`` applies the legacy ``ed_update_codings`` /
``ed_update_annotations`` / ``ed_update_casetext`` writes; ``undo_codings``
ports ``undo_stack.undo_last_...``.

The autocode subsystem (``autocode`` / ``ai_autocode`` and helpers) lives in
:mod:`qualcoder_api.services.autocode_service` and is re-exported here for
backwards compatibility.
"""

from __future__ import annotations

from copy import deepcopy

from diff_match_patch import diff_match_patch
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Source
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables

# Re-export the autocode subsystem for backwards compatibility — existing
# ``from qualcoder_api.services.coding_service import autocode`` keeps working.
from qualcoder_api.services.autocode_service import (  # noqa: F401
    ai_autocode,
    autocode,
)


def shift_positions(
    prev_text: str,
    new_text: str,
    codings: list[dict],
    annotations: list[dict],
    case_text: list[dict],
) -> dict:
    """Recompute segment positions after an edit-mode text change.

    Faithful port of the legacy ``update_positions`` diff analysis: only the
    2-element (add/remove at start or end) and 3-element (add/remove in the
    middle) diff cases shift anything, exactly as the legacy code computes
    ``extending`` / ``chars_len`` / ``pre_chars_len`` / ``post_chars_len`` /
    ``preceding_pos``.

    Input dicts keep their original keys; ``newpos0``/``newpos1`` are added
    (``None`` marks a segment scheduled for deletion). ``deletions`` collects
    the ids of segments whose ``newpos0`` became ``None``.
    """
    diff = diff_match_patch()
    diff_list = diff.diff_main(prev_text, new_text)
    extending = True
    preceding_pos = 0
    chars_len = 0
    pre_chars_len = 0
    post_chars_len = 0
    if len(diff_list) == 2 and diff_list[0][0] == 1:
        chars_len = len(diff_list[0][1])
        pre_chars_len = 0
        preceding_pos = 0
    if len(diff_list) == 2 and diff_list[0][0] == -1:
        extending = False
        chars_len = len(diff_list[0][1])
        pre_chars_len = 0
        preceding_pos = 0
        post_chars_len = len(diff_list[1][1])
    if len(diff_list) == 2 and diff_list[1][0] == 1:
        chars_len = len(diff_list[1][1])
        pre_chars_len = len(diff_list[0][1])
        preceding_pos = pre_chars_len - 1
    if len(diff_list) == 2 and diff_list[1][0] == -1:
        extending = False
        chars_len = len(diff_list[1][1])
        post_chars_len = 0
        pre_chars_len = len(diff_list[0][1])
        preceding_pos = pre_chars_len - 1
    if len(diff_list) == 3 and diff_list[1][0] == 1:
        chars_len = len(diff_list[1][1])
        pre_chars_len = len(diff_list[0][1])
        preceding_pos = pre_chars_len - 1
    if len(diff_list) == 3 and diff_list[1][0] == -1:
        extending = False
        chars_len = len(diff_list[1][1])
        pre_chars_len = len(diff_list[0][1])
        preceding_pos = pre_chars_len - 1
        post_chars_len = len(diff_list[2][1])

    def prepare(entries: list[dict]) -> list[dict]:
        items = []
        for entry in entries:
            item = deepcopy(entry)
            item["newpos0"] = item.get("newpos0", item["pos0"])
            item["newpos1"] = item.get("newpos1", item["pos1"])
            items.append(item)
        return items

    codings = prepare(codings)
    annotations = prepare(annotations)
    case_text = prepare(case_text)
    deletions: dict[str, list[int]] = {"code_text": [], "annotation": [], "case_text": []}

    # Adding characters
    if extending:
        for c in codings:
            changed = False
            if (
                c["newpos0"] is not None
                and c["newpos0"] >= preceding_pos
                and c["newpos0"] >= preceding_pos - pre_chars_len
            ):
                c["newpos0"] += chars_len
                c["newpos1"] += chars_len
                # Also check and apply start of code is at start of text
                if c["pos0"] == 0:
                    c["newpos0"] = 0
                changed = True
            if not changed and c["newpos0"] is not None and c["newpos0"] < preceding_pos < c["newpos1"]:
                c["newpos1"] += chars_len

        for c in annotations:
            changed = False
            if (
                c["newpos0"] is not None
                and c["newpos0"] >= preceding_pos
                and c["newpos0"] >= preceding_pos - pre_chars_len
            ):
                c["newpos0"] += chars_len
                c["newpos1"] += chars_len
                changed = True
            if c["newpos0"] is not None and not changed and c["newpos0"] < preceding_pos < c["newpos1"]:
                c["newpos1"] += chars_len

        for c in case_text:
            changed = False
            if (
                c["newpos0"] is not None
                and c["newpos0"] >= preceding_pos
                and c["newpos0"] >= preceding_pos - pre_chars_len
            ):
                c["newpos0"] += chars_len
                # check and apply start of case is included
                if c["pos0"] == 0:
                    c["newpos0"] = 0
                c["newpos1"] += chars_len
                changed = True
            if c["newpos0"] is not None and not changed and c["newpos0"] < preceding_pos < c["newpos1"]:
                c["newpos1"] += chars_len
        return {
            "codings": codings,
            "annotations": annotations,
            "case_text": case_text,
            "deletions": deletions,
        }

    # Removing characters
    for c in codings:
        changed = False
        if (
            c["newpos0"] is not None
            and c["newpos0"] >= preceding_pos
            and c["newpos0"] >= preceding_pos - pre_chars_len
        ):
            c["newpos0"] -= chars_len
            if c["newpos0"] < 0:
                c["newpos0"] = 0
            c["newpos1"] -= chars_len
            changed = True
        # Remove, as entire text is being removed (e.g. copy replace)
        if (
            c["newpos0"] is not None
            and not changed
            and c["newpos0"] >= preceding_pos
            and c["newpos1"] < preceding_pos - pre_chars_len + post_chars_len
        ):
            c["newpos0"] -= chars_len
            if c["newpos0"] < 0:
                c["newpos0"] = 0
            c["newpos1"] -= chars_len
            changed = True
            deletions["code_text"].append(c["ctid"])
            c["newpos0"] = None
        if c["newpos0"] is not None and not changed and c["newpos0"] < preceding_pos <= c["newpos1"]:
            c["newpos1"] -= chars_len
            if c["newpos1"] < c["newpos0"]:
                deletions["code_text"].append(c["ctid"])
                c["newpos0"] = None

    for c in annotations:
        changed = False
        if (
            c["newpos0"] is not None
            and c["newpos0"] >= preceding_pos
            and c["newpos0"] >= preceding_pos - pre_chars_len
        ):
            c["newpos0"] -= chars_len
            if c["newpos0"] < 0:
                c["newpos0"] = 0
            c["newpos1"] -= chars_len
            changed = True
        # Remove, as entire text is being removed (e.g. copy replace)
        if (
            c["newpos0"] is not None
            and not changed
            and c["newpos0"] >= preceding_pos
            and c["newpos1"] < preceding_pos - pre_chars_len + post_chars_len
        ):
            c["newpos0"] -= chars_len
            if c["newpos0"] < 0:
                c["newpos0"] = 0
            c["newpos1"] -= chars_len
            changed = True
            deletions["annotation"].append(c["anid"])
            c["newpos0"] = None
        if c["newpos0"] is not None and not changed and c["newpos0"] < preceding_pos <= c["newpos1"]:
            c["newpos1"] -= chars_len
            if c["newpos1"] < c["newpos0"]:
                deletions["annotation"].append(c["anid"])
                c["newpos0"] = None

    for c in case_text:
        changed = False
        if (
            c["newpos0"] is not None
            and c["newpos0"] >= preceding_pos
            and c["newpos0"] >= preceding_pos - pre_chars_len
        ):
            c["newpos0"] -= chars_len
            if c["newpos0"] < 0:
                c["newpos0"] = 0
            c["newpos1"] -= chars_len
            changed = True
        # Remove, as entire text is being removed (e.g. copy replace)
        if (
            c["newpos0"] is not None
            and not changed
            and c["newpos0"] >= preceding_pos
            and c["newpos1"] < preceding_pos - pre_chars_len + post_chars_len
        ):
            c["newpos0"] -= chars_len
            if c["newpos0"] < 0:
                c["newpos0"] = 0
            c["newpos1"] -= chars_len
            changed = True
            deletions["case_text"].append(c["id"])
            c["newpos0"] = None
        if c["newpos0"] is not None and not changed and c["newpos0"] < preceding_pos <= c["newpos1"]:
            c["newpos1"] -= chars_len
            if c["newpos1"] < c["newpos0"]:
                deletions["case_text"].append(c["id"])
                c["newpos0"] = None

    return {
        "codings": codings,
        "annotations": annotations,
        "case_text": case_text,
        "deletions": deletions,
    }


async def commit_edit(session: AsyncSession, fid: int, new_text: str, owner: str) -> dict:
    """Apply an edit-mode commit for one source (legacy ``edit_mode_off`` writes).

    Shifts all ``code_text``/``annotation``/``case_text`` rows of ``fid`` with
    :func:`shift_positions`, updates ``source.fulltext``, rewrites each segment
    position (and ``seltext`` slice for codings) and deletes segments whose
    new position became ``None``.
    """
    source_row = (
        await session.execute(select(tables.source).where(tables.source.c.id == fid))
    ).first()
    if source_row is None:
        raise ValueError("source not found")
    source = Source.model_validate(source_row._mapping)
    prev_text = source.fulltext or ""

    code_rows = (
        await session.execute(select(tables.code_text).where(tables.code_text.c.fid == fid))
    ).all()
    codings = [
        {"ctid": r.ctid, "pos0": r.pos0, "pos1": r.pos1, "seltext": r.seltext}
        for r in code_rows
    ]
    ann_rows = (
        await session.execute(select(tables.annotation).where(tables.annotation.c.fid == fid))
    ).all()
    annotations = [{"anid": r.anid, "pos0": r.pos0, "pos1": r.pos1} for r in ann_rows]
    case_rows = (
        await session.execute(select(tables.case_text).where(tables.case_text.c.fid == fid))
    ).all()
    case_text = [{"id": r.id, "pos0": r.pos0, "pos1": r.pos1} for r in case_rows]

    shifts = shift_positions(prev_text, new_text, codings, annotations, case_text)

    await session.execute(
        update(tables.source).where(tables.source.c.id == fid).values(fulltext=new_text)
    )
    updated = {"code_text": 0, "annotation": 0, "case_text": 0}

    from qualcoder_api.persistence.repositories import _capture, _rowdict

    async def _capture_after(table, pk_col, pk_value, action="update") -> None:
        row = (
            await session.execute(select(table).where(table.c[pk_col] == pk_value))
        ).first()
        if row is not None:
            await _capture(session, table.name, action, pk_col, pk_value, _rowdict(row))

    for c in shifts["codings"]:
        if c["newpos0"] is None:
            row = (
                await session.execute(
                    select(tables.code_text).where(tables.code_text.c.ctid == c["ctid"])
                )
            ).first()
            await session.execute(delete(tables.code_text).where(tables.code_text.c.ctid == c["ctid"]))
            if row is not None:
                await _capture(session, "code_text", "delete", "ctid", c["ctid"], _rowdict(row))
        else:
            await session.execute(
                update(tables.code_text)
                .where(tables.code_text.c.ctid == c["ctid"])
                .values(
                    pos0=c["newpos0"],
                    pos1=c["newpos1"],
                    seltext=new_text[c["newpos0"] : c["newpos1"]],
                )
            )
            updated["code_text"] += 1
            await _capture_after(tables.code_text, "ctid", c["ctid"])
    for c in shifts["annotations"]:
        if c["newpos0"] is None:
            row = (
                await session.execute(
                    select(tables.annotation).where(tables.annotation.c.anid == c["anid"])
                )
            ).first()
            await session.execute(delete(tables.annotation).where(tables.annotation.c.anid == c["anid"]))
            if row is not None:
                await _capture(session, "annotation", "delete", "anid", c["anid"], _rowdict(row))
        else:
            await session.execute(
                update(tables.annotation)
                .where(tables.annotation.c.anid == c["anid"])
                .values(pos0=c["newpos0"], pos1=c["newpos1"])
            )
            updated["annotation"] += 1
            await _capture_after(tables.annotation, "anid", c["anid"])
    for c in shifts["case_text"]:
        if c["newpos0"] is None:
            row = (
                await session.execute(
                    select(tables.case_text).where(tables.case_text.c.id == c["id"])
                )
            ).first()
            await session.execute(delete(tables.case_text).where(tables.case_text.c.id == c["id"]))
            if row is not None:
                await _capture(session, "case_text", "delete", "id", c["id"], _rowdict(row))
        else:
            await session.execute(
                update(tables.case_text)
                .where(tables.case_text.c.id == c["id"])
                .values(pos0=c["newpos0"], pos1=c["newpos1"])
            )
            updated["case_text"] += 1
            await _capture_after(tables.case_text, "id", c["id"])
    await _capture_after(tables.source, "id", fid)
    await session.commit()
    return {"updated": updated, "deleted": shifts["deletions"]}


async def undo_codings(session: AsyncSession, items: list[dict]) -> int:
    """Re-insert previously deleted ``code_text`` rows; return count restored.

    Port of the legacy undo_stack insert (cid, fid, seltext, pos0, pos1,
    owner, memo, date, important, avid, weight). Rows that collide with the
    unique constraint are skipped without discarding the previously restored
    rows (each insert runs in its own savepoint).
    """
    restored = 0
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    for item in items:
        try:
            # A nested savepoint keeps one failing insert from rolling back
            # the restores already flushed in this loop.
            async with session.begin_nested():
                await session.execute(
                    insert(tables.code_text).values(
                        cid=item["cid"],
                        fid=item["fid"],
                        seltext=item["seltext"],
                        pos0=item["pos0"],
                        pos1=item["pos1"],
                        owner=item["owner"],
                        memo=item.get("memo", ""),
                        date=item.get("date", _now()),
                        important=item.get("important", 0),
                        avid=item.get("avid"),
                        weight=item.get("weight", 0),
                    )
                )
                await session.flush()
                row = (
                    await session.execute(
                        select(tables.code_text).where(
                            tables.code_text.c.cid == item["cid"],
                            tables.code_text.c.fid == item["fid"],
                            tables.code_text.c.pos0 == item["pos0"],
                            tables.code_text.c.pos1 == item["pos1"],
                            tables.code_text.c.owner == item["owner"],
                        )
                    )
                ).first()
                if row is not None:
                    await _capture(session, "code_text", "insert", "ctid", row.ctid, _rowdict(row))
                restored += 1
        except IntegrityError:
            continue
    await session.commit()
    return restored
