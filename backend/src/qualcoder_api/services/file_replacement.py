"""Text file replacement with segment re-anchoring (upstream ReplaceTextFile).

Replaces a source's stored text (and project copy of the file) with the
contents of a new document, then re-anchors every ``code_text``,
``annotation`` and ``case_text`` position by locating the first occurrence
of each segment's original text in the new fulltext. Segments that cannot
be found are deleted; ambiguous matches (found multiple times) are reported.
PDF sources are not replaceable (their stored text must match the pages).
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables
from qualcoder_api.services import pseudonyms
from qualcoder_api.services.import_service import extract_text


async def _segment_snippets(
    session: AsyncSession, fid: int, table, rows, id_col, pos0_col, pos1_col
) -> list[dict]:
    fulltext_row = (
        await session.execute(
            select(tables.source.c.fulltext).where(tables.source.c.id == fid)
        )
    ).first()
    old_fulltext = fulltext_row[0] or "" if fulltext_row else ""
    segments: list[dict] = []
    for row in rows:
        row_id = row[id_col]
        pos0 = row[pos0_col] or 0
        pos1 = row[pos1_col] or 0
        seltext = old_fulltext[pos0:pos1]
        segments.append({"id": row_id, "pos0": pos0, "pos1": pos1, "seltext": seltext})
    return segments


async def replace_text_file(
    session: AsyncSession,
    project_path: str,
    fid: int,
    new_file_path: str,
    filename: str,
    owner: str,
) -> dict:
    """Replace source ``fid`` with the uploaded document (upstream port).

    Returns a report of re-anchored/deleted segments per entity type.
    Raises ``ValueError`` for PDF sources or unreadable replacements.
    """
    source_row = (
        await session.execute(select(tables.source).where(tables.source.c.id == fid))
    ).first()
    if source_row is None:
        raise ValueError("source not found")
    source = dict(source_row._mapping)

    if (source.get("mediapath") or "").lower().endswith(".pdf"):
        raise ValueError(
            "PDF files cannot be replaced: their stored text must match the "
            "extracted pages. Use the plain-text mode to work with an editable copy."
        )
    if source.get("name") != filename:
        dup = (
            await session.execute(
                select(tables.source.c.id).where(
                    tables.source.c.name == filename, tables.source.c.id != fid
                )
            )
        ).first()
        if dup is not None:
            raise ValueError("new file name matches another existing file")

    new_text = await _extract_or_raise(new_file_path, filename)
    # Normalise line endings / BOM like the upstream UI does.
    new_text = new_text.replace("\r\n", "\n").replace("\r", "\n")
    if new_text.startswith("\ufeff"):
        new_text = new_text[1:]
    # Apply pseudonyms (upstream applies them to the replacement text).
    new_text = pseudonyms.apply_pseudonyms(new_text, project_path)

    old_fulltext = source.get("fulltext") or ""

    from qualcoder_api.persistence.repositories import _capture

    def _clean(data: dict) -> dict:
        return {k: v for k, v in data.items() if not k.startswith("_")}

    # --- codings ---------------------------------------------------------
    code_rows = (
        await session.execute(
            select(tables.code_text).where(tables.code_text.c.fid == fid)
        )
    ).all()
    code_by_id = {dict(r._mapping)["ctid"]: dict(r._mapping) for r in code_rows}
    codes = await _segment_snippets(
        session, fid, tables.code_text,
        [(m["ctid"], m["pos0"], m["pos1"]) for m in code_by_id.values()], 0, 1, 2,
    )
    deleted_codes = 0
    ambiguous = 0
    for segment in codes:
        count = new_text.count(segment["seltext"])
        if count == 0:
            data = code_by_id.pop(segment["id"])
            await session.execute(
                delete(tables.code_text).where(tables.code_text.c.ctid == segment["id"])
            )
            await _capture(
                session, "code_text", "delete", "ctid", segment["id"], _clean(data)
            )
            deleted_codes += 1
            continue
        if count > 1:
            ambiguous += 1
        pos = new_text.find(segment["seltext"])
        length = segment["pos1"] - segment["pos0"]
        await session.execute(
            update(tables.code_text)
            .where(tables.code_text.c.ctid == segment["id"])
            .values(pos0=pos, pos1=pos + length)
        )
        data = dict(code_by_id[segment["id"]])
        data["pos0"] = pos
        data["pos1"] = pos + length
        await _capture(
            session, "code_text", "update", "ctid", segment["id"], _clean(data)
        )

    # --- annotations ------------------------------------------------------
    ann_rows = (
        await session.execute(
            select(tables.annotation).where(tables.annotation.c.fid == fid)
        )
    ).all()
    ann_by_id = {dict(r._mapping)["anid"]: dict(r._mapping) for r in ann_rows}
    anns = await _segment_snippets(
        session, fid, tables.annotation,
        [(m["anid"], m["pos0"], m["pos1"]) for m in ann_by_id.values()], 0, 1, 2,
    )
    deleted_anns = 0
    for segment in anns:
        count = new_text.count(segment["seltext"])
        if count == 0:
            data = ann_by_id.pop(segment["id"])
            await session.execute(
                delete(tables.annotation).where(tables.annotation.c.anid == segment["id"])
            )
            await _capture(
                session, "annotation", "delete", "anid", segment["id"], _clean(data)
            )
            deleted_anns += 1
            continue
        pos = new_text.find(segment["seltext"])
        length = segment["pos1"] - segment["pos0"]
        await session.execute(
            update(tables.annotation)
            .where(tables.annotation.c.anid == segment["id"])
            .values(pos0=pos, pos1=pos + length)
        )
        data = dict(ann_by_id[segment["id"]])
        data["pos0"] = pos
        data["pos1"] = pos + length
        await _capture(
            session, "annotation", "update", "anid", segment["id"], _clean(data)
        )

    # --- case links -------------------------------------------------------
    case_rows = (
        await session.execute(
            select(tables.case_text).where(tables.case_text.c.fid == fid)
        )
    ).all()
    case_by_id = {dict(r._mapping)["id"]: dict(r._mapping) for r in case_rows}
    cases = await _segment_snippets(
        session, fid, tables.case_text,
        [(m["id"], m["pos0"], m["pos1"]) for m in case_by_id.values()], 0, 1, 2,
    )
    # Whole-file assignment: pos0=0 and pos1 covers the whole old text.
    full_file_caseids = [
        c["id"]
        for c in cases
        if c["pos0"] == 0 and c["pos1"] == max(0, len(old_fulltext) - 1)
    ]
    for cid in full_file_caseids:
        await session.execute(
            update(tables.case_text)
            .where(tables.case_text.c.id == cid)
            .values(pos1=max(0, len(new_text) - 1))
        )
        data = dict(case_by_id[cid])
        data["pos1"] = max(0, len(new_text) - 1)
        await _capture(
            session, "case_text", "update", "id", cid, _clean(data)
        )
    deleted_cases = 0
    for segment in cases:
        if segment["id"] in full_file_caseids:
            continue
        count = new_text.count(segment["seltext"])
        if count == 0:
            data = case_by_id.pop(segment["id"])
            await session.execute(
                delete(tables.case_text).where(tables.case_text.c.id == segment["id"])
            )
            await _capture(
                session, "case_text", "delete", "id", segment["id"], _clean(data)
            )
            deleted_cases += 1
            continue
        pos = new_text.find(segment["seltext"])
        length = segment["pos1"] - segment["pos0"]
        await session.execute(
            update(tables.case_text)
            .where(tables.case_text.c.id == segment["id"])
            .values(pos0=pos, pos1=pos + length)
        )
        data = dict(case_by_id[segment["id"]])
        data["pos0"] = pos
        data["pos1"] = pos + length
        await _capture(
            session, "case_text", "update", "id", segment["id"], _clean(data)
        )

    # --- file copy + source row ------------------------------------------
    old_mediapath = source.get("mediapath")
    if old_mediapath is None:
        with contextlib.suppress(OSError):
            (Path(project_path) / "documents" / (source.get("name") or "")).unlink(
                missing_ok=True
            )
    dest = Path(project_path) / "documents" / filename
    try:
        shutil.copy2(new_file_path, dest)
    except OSError as err:
        raise ValueError(f"cannot copy replacement file: {err}") from err

    from qualcoder_api.persistence.repositories import _now

    await session.execute(
        update(tables.source)
        .where(tables.source.c.id == fid)
        .values(
            name=filename,
            fulltext=new_text,
            mediapath=None if old_mediapath is None else old_mediapath,
            owner=owner,
            date=_now(),
        )
    )
    updated = (
        await session.execute(select(tables.source).where(tables.source.c.id == fid))
    ).first()
    if updated is not None:
        await _capture(
            session, "source", "update", "id", fid,
            _clean(dict(updated._mapping)),
        )
    await session.commit()
    return {
        "ok": True,
        "file": filename,
        "deleted_codings": deleted_codes,
        "deleted_annotations": deleted_anns,
        "deleted_case_links": deleted_cases,
        "ambiguous_segments": ambiguous,
        "message": (
            "Reload the file and check the accuracy of codings and annotations. "
            "Segments are re-anchored by locating their first matching text."
        ),
    }


async def _extract_or_raise(path: str, filename: str) -> str:
    text_ = await asyncio_to_thread_extract(path)
    if not text_.strip():
        raise ValueError("the replacement file is empty or unreadable")
    return text_


async def asyncio_to_thread_extract(path: str) -> str:
    import asyncio

    return await asyncio.to_thread(extract_text, path)
