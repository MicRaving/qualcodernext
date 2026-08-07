"""Text coding engine — port of the legacy edit-mode and autocode logic.

Pure backend: no Qt, no FastAPI. ``shift_positions`` is a faithful port of
``CodingTextEditModeMixin.update_positions`` (edit_mode_mixin.py) using
diff-match-patch; ``commit_edit`` applies the legacy ``ed_update_codings`` /
``ed_update_annotations`` / ``ed_update_casetext`` writes; ``autocode`` ports
``CodeText.auto_code``; ``undo_codings`` ports ``undo_stack.undo_last_...``.
"""

from __future__ import annotations

import datetime
import re
from copy import deepcopy

from diff_match_patch import diff_match_patch
from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Source
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodingRepository


def _now() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _emoji_list(text: str) -> list[dict]:
    try:
        import emoji
    except ImportError:  # pragma: no cover - optional dependency
        return []
    return [dict(m) for m in emoji.emoji_list(text)]


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
    for c in shifts["codings"]:
        if c["newpos0"] is None:
            await session.execute(delete(tables.code_text).where(tables.code_text.c.ctid == c["ctid"]))
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
    for c in shifts["annotations"]:
        if c["newpos0"] is None:
            await session.execute(delete(tables.annotation).where(tables.annotation.c.anid == c["anid"]))
        else:
            await session.execute(
                update(tables.annotation)
                .where(tables.annotation.c.anid == c["anid"])
                .values(pos0=c["newpos0"], pos1=c["newpos1"])
            )
            updated["annotation"] += 1
    for c in shifts["case_text"]:
        if c["newpos0"] is None:
            await session.execute(delete(tables.case_text).where(tables.case_text.c.id == c["id"]))
        else:
            await session.execute(
                update(tables.case_text)
                .where(tables.case_text.c.id == c["id"])
                .values(pos0=c["newpos0"], pos1=c["newpos1"])
            )
            updated["case_text"] += 1
    await session.commit()
    return {"updated": updated, "deleted": shifts["deletions"]}


async def autocode(
    session: AsyncSession,
    *,
    fid: int | None,
    cid: int,
    find_texts: list[str],
    mode: str = "all",
    use_regex: bool = False,
    owner: str,
) -> list[dict]:
    """Autocode matching text spans in one source (or all text sources).

    Port of the legacy ``CodeText.auto_code`` loop. ``mode`` is "all",
    "first", "last" or ``"code_within_code <cid>"`` — the last keeps only
    matches that fall inside a coded segment of the given code (same file
    and owner). Regex compile errors raise :class:`ValueError`. Duplicate
    inserts are skipped silently.
    """
    within_cid: int | None = None
    if mode.startswith("code_within_code"):
        parts = mode.split()
        if len(parts) != 2:
            raise ValueError("invalid code_within_code mode")
        try:
            within_cid = int(parts[1])
        except ValueError:
            raise ValueError("invalid code_within_code mode") from None
        mode = "all"
    patterns = [t.strip() for t in find_texts if t.strip()]
    regexes: list[re.Pattern[str]] = []
    if use_regex:
        for pattern in patterns:
            try:
                regexes.append(re.compile(pattern))
            except re.error as err:
                raise ValueError("invalid regex") from err

    if fid is None:
        rows = (
            await session.execute(
                select(tables.source.c.id, tables.source.c.fulltext).where(
                    or_(
                        tables.source.c.mediapath.is_(None),
                        tables.source.c.mediapath.like("/docs/%"),
                        tables.source.c.mediapath.like("docs:%"),
                    )
                )
            )
        ).all()
    else:
        row = (
            await session.execute(
                select(tables.source.c.id, tables.source.c.fulltext).where(
                    tables.source.c.id == fid
                )
            )
        ).first()
        rows = [row] if row is not None else []

    # code_within_code: (fid) -> sorted list of (pos0, pos1) coded segments.
    within_spans: dict[int, list[tuple[int, int]]] = {}
    if within_cid is not None:
        span_rows = (
            await session.execute(
                select(tables.code_text.c.fid, tables.code_text.c.pos0, tables.code_text.c.pos1)
                .where(
                    tables.code_text.c.cid == within_cid,
                    tables.code_text.c.owner == owner,
                )
                .order_by(tables.code_text.c.pos0)
            )
        ).all()
        for span_fid, pos0, pos1 in span_rows:
            within_spans.setdefault(span_fid, []).append((pos0, pos1))

    def _inside(pos0: int, pos1: int, fid: int) -> bool:
        return any(pos0 >= s0 and pos1 <= s1 for s0, s1 in within_spans.get(fid, []))

    created: list[dict] = []
    repo = CodingRepository(session)
    for index, find_txt in enumerate(patterns):
        for file_id, file_text in rows:
            if file_text is None:
                continue
            emojis = _emoji_list(file_text)
            if use_regex:
                matches = [(m.start(), m.end()) for m in regexes[index].finditer(file_text)]
            else:
                matches = [(m.start(), m.end()) for m in re.finditer(re.escape(find_txt), file_text)]
            if mode == "first" and len(matches) > 1:
                matches = matches[:1]
            if mode == "last" and len(matches) > 1:
                matches = matches[-1:]
            for start, end in matches:
                if within_cid is not None and not _inside(start, end, file_id):
                    continue
                pos0, pos1 = start, end
                seltext = file_text[start:end] if use_regex else find_txt
                # Emoji positions from the Qt UI count UTF-16 code units;
                # add each preceding emoji's extra length to pos0/pos1.
                for emo in emojis:
                    if emo["match_end"] < pos0:
                        pos0 += emo["match_end"] - emo["match_start"]
                        pos1 += emo["match_end"] - emo["match_start"]
                try:
                    coding = await repo.add_text_coding(
                        cid=cid,
                        fid=file_id,
                        seltext=seltext,
                        pos0=pos0,
                        pos1=pos1,
                        owner=owner,
                        memo="",
                    )
                except IntegrityError:
                    # Possible a duplicate entry (unique cid,fid,pos0,pos1,owner)
                    continue
                created.append(
                    {
                        "ctid": coding.ctid,
                        "cid": coding.cid,
                        "fid": coding.fid,
                        "seltext": coding.seltext,
                        "pos0": coding.pos0,
                        "pos1": coding.pos1,
                        "owner": coding.owner,
                        "memo": coding.memo,
                        "date": coding.date,
                        "important": coding.important,
                    }
                )
    return created


async def undo_codings(session: AsyncSession, items: list[dict]) -> int:
    """Re-insert previously deleted ``code_text`` rows; return count restored.

    Port of the legacy undo_stack insert (cid, fid, seltext, pos0, pos1,
    owner, memo, date, important). Rows that collide with the unique
    constraint are skipped silently.
    """
    restored = 0
    for item in items:
        try:
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
                )
            )
            await session.flush()
            restored += 1
        except IntegrityError:
            await session.rollback()
    await session.commit()
    return restored
