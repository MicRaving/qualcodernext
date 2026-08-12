"""Codings API — text/image/AV segment CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
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
    cids: list[int]
    find_texts: list[str] = Field(default_factory=list)
    mode: str = "all"  # all | first | last | code_within_code <cid>
    use_regex: bool = False
    suggest: bool = False
    prompt: str | None = None
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
    from qualcoder_api.services.coding_service import ai_autocode

    owner = resolve_owner(req.owner)
    if not req.cids:
        raise HTTPException(status_code=422, detail="at least one code required")
    if not req.find_texts and not (req.prompt or "").strip():
        raise HTTPException(status_code=422, detail="search texts or a coding prompt required")
    try:
        prompt = (req.prompt or "").strip()
        if prompt:
            if req.fid is None:
                raise HTTPException(
                    status_code=422, detail="prompt-based autocode requires a single source"
                )
            result = await ai_autocode(
                db,
                fid=req.fid,
                cids=req.cids,
                prompt=prompt,
                suggest=req.suggest,
                owner=owner,
            )
        else:
            result = await autocode(
                db,
                fid=req.fid,
                cids=req.cids,
                find_texts=req.find_texts,
                mode=req.mode,
                use_regex=req.use_regex,
                suggest=req.suggest,
                owner=owner,
            )
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid regex or mode") from None
    await audit.record(
        db, user=owner, action="coding.autocode", entity="code_text",
        source_id=req.fid,
        detail={
            "cids": req.cids,
            "count": result["count"],
            "prompt": (req.prompt or "")[:200],
            "suggested": [s["name"] for s in result["suggested"]],
        },
    )
    return result


class AutocodeBatchRequest(BaseModel):
    source_ids: list[int]
    cids: list[int]
    prompt: str
    suggest: bool = False
    owner: str | None = None


@router.post("/autocode/batch", status_code=202)
async def autocode_batch_endpoint(req: AutocodeBatchRequest, svc: ServiceDep, db: DbDep) -> dict:
    """Queue one background autocode job per source file (prompt-based only).
    Jobs are created in the ``queued`` state and started one by one by the
    UI dispatcher via ``POST /codings/autocode/jobs/{id}/start``."""
    from qualcoder_api.services import audit
    from qualcoder_api.services.autocode_jobs import start_batch

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    owner = resolve_owner(req.owner)
    if not req.source_ids:
        raise HTTPException(status_code=422, detail="no source files given")
    if not req.cids:
        raise HTTPException(status_code=422, detail="at least one code required")
    if not (req.prompt or "").strip():
        raise HTTPException(status_code=422, detail="a coding prompt is required")

    from sqlalchemy import select

    from qualcoder_api.core.models import MediaType
    from qualcoder_api.persistence import tables

    rows = (
        await db.execute(
            select(tables.source.c.id, tables.source.c.name, tables.source.c.mediapath).where(
                tables.source.c.id.in_(req.source_ids)
            )
        )
    ).all()
    by_id = {r[0]: r for r in rows}
    missing = [sid for sid in req.source_ids if sid not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"sources not found: {missing}")
    non_text = [
        sid
        for sid, r in by_id.items()
        if MediaType.from_mediapath(r[2]).value != "text"
    ]
    if non_text:
        raise HTTPException(
            status_code=422, detail=f"autocode works on text sources only: {non_text}"
        )

    job_ids = start_batch(
        session_factory=svc.session_factory,
        project_path=svc.project_path,
        source_ids=list(req.source_ids),
        cids=req.cids,
        prompt=req.prompt.strip(),
        suggest=req.suggest,
        owner=owner,
        auto_start=False,
    )
    await audit.record(
        db, user=owner, action="coding.autocode", entity="code_text",
        source_id=req.source_ids[0],
        detail={"batch": len(req.source_ids), "job_ids": job_ids, "cids": req.cids},
    )
    return {"job_ids": job_ids}


@router.get("/autocode/jobs/{job_id}")
async def autocode_job_status(job_id: str) -> dict:
    from qualcoder_api.services.autocode_jobs import get_job

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/autocode/jobs/{job_id}/{action}")
async def autocode_job_control(job_id: str, action: str) -> dict:
    """Queue controls: ``start``, ``pause``, ``resume``, ``cancel`` (a pause
    takes effect between files; the LLM call itself cannot be interrupted)."""
    from qualcoder_api.services.autocode_jobs import control_job

    if action not in ("start", "pause", "resume", "cancel"):
        raise HTTPException(status_code=422, detail="unknown action")
    ok = control_job(job_id, action)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or not controllable")
    return {"ok": True}


@router.delete("/autocode/jobs/{job_id}")
async def autocode_job_delete(job_id: str) -> dict:
    from qualcoder_api.services.autocode_jobs import control_job

    ok = control_job(job_id, "cancel")
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or already finished")
    return {"ok": True}


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
