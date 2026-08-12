"""Sources API — list, get, import (upload), link, update, delete."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, text

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.core.models import Source
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import SourceRepository
from qualcoder_api.services import audit
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceUpdate(BaseModel):
    name: str | None = None
    memo: str | None = None
    owner: str | None = None


class LinkRequest(BaseModel):
    path: str
    owner: str | None = None


class CodesUsedItem(BaseModel):
    cid: int
    name: str
    color: str
    count: int


class SourceCaseItem(BaseModel):
    caseid: int
    name: str


class SourceAttributeItem(BaseModel):
    name: str
    value: str
    attr_type: str


class SourceDetails(BaseModel):
    """Aggregated details for a single source file."""

    source: Source
    text_codings: int
    image_codings: int
    av_codings: int
    codes_used: list[CodesUsedItem]
    cases: list[SourceCaseItem]
    attributes: list[SourceAttributeItem]


@router.get("", response_model=list[Source])
async def list_sources(db: DbDep) -> list[Source]:
    return await SourceRepository(db).list_sources()


@router.get("/{source_id}", response_model=Source)
async def get_source(source_id: int, db: DbDep) -> Source:
    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@router.get("/{source_id}/details", response_model=SourceDetails)
async def source_details(source_id: int, db: DbDep) -> SourceDetails:
    """Aggregate details for one source: codings, codes, cases, attributes."""
    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    text_codings = 0
    image_codings = 0
    av_codings = 0
    for tbl, col, name in (
        ("code_text_visible", "fid", "text"),
        ("code_image_visible", "id", "image"),
        ("code_av_visible", "id", "av"),
    ):
        count = (
            await db.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE {col} = :sid"), {"sid": source_id}
            )
        ).scalar_one()
        if name == "text":
            text_codings = count
        elif name == "image":
            image_codings = count
        else:
            av_codings = count

    counts: dict[int, int] = {}
    for tbl, col in (
        ("code_text_visible", "fid"),
        ("code_image_visible", "id"),
        ("code_av_visible", "id"),
    ):
        rows = await db.execute(
            text(f"SELECT cid FROM {tbl} WHERE {col} = :sid"), {"sid": source_id}
        )
        for r in rows:
            cid = r[0]
            counts[cid] = counts.get(cid, 0) + 1
    codes_used: list[CodesUsedItem] = []
    if counts:
        code_rows = await db.execute(
            select(tables.code_name.c.cid, tables.code_name.c.name, tables.code_name.c.color).where(
                tables.code_name.c.cid.in_(counts.keys())
            )
        )
        by_cid = {r[0]: (r[1] or "", r[2] or "#ffffff") for r in code_rows}
        for cid, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
            name, color = by_cid.get(cid, ("", "#ffffff"))
            codes_used.append(CodesUsedItem(cid=cid, name=name, color=color, count=count))

    case_rows = await db.execute(
        select(tables.cases.c.caseid, tables.cases.c.name)
        .select_from(
            tables.case_text.join(tables.cases, tables.cases.c.caseid == tables.case_text.c.caseid)
        )
        .where(tables.case_text.c.fid == source_id)
        .distinct()
    )
    cases = [SourceCaseItem(caseid=r[0], name=r[1] or "") for r in case_rows]

    attr_rows = await db.execute(
        select(tables.attribute.c.name, tables.attribute.c.value, tables.attribute.c.attr_type).where(
            tables.attribute.c.id == source_id,
            tables.attribute.c.attr_type == "file",
        )
    )
    attributes = [
        SourceAttributeItem(name=r[0] or "", value=r[1] or "", attr_type=r[2] or "")
        for r in attr_rows
    ]

    return SourceDetails(
        source=source,
        text_codings=text_codings,
        image_codings=image_codings,
        av_codings=av_codings,
        codes_used=codes_used,
        cases=cases,
        attributes=attributes,
    )


@router.get("/{source_id}/file")
async def source_file(source_id: int, db: DbDep, svc: ServiceDep) -> FileResponse:
    """Serve the raw bytes of a source file (internal or external link)."""
    from qualcoder_api.services.source_files import content_type_for, resolve_source_path

    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    path = resolve_source_path(svc.project_path, source.mediapath, source.name)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type=content_type_for(source.name), filename=source.name)


@router.get("/{source_id}/thumbnail")
async def source_thumbnail(
    source_id: int, db: DbDep, svc: ServiceDep, max_size: int = 300
) -> Response:
    """Serve a PNG thumbnail for image sources and PDFs."""
    from qualcoder_api.services.source_files import build_thumbnail, resolve_source_path

    max_size = min(1024, max(64, max_size))
    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    path = resolve_source_path(svc.project_path, source.mediapath, source.name)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    png = await build_thumbnail(path, source.media_type, source.name, max_size)
    if png is None:
        raise HTTPException(status_code=404, detail="thumbnail not available")
    return Response(content=png, media_type="image/png")


@router.post("/import", response_model=Source)
async def import_source(
    db: DbDep,
    svc: ServiceDep,
    file: Annotated[UploadFile, File()],
    owner: str | None = Form(None),
) -> Source:
    """Upload a file; copies it into the project folder and registers it."""
    from qualcoder_api.services.import_service import ImportService

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    session_factory = svc.session_factory
    if session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = svc.project_path + "/_upload_" + (file.filename or "upload")

    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    try:
        service = ImportService(svc.project_path, session_factory)
        source = await service.import_file(
            tmp, owner=resolve_owner(owner), link=False, filename=file.filename
        )
    finally:
        os.remove(tmp)
    if source is None:
        raise HTTPException(status_code=409, detail="duplicate filename or import failed")
    await audit.record(
        db, user=resolve_owner(owner), action="source.import", entity="source",
        entity_id=source.id, detail={"name": source.name},
    )
    return source


@router.post("/link", response_model=Source)
async def link_source(req: LinkRequest, db: DbDep, svc: ServiceDep) -> Source:
    """Register an external file by path (no copy)."""
    from qualcoder_api.services.import_service import ImportService

    session_factory = svc.session_factory
    if session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    service = ImportService(svc.project_path, session_factory)
    source = await service.import_file(req.path, owner=resolve_owner(req.owner), link=True)
    if source is None:
        raise HTTPException(status_code=409, detail="duplicate filename")
    await audit.record(
        db, user=resolve_owner(req.owner), action="source.link", entity="source",
        entity_id=source.id, detail={"name": source.name},
    )
    return source


@router.patch("/{source_id}", response_model=Source)
async def update_source(source_id: int, req: SourceUpdate, db: DbDep) -> Source:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    old_row = (
        await db.execute(
            select(tables.source.c.name, tables.source.c.memo).where(
                tables.source.c.id == source_id
            )
        )
    ).first()
    old = dict(old_row._mapping) if old_row is not None else {}
    source = await SourceRepository(db).update_source(
        source_id, **req.model_dump(exclude_none=True)
    )
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    await audit.record(
        db, user=get_codername(), action="source.update", entity="source",
        entity_id=source_id, source_id=source_id,
        detail={
            "before_name": old.get("name"),
            "after_name": source.name,
            "before_memo": old.get("memo"),
            "after_memo": source.memo,
        },
    )
    return source


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: int, db: DbDep) -> None:
    await SourceRepository(db).delete_source(source_id)
    await audit.record(
        db, user=get_codername(), action="source.delete", entity="source", entity_id=source_id
    )
