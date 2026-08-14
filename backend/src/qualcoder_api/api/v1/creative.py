"""Creative coding API — MAXQDA-style scratchpad items.

Each item is an idea, quote or fragment (``creative_item`` row). Items with
a source reference (``source_fid`` + ``pos0``/``pos1``) point at a source
span; promoting such an item creates a new code and codes the referenced
span with it. Mutations are audit-recorded and journaled to ``sync_log``
exactly like the segment-link endpoints.
"""

from __future__ import annotations

import datetime
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import CursorResult, Result

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodeRepository, CodingRepository
from qualcoder_api.services import audit, sync
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/creative", tags=["creative"])


def _now() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _inserted_pk(result: Result) -> int:
    """First inserted primary key from an INSERT statement result."""
    pk = cast(CursorResult[Any], result).inserted_primary_key
    if pk is None:  # pragma: no cover - inserts always return a pk here
        raise RuntimeError("insert returned no primary key")
    return int(pk[0])


class CreativeCreate(BaseModel):
    text: str
    source_fid: int | None = None
    pos0: int | None = None
    pos1: int | None = None
    note: str = ""
    owner: str | None = None


class CreativeUpdate(BaseModel):
    text: str | None = None
    note: str | None = None


class CreativePromote(BaseModel):
    code_name: str
    catid: int | None = None


async def _resolve(db, data: dict) -> dict:
    """Attach the source name and the span's text excerpt (when sourced)."""
    out = dict(data)
    fid = data.get("source_fid")
    out["source_name"] = ""
    out["source_text"] = ""
    if fid is None:
        return out
    row = (
        await db.execute(
            select(tables.source.c.name, tables.source.c.fulltext).where(
                tables.source.c.id == fid
            )
        )
    ).first()
    if row is None:
        return out
    out["source_name"] = row[0]
    start = data.get("pos0")
    end = data.get("pos1")
    fulltext = row[1] or ""
    out["source_text"] = (
        fulltext[start:end] if start is not None and end is not None and 0 <= start < end <= len(fulltext) else ""
    )
    return out


async def _validate_span(db, fid: int | None, pos0: int | None, pos1: int | None) -> None:
    """Span positions must fall inside the source's text (422 otherwise)."""
    if fid is None:
        if pos0 is not None or pos1 is not None:
            raise HTTPException(status_code=422, detail="pos0/pos1 require source_fid")
        return
    if pos0 is None or pos1 is None:
        raise HTTPException(status_code=422, detail="source_fid requires pos0 and pos1")
    if pos1 <= pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    if pos0 < 0:
        raise HTTPException(status_code=422, detail="pos0 out of range")
    row = (
        await db.execute(
            select(tables.source.c.fulltext).where(tables.source.c.id == fid)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=422, detail=f"source {fid} not found")
    length = len(row[0] or "")
    if pos1 > length:
        raise HTTPException(status_code=422, detail=f"pos1 exceeds the source text length ({length})")


@router.get("", response_model=list[dict])
async def list_creative_items(db: DbDep) -> list[dict]:
    """All scratchpad items, newest first, with the source name and the
    referenced span's excerpt attached when the item is sourced."""
    rows = await db.execute(
        select(tables.creative_item).order_by(tables.creative_item.c.id.desc())
    )
    return [await _resolve(db, dict(r._mapping)) for r in rows]


@router.post("", response_model=dict, status_code=201)
async def create_creative_item(req: CreativeCreate, db: DbDep) -> dict:
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    await _validate_span(db, req.source_fid, req.pos0, req.pos1)
    owner = resolve_owner(req.owner)
    result = await db.execute(
        insert(tables.creative_item).values(
            text=text,
            source_fid=req.source_fid,
            pos0=req.pos0,
            pos1=req.pos1,
            note=req.note,
            owner=owner,
            date=_now(),
        )
    )
    await db.commit()
    item_id = _inserted_pk(result)
    row = (
        await db.execute(
            select(tables.creative_item).where(tables.creative_item.c.id == item_id)
        )
    ).first()
    assert row is not None
    data = dict(row._mapping)
    await sync.capture_insert(
        db, entity="creative_item", pk_name="id", pk_value=item_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=owner,
        action="creative.create",
        entity="creative_item",
        entity_id=item_id,
        source_id=req.source_fid,
        detail={
            "text": text[:200],
            "source_fid": req.source_fid,
            "pos0": req.pos0,
            "pos1": req.pos1,
            "row": data,
        },
    )
    return await _resolve(db, data)


@router.patch("/{item_id}", response_model=dict)
async def update_creative_item(item_id: int, req: CreativeUpdate, db: DbDep) -> dict:
    row = (
        await db.execute(
            select(tables.creative_item).where(tables.creative_item.c.id == item_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="creative item not found")
    before = dict(row._mapping)
    values = req.model_dump(exclude_none=True)
    if "text" in values:
        text = (values["text"] or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="text must not be empty")
        values["text"] = text
    if values:
        await db.execute(
            sa_update(tables.creative_item)
            .where(tables.creative_item.c.id == item_id)
            .values(**values)
        )
        await db.commit()
        row = (
            await db.execute(
                select(tables.creative_item).where(tables.creative_item.c.id == item_id)
            )
        ).first()
        assert row is not None
        data = dict(row._mapping)
        await sync.capture_update(
            db, entity="creative_item", pk_name="id", pk_value=item_id, row=data
        )
        await db.commit()
        await audit.record(
            db,
            user=get_codername(),
            action="creative.update",
            entity="creative_item",
            entity_id=item_id,
            source_id=data.get("source_fid"),
            detail={**values, "before": before},
        )
    return await _resolve(db, dict(row._mapping))


@router.delete("/{item_id}", status_code=204)
async def delete_creative_item(item_id: int, db: DbDep) -> None:
    row = (
        await db.execute(
            select(tables.creative_item).where(tables.creative_item.c.id == item_id)
        )
    ).first()
    await db.execute(
        delete(tables.creative_item).where(tables.creative_item.c.id == item_id)
    )
    if row is None:
        await db.commit()
        raise HTTPException(status_code=404, detail="creative item not found")
    data = dict(row._mapping)
    await sync.capture_delete(
        db, entity="creative_item", pk_name="id", pk_value=item_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=get_codername(),
        action="creative.delete",
        entity="creative_item",
        entity_id=item_id,
        source_id=data.get("source_fid"),
        detail=data,
    )


@router.post("/{item_id}/promote", response_model=dict)
async def promote_creative_item(item_id: int, req: CreativePromote, db: DbDep) -> dict:
    """Promote an item into a new code.

    Creates the code through ``CodeRepository.add_code`` (the same path as
    ``POST /codes``); when the item carries a source span, the excerpt is
    additionally coded with the new code through ``CodingRepository`` (the
    path used by ``POST /codings/text``). Returns the new ``cid`` and the
    ``ctid`` of the attached coding (``None`` for unsourced items).
    """
    row = (
        await db.execute(
            select(tables.creative_item).where(tables.creative_item.c.id == item_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="creative item not found")
    item = dict(row._mapping)
    name = (req.code_name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="code_name must not be empty")
    # Duplicate code names are rejected with 409 like POST /codes (the
    # case-insensitive pre-check mirrors the AI code-suggestion path).
    existing_rows = (await db.execute(select(tables.code_name.c.name))).all()
    if any(str(r[0]).strip().lower() == name.lower() for r in existing_rows if r[0]):
        raise HTTPException(status_code=409, detail="duplicate code name")

    # Validate the source span BEFORE creating anything so a bad item never
    # leaves a dangling code behind.
    fid = item.get("source_fid")
    pos0 = item.get("pos0")
    pos1 = item.get("pos1")
    coding_source: tuple[str, int, int] | None = None
    if fid is not None and pos0 is not None and pos1 is not None:
        src = (
            await db.execute(
                select(tables.source.c.fulltext).where(tables.source.c.id == fid)
            )
        ).first()
        if src is None:
            raise HTTPException(status_code=422, detail="source no longer exists")
        fulltext = src[0] or ""
        if not (0 <= pos0 < pos1 <= len(fulltext)):
            raise HTTPException(
                status_code=422, detail="item span is out of range of the source text"
            )
        coding_source = (fulltext[pos0:pos1], pos0, pos1)

    owner = resolve_owner(None)
    code = await CodeRepository(db).add_code(name=name, owner=owner, catid=req.catid)
    assert code is not None  # the pre-check above guarantees the name is new

    ctid: int | None = None
    if coding_source is not None:
        seltext, span0, span1 = coding_source
        assert fid is not None
        coding = await CodingRepository(db).add_text_coding(
            cid=code.cid,
            fid=fid,
            seltext=seltext,
            pos0=span0,
            pos1=span1,
            owner=owner,
            memo=item.get("note") or "",
        )
        ctid = coding.ctid

    code_row = (
        await db.execute(select(tables.code_name).where(tables.code_name.c.cid == code.cid))
    ).first()
    coding_row = None
    if ctid is not None:
        coding_row = (
            await db.execute(select(tables.code_text).where(tables.code_text.c.ctid == ctid))
        ).first()
    await audit.record(
        db,
        user=owner,
        action="creative.promote",
        entity="creative_item",
        entity_id=item_id,
        source_id=fid,
        detail={
            "cid": code.cid,
            "ctid": ctid,
            "code_name": code.name,
            "catid": req.catid,
            "code": dict(code_row._mapping) if code_row is not None else None,
            "coding": dict(coding_row._mapping) if coding_row is not None else None,
        },
    )
    return {"cid": code.cid, "ctid": ctid}
