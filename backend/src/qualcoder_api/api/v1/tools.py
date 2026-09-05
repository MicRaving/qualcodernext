"""Project tools API — bookmarks, pseudonyms, speakers, references,
bad-link repair, saved file filters, text file replacement."""

from __future__ import annotations

import contextlib
import os
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select, text

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep, ServiceDep
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import ProjectRepository
from qualcoder_api.services import audit
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(tags=["tools"])


# ----------------------------------------------------------------------
# Bookmarks (text + audio/video)
# ----------------------------------------------------------------------

class BookmarkRequest(BaseModel):
    file_id: int | None = None
    pos: int | None = None


class AVBookmarkRequest(BaseModel):
    file_id: int | None = None
    msec: int | None = None
    textpos: int | None = None


@router.get("/bookmarks")
async def get_bookmarks(db: DbDep) -> dict:
    return await ProjectRepository(db).get_bookmarks()


@router.put("/bookmarks")
async def set_bookmark(req: BookmarkRequest, db: DbDep) -> dict:
    before = await ProjectRepository(db).get_bookmarks()
    result = await ProjectRepository(db).set_bookmark(file_id=req.file_id, pos=req.pos)
    await audit.record(
        db, user=get_codername(), action="bookmark.set", entity="project",
        detail={"file_id": req.file_id, "pos": req.pos,
                "before": before, "after": result},
    )
    return result


@router.put("/bookmarks/av")
async def set_av_bookmark(req: AVBookmarkRequest, db: DbDep) -> dict:
    before = await ProjectRepository(db).get_bookmarks()
    result = await ProjectRepository(db).set_av_bookmark(
        file_id=req.file_id, msec=req.msec, textpos=req.textpos
    )
    await audit.record(
        db, user=get_codername(), action="bookmark.set", entity="project",
        detail={"file_id": req.file_id, "msec": req.msec, "textpos": req.textpos,
                "before": before, "after": result},
    )
    return result


# ----------------------------------------------------------------------
# Pseudonyms (pseudonyms.json in the project folder)
# ----------------------------------------------------------------------

class PseudonymAdd(BaseModel):
    original: str
    pseudonym: str = ""


class PseudonymDelete(BaseModel):
    original: str


@router.get("/pseudonyms")
async def list_pseudonyms(svc: OpenProjectDep) -> dict:
    from qualcoder_api.services import pseudonyms

    return {"pseudonyms": pseudonyms.load_pseudonyms(svc.project_path)}


@router.post("/pseudonyms")
async def add_pseudonym(req: PseudonymAdd, svc: OpenProjectDep, db: DbDep) -> dict:
    from qualcoder_api.services import pseudonyms

    try:
        entry = pseudonyms.add_pseudonym(svc.project_path, req.original, req.pseudonym)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await audit.record(
        db, user=get_codername(), action="pseudonym.add", entity="pseudonym",
        detail={"original": req.original, "pseudonym": entry["pseudonym"]},
    )
    return {"pseudonym": entry}


@router.delete("/pseudonyms/{original}")
async def delete_pseudonym(original: str, svc: OpenProjectDep, db: DbDep) -> dict:
    from qualcoder_api.services import pseudonyms

    entry = next(
        (d for d in pseudonyms.load_pseudonyms(svc.project_path) if d["original"] == original),
        None,
    )
    pseudonyms.delete_pseudonym(svc.project_path, original)
    await audit.record(
        db, user=get_codername(), action="pseudonym.delete", entity="pseudonym",
        detail={"original": original, "pseudonym": (entry or {}).get("pseudonym") or ""},
    )
    return {"ok": True}


# ----------------------------------------------------------------------
# Speakers (transcript speaker-turn detection + coding)
# ----------------------------------------------------------------------

class SpeakersDetectRequest(BaseModel):
    fid: int | None = None
    identifiers: list[str] = ["name"]  # name|hash|at|bracket|brace|custom
    custom_regex: str = ""


class SpeakersMarkRequest(SpeakersDetectRequest):
    selected: list[str] | None = None


def _speakers_mark_detail(result: dict) -> dict:
    """Audit detail for a speaker run: the created code ids + coding ids
    (capped so the undo stays bounded)."""
    detail = {
        "turns_marked": result.get("turns_marked", 0),
        "codes_created": result.get("codes_created", 0),
        "skipped_duplicates": result.get("skipped_duplicates", 0),
    }
    ctids = result.get("created_ctids") or []
    if len(ctids) <= 5000:
        detail["created_code_ids"] = result.get("created_code_ids") or []
        detail["created_ctids"] = ctids
    else:
        detail["too_many_codings"] = True
    return detail


@router.post("/speakers/detect")
async def speakers_detect(req: SpeakersDetectRequest, db: DbDep) -> dict:
    from qualcoder_api.services import speakers

    try:
        return await speakers.detect_speakers(
            db, req.fid, req.identifiers, req.custom_regex
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.post("/speakers/mark")
async def speakers_mark(req: SpeakersMarkRequest, db: DbDep) -> dict:
    from qualcoder_api.services import speakers

    owner = get_codername()
    try:
        result = await speakers.mark_speakers(
            db, req.fid, req.identifiers, req.custom_regex, req.selected, owner
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await audit.record(
        db, user=owner, action="speakers.mark", entity="code_text",
        detail=_speakers_mark_detail(result),
    )
    return result


# ----------------------------------------------------------------------
# References (bibliography)
# ----------------------------------------------------------------------

@router.get("/references")
async def list_references(db: DbDep) -> dict:
    from qualcoder_api.services.references import list_references

    return {"references": await list_references(db)}


@router.delete("/references/{risid}", status_code=204)
async def delete_reference(risid: int, db: DbDep) -> None:
    from qualcoder_api.services.references import delete_reference

    ris_rows = [
        dict(r._mapping)
        for r in (await db.execute(select(tables.ris).where(tables.ris.c.risid == risid))).all()
    ]
    source_ids = [
        r[0]
        for r in (await db.execute(select(tables.source.c.id).where(tables.source.c.risid == risid))).all()
    ]
    await delete_reference(db, risid)
    await audit.record(
        db, user=get_codername(), action="reference.delete", entity="ris",
        entity_id=risid, detail={"rows": ris_rows, "source_ids": source_ids},
    )


# ----------------------------------------------------------------------
# Bad file links (broken mediapath repair + bulk path rename)
# ----------------------------------------------------------------------

class MediapathUpdate(BaseModel):
    mediapath: str


class BulkRenameRequest(BaseModel):
    old: str
    new: str


def _link_status(project_path: str, mediapath: str | None) -> dict:
    """Split ``type:path`` and report whether the file exists."""
    if mediapath is None or ":" not in mediapath:
        return {"kind": "internal", "path": "", "exists": True, "mediapath": mediapath or ""}
    kind, path = mediapath.split(":", 1)
    exists = os.path.exists(path)
    return {"kind": kind, "path": path, "exists": exists, "mediapath": mediapath}


@router.get("/sources/bad-links")
async def bad_links(db: DbDep, svc: ServiceDep) -> dict:
    """Sources whose media path does not exist on disk (external links)."""
    rows = await db.execute(
        select(
            tables.source.c.id,
            tables.source.c.name,
            tables.source.c.mediapath,
        ).where(tables.source.c.mediapath.is_not(None))
    )
    links = []
    for sid, name, mediapath in rows:
        status = _link_status(svc.project_path, mediapath)
        if status["kind"] == "internal":
            continue
        if not status["exists"]:
            status.update({"id": sid, "name": name})
            links.append(status)
    links.sort(key=lambda item: (item["name"] or "").lower())
    return {"links": links}


@router.patch("/sources/{source_id}/mediapath", response_model=dict)
async def update_mediapath(source_id: int, req: MediapathUpdate, db: DbDep) -> dict:
    """Replace a broken link with a new path (filename must match)."""
    row = (
        await db.execute(
            select(tables.source.c.name, tables.source.c.mediapath).where(
                tables.source.c.id == source_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="source not found")
    name, old_mediapath = row
    new_path = req.mediapath.replace("\\", "/")
    new_name = new_path.split("/")[-1]
    if new_name != name:
        raise HTTPException(status_code=422, detail="filename does not match the source")
    kind = "docs"
    if old_mediapath and ":" in old_mediapath:
        kind = old_mediapath.split(":", 1)[0]
    await db.execute(text(
            "UPDATE source SET mediapath = :mp WHERE id = :id"
        ),
        {"mp": f"{kind}:{new_path}", "id": source_id},
    )
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    _updated = (
        await db.execute(select(tables.source).where(tables.source.c.id == source_id))
    ).first()
    if _updated is not None:
        await _capture(
            db, "source", "update", "id", source_id, _rowdict(_updated)
        )
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="source.link_fix", entity="source",
        entity_id=source_id, detail={"old": old_mediapath, "new": f"{kind}:{new_path}"},
    )
    return {"ok": True, "mediapath": f"{kind}:{new_path}"}


@router.post("/sources/bulk-rename-path")
async def bulk_rename_path(req: BulkRenameRequest, db: DbDep) -> dict:
    """Replace a path fragment in every external link (manage_links port).

    Only links containing ``old`` exactly once are updated.
    """
    old_text = req.old.replace("\\", "/")
    new_text = req.new.replace("\\", "/")
    if not old_text or old_text == new_text:
        raise HTTPException(status_code=422, detail="old and new values must differ")
    rows = await db.execute(
        select(tables.source.c.id, tables.source.c.mediapath).where(
            tables.source.c.mediapath.is_not(None)
        )
    )
    updated = 0
    skipped = 0
    updated_rows: list[list] = []
    for sid, mediapath in rows:
        if mediapath is None or ":" not in mediapath:
            continue
        kind, path = mediapath.split(":", 1)
        instances = path.count(old_text)
        if instances == 1:
            new_path = f"{kind}:{path.replace(old_text, new_text)}"
            await db.execute(
                text("UPDATE source SET mediapath = :mp WHERE id = :id"),
                {"mp": new_path, "id": sid},
            )
            updated_rows.append([sid, mediapath, new_path])
            updated += 1
        elif instances > 1:
            skipped += 1
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    for sid, _old, _new in updated_rows:
        _row = (
            await db.execute(select(tables.source).where(tables.source.c.id == sid))
        ).first()
        if _row is not None:
            await _capture(db, "source", "update", "id", sid, _rowdict(_row))
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="source.link_fix", entity="source",
        detail={"bulk": True, "old": old_text, "new": new_text, "updated": updated,
                "rows": updated_rows[:5000]},
    )
    return {"ok": True, "updated": updated, "skipped_multiples": skipped}


# ----------------------------------------------------------------------
# Text file replacement (re-anchoring port)
# ----------------------------------------------------------------------

@router.post("/sources/{source_id}/replace")
async def replace_source_file(
    source_id: int,
    svc: OpenProjectDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    owner: str | None = Form(None),
) -> dict:
    """Replace a text source with a new document; re-anchors codings,
    annotations and case links by first-match text."""
    from qualcoder_api.services.file_replacement import replace_text_file

    before_row = (
        await db.execute(select(tables.source).where(tables.source.c.id == source_id))
    ).first()
    before_source = dict(before_row._mapping) if before_row is not None else None
    segments: dict[str, list[dict]] = {}
    for table, col in (
        (tables.code_text, tables.code_text.c.fid),
        (tables.annotation, tables.annotation.c.fid),
        (tables.case_text, tables.case_text.c.fid),
    ):
        rows = (await db.execute(select(table).where(col == source_id))).all()
        segments[table.name] = [dict(r._mapping) for r in rows]
    from qualcoder_api.core.security import sanitize_filename

    tmp = os.path.join(svc.project_path, f"_replace_{sanitize_filename(file.filename, 'replace')}")
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    try:
        result = await replace_text_file(
            db, svc.project_path, source_id, tmp, file.filename or "", resolve_owner(owner)
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)
    await audit.record(
        db, user=get_codername(), action="source.replace", entity="source",
        entity_id=source_id,
        detail={
            **result,
            "before_source": before_source,
            "code_text": segments.get("code_text", []),
            "annotation": segments.get("annotation", []),
            "case_text": segments.get("case_text", []),
        },
    )
    return result


# ----------------------------------------------------------------------
# Saved file filters (files_filter table)
# ----------------------------------------------------------------------

class FilterCreate(BaseModel):
    name: str
    filter: str = "{}"
    owner: str | None = None


@router.get("/sources/filters")
async def list_filters(db: DbDep) -> dict:
    rows = await db.execute(
        select(tables.files_filter).order_by(tables.files_filter.c.name)
    )
    return {
        "filters": [
            {
                "filterid": r.filterid,
                "name": r.name,
                "filter": r.filter or "{}",
                "owner": r.owner or "",
            }
            for r in rows
        ]
    }


@router.post("/sources/filters", status_code=201)
async def create_filter(req: FilterCreate, db: DbDep) -> dict:
    from qualcoder_api.persistence.repositories import _capture, _inserted_pk, _rowdict

    result = await db.execute(
        tables.files_filter.insert().values(
            name=req.name, filter=req.filter, owner=resolve_owner(req.owner)
        )
    )
    filterid = _inserted_pk(result)
    await db.commit()
    row = (
        await db.execute(
            select(tables.files_filter).where(tables.files_filter.c.filterid == filterid)
        )
    ).first()
    if row is not None:
        await _capture(db, "files_filter", "insert", "filterid", filterid, _rowdict(row))
        await db.commit()
    await audit.record(
        db, user=get_codername(), action="filter.create", entity="files_filter",
        entity_id=filterid,
        detail={"name": req.name, "row": dict(row._mapping) if row is not None else None},
    )
    return {"ok": True, "filterid": filterid}


@router.delete("/sources/filters/{filterid}", status_code=204)
async def delete_filter(filterid: int, db: DbDep) -> None:
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    row = (
        await db.execute(
            select(tables.files_filter).where(tables.files_filter.c.filterid == filterid)
        )
    ).first()
    await db.execute(delete(tables.files_filter).where(tables.files_filter.c.filterid == filterid))
    if row is not None:
        await _capture(db, "files_filter", "delete", "filterid", filterid, _rowdict(row))
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="filter.delete", entity="files_filter",
        entity_id=filterid,
        detail={"row": dict(row._mapping) if row is not None else None},
    )


# ----------------------------------------------------------------------
# Reference attachments
# ----------------------------------------------------------------------

@router.post("/references/{risid}/attach")
async def attach_reference_file(
    risid: int,
    svc: OpenProjectDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    owner: str | None = Form(None),
) -> dict:
    """Attach a PDF/EPUB (or any document) to a reference as a coded source."""
    from qualcoder_api.services.references import attach_file

    assert svc.session_factory is not None
    from qualcoder_api.core.security import sanitize_filename as _sanitize

    tmp = os.path.join(svc.project_path, f"_attach_{_sanitize(file.filename, 'attach')}")
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    try:
        result = await attach_file(
            svc.session_factory, svc.project_path, risid, tmp,
            file.filename or "attachment.pdf", resolve_owner(owner),
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    finally:
        import contextlib

        with contextlib.suppress(OSError):
            os.remove(tmp)
    await audit.record(
        db, user=get_codername(), action="reference.attach", entity="source",
        entity_id=result["source_id"],
        detail={"risid": risid, "name": result["name"],
                "row": await _source_row(db, result["source_id"])},
    )
    return result


async def _source_row(db, source_id: int) -> dict | None:
    row = (await db.execute(select(tables.source).where(tables.source.c.id == source_id))).first()
    return dict(row._mapping) if row is not None else None


@router.delete("/references/{risid}/attach/{source_id}", status_code=204)
async def detach_reference_file(risid: int, source_id: int, db: DbDep) -> None:
    from qualcoder_api.services.references import detach_file

    await detach_file(db, risid, source_id)
    await audit.record(
        db, user=get_codername(), action="reference.detach", entity="source",
        entity_id=source_id, detail={"risid": risid},
    )


# ----------------------------------------------------------------------
# Code color scheme
# ----------------------------------------------------------------------

class ColorSchemeRequest(BaseModel):
    colors: list[str]
    ranges: list[dict] = []


@router.get("/color-scheme")
async def get_color_scheme() -> dict:
    from qualcoder_api.services import user_settings

    return user_settings.get_color_scheme()


@router.put("/color-scheme")
async def save_color_scheme(req: ColorSchemeRequest) -> dict:
    from qualcoder_api.services import user_settings

    try:
        return user_settings.save_color_scheme(req.colors, req.ranges)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.delete("/color-scheme")
async def reset_color_scheme() -> dict:
    from qualcoder_api.services import user_settings

    return user_settings.reset_color_scheme()
