"""Codings API — text/image/AV segment CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.core.models import AVCoding, Coding, ImageCoding
from qualcoder_api.persistence.repositories import CodingRepository
from qualcoder_api.services import audit
from qualcoder_api.services.coding_service import (
    autocode,
    commit_edit,
    shift_positions,
    undo_codings,
)
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/codings", tags=["codings"])


class TextCodingCreate(BaseModel):
    cid: int
    fid: int
    seltext: str
    pos0: int = Field(ge=0)
    pos1: int = Field(ge=0)
    owner: str | None = None
    memo: str = ""
    avid: int | None = None
    important: int = 0


class ImageCodingCreate(BaseModel):
    id: int  # source id
    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    cid: int
    owner: str | None = None
    memo: str = ""
    important: int = 0
    pdf_page: int | None = None


class AVCodingCreate(BaseModel):
    id: int  # source id
    pos0: int = Field(ge=0)
    pos1: int = Field(ge=0)
    cid: int
    owner: str | None = None
    memo: str = ""
    important: int = 0


class TextCodingUpdate(BaseModel):
    memo: str | None = None
    important: int | None = None
    pos0: int | None = None
    pos1: int | None = None


@router.post("/text", response_model=Coding, status_code=201)
async def create_text_coding(req: TextCodingCreate, db: DbDep) -> Coding:
    if req.pos1 <= req.pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    payload = req.model_dump()
    payload["owner"] = resolve_owner(payload["owner"])
    coding = await CodingRepository(db).add_text_coding(**payload)
    await audit.record(
        db, user=payload["owner"], action="coding.create", entity="code_text",
        entity_id=coding.ctid, source_id=req.fid,
        detail=coding.model_dump(),
    )
    return coding


@router.get("/text/{fid}", response_model=list[Coding])
async def list_text_codings(fid: int, db: DbDep) -> list[Coding]:
    return await CodingRepository(db).list_text_codings_for_file(fid)


@router.patch("/text/{ctid}", response_model=Coding)
async def update_text_coding(ctid: int, req: TextCodingUpdate, db: DbDep) -> Coding:
    if req.pos0 is not None and req.pos1 is not None and req.pos1 <= req.pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    coding = await CodingRepository(db).update_text_coding(
        ctid, **req.model_dump(exclude_none=True)
    )
    if coding is None:
        raise HTTPException(status_code=404, detail="coding not found")
    await audit.record(
        db, user=get_codername(), action="coding.update", entity="code_text",
        entity_id=ctid, source_id=coding.fid,
        detail=coding.model_dump(),
    )
    return coding


@router.delete("/text/{ctid}", status_code=204)
async def delete_text_coding(ctid: int, db: DbDep) -> None:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    row = (
        await db.execute(select(tables.code_text).where(tables.code_text.c.ctid == ctid))
    ).first()
    detail = dict(row._mapping) if row is not None else {}
    await CodingRepository(db).delete_text_coding(ctid)
    await audit.record(
        db, user=get_codername(), action="coding.delete", entity="code_text",
        entity_id=ctid, source_id=detail.get("fid"), detail=detail,
    )


@router.post("/image", response_model=ImageCoding, status_code=201)
async def create_image_coding(req: ImageCodingCreate, db: DbDep) -> ImageCoding:
    payload = req.model_dump()
    payload["owner"] = resolve_owner(payload["owner"])
    coding = await CodingRepository(db).add_image_coding(**payload)
    await audit.record(
        db, user=payload["owner"], action="coding.create", entity="code_image",
        entity_id=coding.imid, source_id=req.id,
        detail=coding.model_dump(),
    )
    return coding


@router.get("/image/{source_id}", response_model=list[ImageCoding])
async def list_image_codings(source_id: int, db: DbDep) -> list[ImageCoding]:
    return await CodingRepository(db).list_image_codings_for_file(source_id)


class ImageCodingUpdate(BaseModel):
    x1: int | None = Field(default=None, ge=0)
    y1: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    cid: int | None = None
    memo: str | None = None
    important: int | None = None


@router.patch("/image/{imid}", response_model=ImageCoding)
async def update_image_coding(imid: int, req: ImageCodingUpdate, db: DbDep) -> ImageCoding:
    """Update a coded image/PDF rectangle (port of move/resize rectangle)."""
    coding = await CodingRepository(db).update_image_coding(
        imid, **req.model_dump(exclude_none=True)
    )
    if coding is None:
        raise HTTPException(status_code=404, detail="coding not found")
    await audit.record(
        db, user=get_codername(), action="coding.update", entity="code_image",
        entity_id=imid, source_id=coding.id, detail=coding.model_dump(),
    )
    return coding


@router.delete("/image/{imid}", status_code=204)
async def delete_image_coding(imid: int, db: DbDep) -> None:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    row = (
        await db.execute(select(tables.code_image).where(tables.code_image.c.imid == imid))
    ).first()
    detail = dict(row._mapping) if row is not None else {}
    await CodingRepository(db).delete_image_coding(imid)
    await audit.record(
        db, user=get_codername(), action="coding.delete", entity="code_image",
        entity_id=imid, source_id=detail.get("id"), detail=detail,
    )


@router.post("/av", response_model=AVCoding, status_code=201)
async def create_av_coding(req: AVCodingCreate, db: DbDep) -> AVCoding:
    if req.pos1 <= req.pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    payload = req.model_dump()
    payload["owner"] = resolve_owner(payload["owner"])
    coding = await CodingRepository(db).add_av_coding(**payload)
    await audit.record(
        db, user=payload["owner"], action="coding.create", entity="code_av",
        entity_id=coding.avid, source_id=req.id,
        detail=coding.model_dump(),
    )
    return coding


@router.get("/av/{source_id}", response_model=list[AVCoding])
async def list_av_codings(source_id: int, db: DbDep) -> list[AVCoding]:
    return await CodingRepository(db).list_av_codings_for_file(source_id)


@router.delete("/av/{avid}", status_code=204)
async def delete_av_coding(avid: int, db: DbDep) -> None:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    row = (
        await db.execute(select(tables.code_av).where(tables.code_av.c.avid == avid))
    ).first()
    detail = dict(row._mapping) if row is not None else {}
    await CodingRepository(db).delete_av_coding(avid)
    await audit.record(
        db, user=get_codername(), action="coding.delete", entity="code_av",
        entity_id=avid, source_id=detail.get("id"), detail=detail,
    )


class AutocodeRequest(BaseModel):
    fid: int | None = None
    cid: int
    find_texts: list[str]
    mode: str = "all"  # all | first | last | code_within_code <cid>
    use_regex: bool = False
    owner: str | None = None


class ShiftPositionsRequest(BaseModel):
    prev_text: str
    new_text: str
    codings: list[dict] = Field(default_factory=list)
    annotations: list[dict] = Field(default_factory=list)
    case_text: list[dict] = Field(default_factory=list)


class CommitEditRequest(BaseModel):
    fid: int
    new_text: str
    owner: str | None = None


class UndoCodingsRequest(BaseModel):
    items: list[dict]


@router.post("/autocode", status_code=201)
async def autocode_endpoint(req: AutocodeRequest, db: DbDep) -> dict:
    owner = resolve_owner(req.owner)
    try:
        created = await autocode(
            db,
            fid=req.fid,
            cid=req.cid,
            find_texts=req.find_texts,
            mode=req.mode,
            use_regex=req.use_regex,
            owner=owner,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid regex or mode") from None
    await audit.record(
        db, user=owner, action="coding.autocode", entity="code_text",
        source_id=req.fid,
        detail={"cid": req.cid, "count": len(created), "find_texts": req.find_texts},
    )
    return {"created": created, "count": len(created)}


@router.post("/shift-positions")
async def shift_positions_endpoint(req: ShiftPositionsRequest) -> dict:
    """Stateless pure computation: no project required."""
    return shift_positions(
        req.prev_text, req.new_text, req.codings, req.annotations, req.case_text
    )


@router.post("/commit-edit")
async def commit_edit_endpoint(req: CommitEditRequest, db: DbDep) -> dict:
    old_text = ""
    try:
        from sqlalchemy import select

        from qualcoder_api.persistence import tables

        old_row = (
            await db.execute(select(tables.source.c.fulltext).where(tables.source.c.id == req.fid))
        ).first()
        if old_row is not None:
            old_text = old_row[0] or ""
    except Exception:
        old_text = ""
    try:
        result = await commit_edit(
            db, fid=req.fid, new_text=req.new_text, owner=resolve_owner(req.owner)
        )
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from None
    await audit.record(
        db, user=get_codername(), action="source.edit", entity="source",
        source_id=req.fid,
        detail={
            # The FULL before/after text — the undo path restores the source
            # from these, so truncating would destroy everything past N chars.
            "before": old_text,
            "after": req.new_text,
            "before_length": len(old_text),
            "new_length": len(req.new_text),
        },
    )
    return result


@router.post("/undo")
async def undo_endpoint(req: UndoCodingsRequest, db: DbDep) -> dict:
    restored = await undo_codings(db, req.items)
    await audit.record(
        db, user=get_codername(), action="coding.undo", entity="code_text",
        detail={"restored": restored},
    )
    return {"restored": restored}
