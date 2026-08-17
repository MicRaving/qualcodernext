"""Audit log API — project history browsing (edit review view).

Listing supports server-side filtering/search and a ``summary`` projection
that omits the (potentially huge) ``detail`` JSON for the list view. Undo /
redo record ``audit.undo`` / ``audit.redo`` marker rows so redo survives a
pane reload, and the ``/undoable`` endpoint lets the UI grey out undo before
a round trip.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from qualcoder_api.api.v1.deps import DbDep, ServiceDep

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
    #: Lightweight one-line summary, populated only in ``summary`` mode (the
    #: list view); empty otherwise.
    summary: str = ""
    #: Whether the backend could invert this row (undo direction). Computed in
    #: ``summary`` mode so the list needs no per-row predicate round trips.
    undoable: bool = True
    #: Reason when ``undoable`` is false.
    undo_reason: str | None = None


class AuditResponse(BaseModel):
    rows: list[AuditRow] = Field(default_factory=list)
    total: int = 0


class AuditStatsRow(BaseModel):
    action: str
    count: int


def _decode_detail(raw) -> dict:
    detail: dict = {}
    try:
        detail = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        detail = {}
    return detail if isinstance(detail, dict) else {}


def _summarize(action: str, detail: dict) -> str:
    """Cheap numeric summary for the list view (no localization needed)."""
    if action == "coding.create" and detail.get("cid") is not None:
        return f"cid {detail['cid']} · {detail.get('pos0', '')}-{detail.get('pos1', '')}"
    if action == "source.edit":
        return f"{detail.get('before_length', '?')} -> {detail.get('new_length', '?')} chars"
    if action == "coding.autocode" and detail.get("count") is not None:
        return f"{detail['count']} segments"
    return ""


def _build_row(row, *, summary: bool = False) -> AuditRow:
    detail = _decode_detail(row[7]) if len(row) > 7 else {}
    undoable, undo_reason = True, None
    if summary:
        from qualcoder_api.services.audit_undo import can_undoable

        undoable, undo_reason = can_undoable(row[3] or "", detail, undo=True)
    return AuditRow(
        id=row[0],
        ts=row[1],
        user=row[2] or "",
        action=row[3] or "",
        entity=row[4] or "",
        entity_id=row[5],
        source_id=row[6],
        detail={} if summary else detail,
        summary=_summarize(row[3] or "", detail) if summary else "",
        undoable=undoable,
        undo_reason=undo_reason,
    )


@router.get("", response_model=AuditResponse)
async def list_audit(
    db: DbDep,
    limit: int = 100,
    offset: int = 0,
    action: str | None = None,
    user: str | None = None,
    entity: str | None = None,
    source_id: int | None = None,
    q: str | None = None,
    summary: bool = False,
) -> AuditResponse:
    """Chronological audit rows, newest first, with optional filters.

    ``summary=true`` drops the ``detail`` column from the SELECT (it can be
    megabytes for ``source.edit`` rows); fetch the full row via ``GET /audit/
    {id}`` when needed. ``q`` does a server-side substring search over the
    entity/action/user/detail columns (so search spans every page, not just
    the loaded one).
    """
    where = []
    params: dict = {}
    if action:
        where.append("action = :action")
        params["action"] = action
    if user:
        where.append("user = :user")
        params["user"] = user
    if entity:
        where.append("entity = :entity")
        params["entity"] = entity
    if source_id is not None:
        where.append("source_id = :source_id")
        params["source_id"] = source_id
    if q:
        needle = q.strip()[:200]
        if needle:
            where.append(
                "(entity LIKE :q OR action LIKE :q OR user LIKE :q OR detail LIKE :q)"
            )
            params["q"] = f"%{needle}%"
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = (
        await db.execute(text(f"SELECT count(*) FROM audit_log {clause}"), params)
    ).scalar_one()

    cols = "id, ts, user, action, entity, entity_id, source_id, detail"
    rows = await db.execute(
        text(
            f"SELECT {cols} FROM audit_log {clause} "
            f"ORDER BY id DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": min(max(limit, 1), 500), "offset": max(offset, 0)},
    )
    items = [_build_row(row, summary=summary) for row in rows]
    return AuditResponse(rows=items, total=int(total))


@router.get("/stats", response_model=list[AuditStatsRow])
async def audit_stats(db: DbDep) -> list[AuditStatsRow]:
    rows = await db.execute(
        select(text("action"), func.count()).select_from(text("audit_log")).group_by(text("action"))
    )
    return [AuditStatsRow(action=r[0] or "", count=int(r[1])) for r in rows]


@router.get("/users", response_model=list[str])
async def audit_users(db: DbDep) -> list[str]:
    """Distinct coders in the audit log (project-wide, for the user filter)."""
    rows = await db.execute(
        text("SELECT DISTINCT user FROM audit_log WHERE user IS NOT NULL AND user != '' "
             "ORDER BY user")
    )
    return [r[0] for r in rows]


@router.get("/redo-pending", response_model=dict)
async def audit_redo_pending(db: DbDep) -> dict:
    """Most recent undone row that has not been re-applied, plus a count.

    The ``audit.undo`` / ``audit.redo`` marker rows (recorded by the undo /
    redo endpoints) let the UI reconstruct the redo stack across pane reloads
    instead of keeping it in component state.
    """
    rows = (
        await db.execute(
            text(
                "SELECT e.entity_id, e.id "
                "FROM audit_log e "
                "WHERE e.action = 'audit.undo' AND NOT EXISTS ("
                "  SELECT 1 FROM audit_log r "
                "  WHERE r.action = 'audit.redo' AND r.entity_id = e.entity_id AND r.id > e.id"
                ") "
                "ORDER BY e.id DESC"
            )
        )
    ).all()
    return {"count": len(rows), "next_id": int(rows[0][0]) if rows else None}


@router.get("/{audit_id}", response_model=AuditRow)
async def get_audit(audit_id: int, db: DbDep) -> AuditRow:
    """One audit row with its full detail (for the detail modal)."""
    row = (
        await db.execute(
            text("SELECT id, ts, user, action, entity, entity_id, source_id, detail "
                 "FROM audit_log WHERE id = :id"),
            {"id": audit_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="audit row not found")
    return _build_row(row)


@router.get("/{audit_id}/undoable", response_model=dict)
async def audit_undoable(audit_id: int, db: DbDep, undo: bool = True) -> dict:
    """Predicate: could the backend invert this row in the given direction?

    Returns ``{"undoable": bool, "reason": str | null}`` without mutating any
    state, so the UI can grey out the undo/redo buttons before a round trip.
    """
    from qualcoder_api.services.audit_undo import can_undoable

    row = (
        await db.execute(
            text("SELECT id, action, detail FROM audit_log WHERE id = :id"),
            {"id": audit_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="audit row not found")
    detail = _decode_detail(row[2])
    ok, reason = can_undoable(row[1] or "", detail, undo=undo)
    return {"undoable": ok, "reason": reason}


class AuditActionRequest(BaseModel):
    id: int


async def _fetch_row(db: DbDep, audit_id: int) -> dict:
    row = (
        await db.execute(
            select(text("*")).select_from(text("audit_log")).where(text("id = :id")), {"id": audit_id}
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="audit row not found")
    return dict(row)


async def _record_marker(db: DbDep, action: str, audit_id: int, message: str) -> None:
    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername

    await audit.record(
        db, user=get_codername(), action=action, entity="audit_log",
        entity_id=audit_id, detail={"message": message},
    )


@router.post("/undo", response_model=dict)
async def audit_undo(req: AuditActionRequest, db: DbDep, svc: ServiceDep) -> dict:
    """Revert one audit-logged change."""
    from qualcoder_api.services.audit_undo import UnsupportedAction, apply

    row = await _fetch_row(db, req.id)
    try:
        message = await apply(db, row, undo=True, project_path=svc.project_path)
    except UnsupportedAction as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await _record_marker(db, "audit.undo", req.id, message)
    await db.commit()
    return {"ok": True, "message": message}


@router.post("/redo", response_model=dict)
async def audit_redo(req: AuditActionRequest, db: DbDep, svc: ServiceDep) -> dict:
    """Re-apply a previously undone audit-logged change."""
    from qualcoder_api.services.audit_undo import UnsupportedAction, apply

    row = await _fetch_row(db, req.id)
    try:
        message = await apply(db, row, undo=False, project_path=svc.project_path)
    except UnsupportedAction as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await _record_marker(db, "audit.redo", req.id, message)
    await db.commit()
    return {"ok": True, "message": message}
