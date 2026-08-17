"""Threaded comments API — comments on any project entity.

A comment row pins a free-text note to a whitelisted target entity
(``target_kind``/``target_id``): source, code, case, coding, annotation,
creative item or QTT item. The thread endpoint returns the comments for one
target oldest-first with the author and timestamp; mutations are
audit-recorded and journaled to ``sync_log`` exactly like the creative
scratchpad, so the folder-sync replays them between machines.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import CursorResult, Result

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables
from qualcoder_api.services import audit, sync
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/comments", tags=["comments"])

# Entity kinds a comment may be attached to, with the table + pk column used
# to check the target row exists. ``coding`` spans three tables (text, image,
# AV) — the target id must exist in any of them.
TARGET_KINDS = (
    "source",
    "code",
    "case",
    "coding",
    "annotation",
    "creative_item",
    "qtt_item",
)

_TARGET_TABLES: dict[str, tuple[Any, str]] = {
    "source": (tables.source, "id"),
    "code": (tables.code_name, "cid"),
    "case": (tables.cases, "caseid"),
    "annotation": (tables.annotation, "anid"),
    "creative_item": (tables.creative_item, "id"),
    "qtt_item": (tables.qtt_item, "id"),
}

_CODING_TABLES = (
    (tables.code_text, "ctid"),
    (tables.code_image, "imid"),
    (tables.code_av, "avid"),
)


def _inserted_pk(result: Result) -> int:
    """First inserted primary key from an INSERT statement result."""
    pk = cast(CursorResult[Any], result).inserted_primary_key
    if pk is None:  # pragma: no cover - inserts always return a pk here
        raise RuntimeError("insert returned no primary key")
    return int(pk[0])


class CommentCreate(BaseModel):
    target_kind: str
    target_id: int
    body: str
    owner: str | None = None


class CommentUpdate(BaseModel):
    body: str


async def _validate_kind(target_kind: str) -> None:
    if target_kind not in TARGET_KINDS:
        raise HTTPException(
            status_code=422, detail=f"unknown target_kind {target_kind!r}"
        )


async def _target_exists(db, target_kind: str, target_id: int) -> bool:
    """True when a row for the whitelisted target kind+id exists."""
    if target_kind == "coding":
        for table, pk in _CODING_TABLES:
            row = (
                await db.execute(
                    select(table).where(table.c[pk] == target_id).limit(1)
                )
            ).first()
            if row is not None:
                return True
        return False
    table, pk = _TARGET_TABLES[target_kind]
    row = (
        await db.execute(select(table).where(table.c[pk] == target_id).limit(1))
    ).first()
    return row is not None


@router.get("", response_model=list[dict])
async def list_comments(target_kind: str, target_id: int, db: DbDep) -> list[dict]:
    """The thread for one target, oldest first (coder + created attached)."""
    await _validate_kind(target_kind)
    rows = await db.execute(
        select(tables.comment)
        .where(
            tables.comment.c.target_kind == target_kind,
            tables.comment.c.target_id == target_id,
        )
        .order_by(tables.comment.c.id.asc())
    )
    return [dict(r._mapping) for r in rows]


@router.post("", response_model=dict, status_code=201)
async def create_comment(req: CommentCreate, db: DbDep) -> dict:
    body = (req.body or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="body must not be empty")
    await _validate_kind(req.target_kind)
    if not await _target_exists(db, req.target_kind, req.target_id):
        raise HTTPException(
            status_code=404,
            detail=f"{req.target_kind} {req.target_id} not found",
        )
    coder = resolve_owner(req.owner)
    result = await db.execute(
        insert(tables.comment).values(
            target_kind=req.target_kind,
            target_id=req.target_id,
            body=body,
            owner=coder,
            created=_now(),
        )
    )
    await db.commit()
    comment_id = _inserted_pk(result)
    row = (
        await db.execute(
            select(tables.comment).where(tables.comment.c.id == comment_id)
        )
    ).first()
    assert row is not None
    data = dict(row._mapping)
    await sync.capture_insert(
        db, entity="comment", pk_name="id", pk_value=comment_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=coder,
        action="comment.create",
        entity="comment",
        entity_id=comment_id,
        detail={
            "target_kind": req.target_kind,
            "target_id": req.target_id,
            "body": body[:200],
            "row": data,
        },
    )
    return data


@router.patch("/{comment_id}", response_model=dict)
async def update_comment(comment_id: int, req: CommentUpdate, db: DbDep) -> dict:
    row = (
        await db.execute(
            select(tables.comment).where(tables.comment.c.id == comment_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="comment not found")
    old_body = row._mapping.get("body") if row is not None else None
    body = (req.body or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="body must not be empty")
    await db.execute(
        sa_update(tables.comment)
        .where(tables.comment.c.id == comment_id)
        .values(body=body)
    )
    await db.commit()
    row = (
        await db.execute(
            select(tables.comment).where(tables.comment.c.id == comment_id)
        )
    ).first()
    assert row is not None
    data = dict(row._mapping)
    await sync.capture_update(
        db, entity="comment", pk_name="id", pk_value=comment_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=get_codername(),
        action="comment.update",
        entity="comment",
        entity_id=comment_id,
        detail={
            "target_kind": data["target_kind"],
            "target_id": data["target_id"],
            "body": body[:200],
            "old_body": old_body,
            "new_body": body,
        },
    )
    return data


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(comment_id: int, db: DbDep) -> None:
    row = (
        await db.execute(
            select(tables.comment).where(tables.comment.c.id == comment_id)
        )
    ).first()
    await db.execute(
        delete(tables.comment).where(tables.comment.c.id == comment_id)
    )
    if row is None:
        await db.commit()
        raise HTTPException(status_code=404, detail="comment not found")
    data = dict(row._mapping)
    await sync.capture_delete(
        db, entity="comment", pk_name="id", pk_value=comment_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=get_codername(),
        action="comment.delete",
        entity="comment",
        entity_id=comment_id,
        detail={
            "target_kind": data["target_kind"],
            "target_id": data["target_id"],
            "body": (data.get("body") or "")[:200],
            "row": data,
        },
    )
