"""Code sets API — MAXQDA-style named subsets of codes.

A code set is a named list of code ids (``code_set`` + ``code_set_member``
rows) that can be applied as a client-side filter on the codebook tree.
Mutations are audit-recorded like every other domain (see ``creative.py``
for the pattern).
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import CursorResult

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _inserted_pk
from qualcoder_api.services import audit
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/code-sets", tags=["code-sets"])


class CodeSetCreate(BaseModel):
    name: str
    owner: str | None = None


class CodeSetRename(BaseModel):
    name: str


class CodeSetMembers(BaseModel):
    cids: list[int]


async def _get_set(db: DbDep, set_id: int) -> dict:
    """The ``code_set`` row as a dict; 404 when it does not exist."""
    row = (
        await db.execute(select(tables.code_set).where(tables.code_set.c.id == set_id))
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="code set not found")
    return dict(row._mapping)


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="code set name must not be empty")
    return name


async def _assert_name_free(db: DbDep, name: str, exclude_id: int | None = None) -> None:
    """409 when another set already uses ``name`` (case-insensitive, like
    the code-name pre-check in the creative promote path)."""
    rows = await db.execute(select(tables.code_set.c.id, tables.code_set.c.name))
    for set_id, existing in rows:
        if exclude_id is not None and set_id == exclude_id:
            continue
        if existing and str(existing).strip().lower() == name.lower():
            raise HTTPException(status_code=409, detail="duplicate code set name")


async def _existing_cids(db: DbDep, cids: list[int]) -> list[int]:
    """The subset of ``cids`` that actually exist in ``code_name``."""
    unique = list(dict.fromkeys(cids))
    if not unique:
        return []
    rows = await db.execute(
        select(tables.code_name.c.cid).where(tables.code_name.c.cid.in_(unique))
    )
    return [int(r[0]) for r in rows]


@router.get("", response_model=list[dict])
async def list_code_sets(db: DbDep) -> list[dict]:
    """All code sets with their member counts, oldest first."""
    rows = await db.execute(
        select(
            tables.code_set.c.id,
            tables.code_set.c.name,
            tables.code_set.c.owner,
            tables.code_set.c.created,
            func.count(tables.code_set_member.c.cid).label("member_count"),
        )
        .outerjoin(
            tables.code_set_member,
            tables.code_set_member.c.set_id == tables.code_set.c.id,
        )
        .group_by(tables.code_set.c.id)
        .order_by(tables.code_set.c.id)
    )
    return [dict(r._mapping) for r in rows]


@router.post("", response_model=dict, status_code=201)
async def create_code_set(req: CodeSetCreate, db: DbDep) -> dict:
    """Create a named code set; duplicate names are rejected with 409."""
    name = _clean_name(req.name)
    await _assert_name_free(db, name)
    owner = resolve_owner(req.owner)
    try:
        result = await db.execute(
            insert(tables.code_set).values(name=name, owner=owner, created=_now())
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="duplicate code set name") from None
    set_id = _inserted_pk(result)
    row = (await db.execute(select(tables.code_set).where(tables.code_set.c.id == set_id))).first()
    assert row is not None
    await audit.record(
        db, user=owner, action="code_set.create", entity="code_set",
        entity_id=set_id, detail={"name": name, "row": dict(row._mapping)},
    )
    return {**dict(row._mapping), "member_count": 0}


@router.patch("/{set_id}", response_model=dict)
async def rename_code_set(set_id: int, req: CodeSetRename, db: DbDep) -> dict:
    """Rename a code set; collisions with another set's name yield 409."""
    name = _clean_name(req.name)
    old = await _get_set(db, set_id)
    await _assert_name_free(db, name, exclude_id=set_id)
    try:
        await db.execute(
            sa_update(tables.code_set).where(tables.code_set.c.id == set_id).values(name=name)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="duplicate code set name") from None
    await audit.record(
        db, user=get_codername(), action="code_set.rename", entity="code_set",
        entity_id=set_id, detail={"old_name": old.get("name"), "new_name": name},
    )
    row = (await db.execute(select(tables.code_set).where(tables.code_set.c.id == set_id))).first()
    assert row is not None
    return dict(row._mapping)


@router.delete("/{set_id}", status_code=204)
async def delete_code_set(set_id: int, db: DbDep) -> None:
    """Delete a code set and cascade-remove its members."""
    row = (
        await db.execute(select(tables.code_set).where(tables.code_set.c.id == set_id))
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="code set not found")
    data = dict(row._mapping)
    members = [
        dict(r._mapping)
        for r in (
            await db.execute(
                select(tables.code_set_member).where(tables.code_set_member.c.set_id == set_id)
            )
        ).all()
    ]
    await db.execute(
        delete(tables.code_set_member).where(tables.code_set_member.c.set_id == set_id)
    )
    await db.execute(delete(tables.code_set).where(tables.code_set.c.id == set_id))
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="code_set.delete", entity="code_set",
        entity_id=set_id, detail={**data, "row": data, "members": members},
    )


@router.get("/{set_id}", response_model=dict)
async def get_code_set(set_id: int, db: DbDep) -> dict:
    """One code set with its member list (cid + code name)."""
    _ = await _get_set(db, set_id)
    rows = await db.execute(
        select(tables.code_set_member.c.cid, tables.code_name.c.name)
        .join(tables.code_name, tables.code_name.c.cid == tables.code_set_member.c.cid)
        .where(tables.code_set_member.c.set_id == set_id)
        .order_by(tables.code_set_member.c.cid)
    )
    members = [
        {"cid": int(r[0]), "name": r[1] or ""}
        for r in rows
    ]
    return {"set_id": set_id, "members": members}


@router.post("/{set_id}/members", response_model=dict)
async def add_code_set_members(set_id: int, req: CodeSetMembers, db: DbDep) -> dict:
    """Add members to a set. Unknown cids are ignored; duplicates are
    deduped. Returns how many members were actually added."""
    _ = await _get_set(db, set_id)
    cids = await _existing_cids(db, req.cids)
    have = {
        int(r[0])
        for r in (
            await db.execute(
                select(tables.code_set_member.c.cid).where(
                    tables.code_set_member.c.set_id == set_id,
                    tables.code_set_member.c.cid.in_(cids),
                )
            )
        )
    }
    to_add = [c for c in cids if c not in have]
    if to_add:
        await db.execute(
            insert(tables.code_set_member),
            [{"set_id": set_id, "cid": cid} for cid in to_add],
        )
        await db.commit()
    await audit.record(
        db, user=get_codername(), action="code_set.members_add", entity="code_set",
        entity_id=set_id, detail={"cids": cids, "added": len(to_add), "added_cids": to_add},
    )
    return {"set_id": set_id, "added": len(to_add), "cids": to_add}


@router.delete("/{set_id}/members", response_model=dict)
async def remove_code_set_members(set_id: int, req: CodeSetMembers, db: DbDep) -> dict:
    """Remove members from a set. Unknown cids are ignored. Returns how
    many members were actually removed."""
    _ = await _get_set(db, set_id)
    cids = list(dict.fromkeys(req.cids))
    removed_cids: list[int] = []
    removed = 0
    if cids:
        existing = {
            int(r[0])
            for r in (
                await db.execute(
                    select(tables.code_set_member.c.cid).where(
                        tables.code_set_member.c.set_id == set_id,
                        tables.code_set_member.c.cid.in_(cids),
                    )
                )
            ).all()
        }
        removed_cids = [c for c in cids if c in existing]
        result = await db.execute(
            delete(tables.code_set_member).where(
                tables.code_set_member.c.set_id == set_id,
                tables.code_set_member.c.cid.in_(cids),
            )
        )
        removed = cast(CursorResult[Any], result).rowcount or 0
        await db.commit()
    await audit.record(
        db, user=get_codername(), action="code_set.members_remove", entity="code_set",
        entity_id=set_id,
        detail={"cids": cids, "removed": removed, "removed_cids": removed_cids},
    )
    return {"set_id": set_id, "removed": removed, "cids": cids}
