"""Coder management — create / switch / delete coders (user identities)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from qualcoder_api.api.v1.deps import ServiceDep
from qualcoder_api.services.user_settings import (
    get_codername,
    get_coders,
    set_codername,
    set_coders,
)

router = APIRouter(prefix="/coders", tags=["coders"])

OWNER_TABLES = (
    ("code_text", "owner"),
    ("code_image", "owner"),
    ("code_av", "owner"),
    ("case_text", "owner"),
    ("annotation", "owner"),
    ("cases", "owner"),
    ("attribute_type", "owner"),
    ("journal", "owner"),
)


class CoderInfo(BaseModel):
    name: str
    coding_count: int = 0


class CodersResponse(BaseModel):
    current: str
    coders: list[CoderInfo] = Field(default_factory=list)


class CoderRequest(BaseModel):
    name: str


class CurrentCoderRequest(BaseModel):
    name: str


class DeleteCoderRequest(BaseModel):
    reassign_to: str | None = None


class VisibilityRequest(BaseModel):
    visible: bool


async def _coding_counts(svc) -> dict[str, int]:
    """Count records per owner in the open project (empty when none open)."""
    if svc.engine is None:
        return {}
    _, factory = svc._ensure_engine()
    result: dict[str, int] = {}
    async with factory() as session:
        for table, column in OWNER_TABLES:
            # Double quotes: "case" is a SQL keyword.
            rows = await session.execute(
                text(f'SELECT "{column}", count(*) FROM "{table}" GROUP BY "{column}"')
            )
            for owner, count in rows:
                if owner:
                    result[owner] = result.get(owner, 0) + int(count)
    return result


def _response(current: str, names: list[str], counts: dict[str, int]) -> CodersResponse:
    return CodersResponse(
        current=current,
        coders=[CoderInfo(name=n, coding_count=counts.get(n, 0)) for n in names],
    )


@router.get("", response_model=CodersResponse)
async def list_coders(svc: ServiceDep) -> CodersResponse:
    counts = await _coding_counts(svc)
    return _response(get_codername(), get_coders(), counts)


@router.post("", response_model=CodersResponse, status_code=201)
async def create_coder(req: CoderRequest) -> CodersResponse:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="coder name must not be empty")
    names = get_coders()
    if name in names:
        raise HTTPException(status_code=409, detail=f'coder "{name}" already exists')
    set_coders([*names, name])
    return _response(get_codername(), get_coders(), {})


@router.put("/current", response_model=CodersResponse)
async def switch_coder(req: CurrentCoderRequest) -> CodersResponse:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="coder name must not be empty")
    names = get_coders()
    if name not in names:
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    set_codername(name)
    return _response(name, names, {})


@router.delete("/{name}", response_model=CodersResponse)
async def delete_coder(
    name: str,
    svc: ServiceDep,
    req: DeleteCoderRequest | None = None,
) -> CodersResponse:
    names = get_coders()
    if name not in names:
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    if name == get_codername():
        raise HTTPException(status_code=409, detail="cannot delete the current coder — switch first")
    if len(names) <= 1:
        raise HTTPException(status_code=409, detail="cannot delete the last coder")

    counts = await _coding_counts(svc)
    count = counts.get(name, 0)
    reassign_to = (req.reassign_to if req else None) or None
    if count > 0 and not reassign_to:
        raise HTTPException(
            status_code=409,
            detail=f'coder "{name}" owns {count} records — pass reassign_to to move them',
        )

    if reassign_to:
        if reassign_to not in names:
            raise HTTPException(status_code=404, detail=f'target coder "{reassign_to}" does not exist')
        _, factory = svc._ensure_engine()
        async with factory() as session:
            for table, column in OWNER_TABLES:
                await session.execute(
                    text(f'UPDATE "{table}" SET "{column}" = :to WHERE "{column}" = :from'),
                    {"to": reassign_to, "from": name},
                )
            await session.commit()

    # Remove the coder from the coder_names table too (visibility registry).
    if svc.engine is not None:
        _, factory = svc._ensure_engine()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM coder_names WHERE name = :n"), {"n": name}
            )
            await session.commit()

    set_coders([n for n in names if n != name])
    return _response(get_codername(), get_coders(), counts)


@router.get("/visibility")
async def coder_visibility(svc: ServiceDep) -> dict:
    """Visibility flags (0 = hidden, 1 = visible) per coder in the project."""
    if svc.engine is None:
        return {"visibility": {}}
    _, factory = svc._ensure_engine()
    async with factory() as session:
        rows = await session.execute(
            text("SELECT name, visibility FROM coder_names ORDER BY name")
        )
    return {"visibility": {r[0]: r[1] for r in rows}}


@router.put("/{name}/visibility")
async def set_coder_visibility(name: str, req: VisibilityRequest, svc: ServiceDep) -> dict:
    """Hide/show a coder's codings and annotations across the project.

    The ``*_visible`` SQL views exclude hidden coders from coding lists and
    every report; a hidden coder's own rows are untouched.
    """
    if svc.engine is None:
        raise HTTPException(status_code=409, detail="no project is open")
    names = get_coders()
    if name not in names:
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    _, factory = svc._ensure_engine()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO coder_names (name, visibility) VALUES (:n, :v) "
                "ON CONFLICT(name) DO UPDATE SET visibility = :v"
            ),
            {"n": name, "v": 1 if req.visible else 0},
        )
        await session.commit()
    return {"ok": True, "name": name, "visible": req.visible}
