"""Segment links API — directed links between source spans.

Mirrors the annotation endpoints: mutations are audited, positions are
validated against the source text lengths, and list responses resolve both
sources' names plus short excerpts for previews.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.services import audit
from qualcoder_api.services.links_service import LinkError, LinkService
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/links", tags=["links"])


class LinkCreate(BaseModel):
    from_fid: int
    from_pos0: int
    from_pos1: int
    to_fid: int
    to_pos0: int
    to_pos1: int
    memo: str = ""
    owner: str | None = None


@router.get("", response_model=list[dict])
async def list_links(db: DbDep, fid: int | None = None) -> list[dict]:
    """Links anchored on ``fid`` (outgoing). Without ``fid``: every link."""
    service = LinkService(db)
    if fid is None:
        return await service.list_all()
    return await service.list_outgoing(fid)


@router.get("/source/{fid}", response_model=list[dict])
async def list_incoming_links(fid: int, db: DbDep) -> list[dict]:
    """Links pointing AT ``fid`` (incoming; for the Inspector's target side)."""
    return await LinkService(db).list_incoming(fid)


@router.post("", response_model=dict, status_code=201)
async def create_link(req: LinkCreate, db: DbDep) -> dict:
    try:
        link = await LinkService(db).create(
            from_fid=req.from_fid,
            from_pos0=req.from_pos0,
            from_pos1=req.from_pos1,
            to_fid=req.to_fid,
            to_pos0=req.to_pos0,
            to_pos1=req.to_pos1,
            memo=req.memo,
            owner=resolve_owner(req.owner),
        )
    except LinkError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await audit.record(
        db,
        user=resolve_owner(req.owner),
        action="link.create",
        entity="link",
        entity_id=link["id"],
        source_id=req.from_fid,
        detail={
            "from_fid": req.from_fid,
            "from_pos0": req.from_pos0,
            "from_pos1": req.from_pos1,
            "to_fid": req.to_fid,
            "to_pos0": req.to_pos0,
            "to_pos1": req.to_pos1,
        },
    )
    return link


@router.delete("/{link_id}", status_code=204)
async def delete_link(link_id: int, db: DbDep) -> None:
    row = await LinkService(db).delete(link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="link not found")
    await audit.record(
        db,
        user=get_codername(),
        action="link.delete",
        entity="link",
        entity_id=link_id,
        source_id=row.get("from_fid"),
        detail=row,
    )
