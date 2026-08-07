"""Audit log API — project history browsing (edit review view)."""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from qualcoder_api.api.v1.deps import DbDep

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditRow(BaseModel):
    id: int
    ts: str
    user: str
    action: str
    entity: str
    entity_id: int | None = None
    source_id: int | None = None
    detail: dict = Field(default_factory=dict)


class AuditResponse(BaseModel):
    rows: list[AuditRow] = Field(default_factory=list)
    total: int = 0


class AuditStatsRow(BaseModel):
    action: str
    count: int


@router.get("", response_model=AuditResponse)
async def list_audit(
    db: DbDep,
    limit: int = 100,
    offset: int = 0,
    action: str | None = None,
    user: str | None = None,
    source_id: int | None = None,
) -> AuditResponse:
    """Chronological audit rows, newest first, with optional filters."""
    where = []
    params: dict = {}
    if action:
        where.append("action = :action")
        params["action"] = action
    if user:
        where.append("user = :user")
        params["user"] = user
    if source_id is not None:
        where.append("source_id = :source_id")
        params["source_id"] = source_id
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = (
        await db.execute(text(f"SELECT count(*) FROM audit_log {clause}"), params)
    ).scalar_one()
    rows = await db.execute(
        text(
            f"SELECT id, ts, user, action, entity, entity_id, source_id, detail "
            f"FROM audit_log {clause} ORDER BY id DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": min(max(limit, 1), 500), "offset": max(offset, 0)},
    )
    items = []
    for row in rows:
        detail: dict = {}
        try:
            detail = json.loads(row[7]) if row[7] else {}
        except (json.JSONDecodeError, TypeError):
            detail = {}
        items.append(
            AuditRow(
                id=row[0],
                ts=row[1],
                user=row[2] or "",
                action=row[3] or "",
                entity=row[4] or "",
                entity_id=row[5],
                source_id=row[6],
                detail=detail if isinstance(detail, dict) else {},
            )
        )
    return AuditResponse(rows=items, total=int(total))


@router.get("/stats", response_model=list[AuditStatsRow])
async def audit_stats(db: DbDep) -> list[AuditStatsRow]:
    rows = await db.execute(
        select(text("action"), func.count()).select_from(text("audit_log")).group_by(text("action"))
    )
    return [AuditStatsRow(action=r[0] or "", count=int(r[1])) for r in rows]


class AuditActionRequest(BaseModel):
    id: int


@router.post("/undo", response_model=dict)
async def audit_undo(req: AuditActionRequest, db: DbDep) -> dict:
    """Revert one audit-logged change."""
    from fastapi import HTTPException

    from qualcoder_api.services.audit_undo import UnsupportedAction, apply

    row = (
        await db.execute(select(text("*")).select_from(text("audit_log")).where(text("id = :id")), {"id": req.id})
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="audit row not found")
    try:
        message = await apply(db, dict(row), undo=True)
    except UnsupportedAction as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await db.commit()
    return {"ok": True, "message": message}


@router.post("/redo", response_model=dict)
async def audit_redo(req: AuditActionRequest, db: DbDep) -> dict:
    """Re-apply a previously undone audit-logged change."""
    from fastapi import HTTPException

    from qualcoder_api.services.audit_undo import UnsupportedAction, apply

    row = (
        await db.execute(select(text("*")).select_from(text("audit_log")).where(text("id = :id")), {"id": req.id})
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="audit row not found")
    try:
        message = await apply(db, dict(row), undo=False)
    except UnsupportedAction as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await db.commit()
    return {"ok": True, "message": message}
