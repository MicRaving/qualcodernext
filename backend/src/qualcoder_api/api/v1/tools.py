"""Project tools API — bookmarks, pseudonyms, speakers, references,
bad-link repair, saved file filters, text file replacement."""

from __future__ import annotations

import contextlib
import os
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select, text

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
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
    return await ProjectRepository(db).set_bookmark(file_id=req.file_id, pos=req.pos)


@router.put("/bookmarks/av")
async def set_av_bookmark(req: AVBookmarkRequest, db: DbDep) -> dict:
    return await ProjectRepository(db).set_av_bookmark(
        file_id=req.file_id, msec=req.msec, textpos=req.textpos
    )


# ----------------------------------------------------------------------
# Pseudonyms (pseudonyms.json in the project folder)
# ----------------------------------------------------------------------

class PseudonymAdd(BaseModel):
    original: str
    pseudonym: str = ""


class PseudonymDelete(BaseModel):
    original: str


@router.get("/pseudonyms")
async def list_pseudonyms(svc: ServiceDep) -> dict:
    from qualcoder_api.services import pseudonyms

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    return {"pseudonyms": pseudonyms.load_pseudonyms(svc.project_path)}


@router.post("/pseudonyms")
async def add_pseudonym(req: PseudonymAdd, svc: ServiceDep) -> dict:
    from qualcoder_api.services import pseudonyms

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    try:
        entry = pseudonyms.add_pseudonym(svc.project_path, req.original, req.pseudonym)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"pseudonym": entry}


@router.delete("/pseudonyms/{original}")
async def delete_pseudonym(original: str, svc: ServiceDep) -> dict:
    from qualcoder_api.services import pseudonyms

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    pseudonyms.delete_pseudonym(svc.project_path, original)
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
        detail={"turns_marked": result.get("turns_marked", 0)},
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

    await delete_reference(db, risid)
    await audit.record(
        db, user=get_codername(), action="reference.delete", entity="ris",
        entity_id=risid,
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
            updated += 1
        elif instances > 1:
            skipped += 1
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="source.link_fix", entity="source",
        detail={"bulk": True, "old": old_text, "new": new_text, "updated": updated},
    )
    return {"ok": True, "updated": updated, "skipped_multiples": skipped}


# ----------------------------------------------------------------------
# Text file replacement (re-anchoring port)
# ----------------------------------------------------------------------

@router.post("/sources/{source_id}/replace")
async def replace_source_file(
    source_id: int,
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    owner: str | None = Form(None),
) -> dict:
    """Replace a text source with a new document; re-anchors codings,
    annotations and case links by first-match text."""
    from qualcoder_api.services.file_replacement import replace_text_file

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = svc.project_path + "/_replace_" + (file.filename or "replace")
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
        entity_id=source_id, detail=result,
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
    from qualcoder_api.persistence.repositories import _inserted_pk

    result = await db.execute(
        tables.files_filter.insert().values(
            name=req.name, filter=req.filter, owner=resolve_owner(req.owner)
        )
    )
    await db.commit()
    return {"ok": True, "filterid": _inserted_pk(result)}


@router.delete("/sources/filters/{filterid}", status_code=204)
async def delete_filter(filterid: int, db: DbDep) -> None:
    await db.execute(delete(tables.files_filter).where(tables.files_filter.c.filterid == filterid))
    await db.commit()


# ----------------------------------------------------------------------
# Reference attachments
# ----------------------------------------------------------------------

@router.post("/references/{risid}/attach")
async def attach_reference_file(
    risid: int,
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    owner: str | None = Form(None),
) -> dict:
    """Attach a PDF/EPUB (or any document) to a reference as a coded source."""
    from qualcoder_api.services.references import attach_file

    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = svc.project_path + "/_attach_" + (file.filename or "attach")
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
        entity_id=result["source_id"], detail={"risid": risid, "name": result["name"]},
    )
    return result


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
