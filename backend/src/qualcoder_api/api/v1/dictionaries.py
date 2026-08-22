"""Word dictionaries API — MAXDictio-style CRUD, import and the
per-document x per-term frequency report.

Dictionary autocoding itself lives in ``codings.py``
(``POST /codings/dictionary-autocode``) next to the regular autocode
endpoints; both share the same autocode engine.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep
from qualcoder_api.persistence import tables
from qualcoder_api.services import audit, dictionary_service
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/dictionaries", tags=["dictionaries"])


class DictionaryCreate(BaseModel):
    name: str
    owner: str | None = None


class DictionaryRename(BaseModel):
    name: str


class DictionaryEntryCreate(BaseModel):
    code_name: str
    term: str


@router.get("")
async def list_dictionaries(db: DbDep) -> list[dict]:
    return await dictionary_service.list_dictionaries(db)


@router.post("", status_code=201)
async def create_dictionary(req: DictionaryCreate, db: DbDep) -> dict:
    owner = resolve_owner(req.owner)
    try:
        dictionary = await dictionary_service.create_dictionary(db, req.name, owner)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from None
    if dictionary is None:
        raise HTTPException(status_code=409, detail="duplicate dictionary name")
    await audit.record(
        db, user=owner, action="dictionary.create", entity="dictionary",
        entity_id=dictionary["id"],
        detail={
            "name": dictionary["name"],
            "row": {
                "id": dictionary["id"],
                "name": dictionary["name"],
                "owner": dictionary.get("owner"),
                "created": dictionary.get("created"),
            },
        },
    )
    return dictionary


@router.patch("/{dict_id}")
async def rename_dictionary(dict_id: int, req: DictionaryRename, db: DbDep) -> dict:
    from sqlalchemy import select

    old_row = (
        await db.execute(select(tables.dictionary).where(tables.dictionary.c.id == dict_id))
    ).first()
    try:
        dictionary = await dictionary_service.rename_dictionary(db, dict_id, req.name)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from None
    if dictionary is None:
        raise HTTPException(status_code=404, detail="dictionary not found")
    await audit.record(
        db, user=get_codername(), action="dictionary.update", entity="dictionary",
        entity_id=dict_id,
        detail={
            "new_name": dictionary["name"],
            "old_name": old_row[1] if old_row is not None else None,
        },
    )
    return dictionary


@router.delete("/{dict_id}", status_code=204)
async def delete_dictionary(dict_id: int, db: DbDep) -> None:
    from sqlalchemy import select

    row = (
        await db.execute(select(tables.dictionary).where(tables.dictionary.c.id == dict_id))
    ).first()
    entries = [
        dict(r._mapping)
        for r in (
            await db.execute(
                select(tables.dictionary_entry).where(tables.dictionary_entry.c.dict_id == dict_id)
            )
        ).all()
    ]
    if not await dictionary_service.delete_dictionary(db, dict_id):
        raise HTTPException(status_code=404, detail="dictionary not found")
    await audit.record(
        db, user=get_codername(), action="dictionary.delete", entity="dictionary",
        entity_id=dict_id,
        detail={"row": dict(row._mapping) if row is not None else None, "entries": entries},
    )


@router.post("/{dict_id}/entries", status_code=201)
async def add_entry(dict_id: int, req: DictionaryEntryCreate, db: DbDep) -> dict:
    try:
        entry = await dictionary_service.add_entry(
            db, dict_id, req.code_name, req.term
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from None
    if isinstance(entry, str):
        raise HTTPException(status_code=409, detail="term already in dictionary")
    if entry is None:
        raise HTTPException(status_code=404, detail="dictionary not found")
    await audit.record(
        db, user=get_codername(), action="dictionary.entry_add", entity="dictionary_entry",
        entity_id=entry["id"], source_id=dict_id, detail=entry,
    )
    return entry


@router.delete("/entries/{entry_id}", status_code=204)
async def remove_entry(entry_id: int, db: DbDep) -> None:
    from sqlalchemy import select

    row = (
        await db.execute(
            select(tables.dictionary_entry).where(tables.dictionary_entry.c.id == entry_id)
        )
    ).first()
    if not await dictionary_service.remove_entry(db, entry_id):
        raise HTTPException(status_code=404, detail="entry not found")
    await audit.record(
        db, user=get_codername(), action="dictionary.entry_delete",
        entity="dictionary_entry", entity_id=entry_id,
        detail={"row": dict(row._mapping) if row is not None else None},
    )


@router.post("/import", status_code=201)
async def import_dictionary(
    svc: OpenProjectDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    name: str | None = Form(None),
    codername: str | None = Form(None),
) -> dict:
    """Import a dictionary from a text/CSV upload (``code,term1,term2,...``
    per line; ``#`` comments and blank lines are ignored)."""
    tmp = svc.project_path + "/_dict_import_" + (file.filename or "dictionary.txt")
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    owner = resolve_owner(codername)
    try:
        content = await asyncio.to_thread(
            lambda: Path(tmp).read_text(encoding="utf-8-sig", errors="replace")
        )
        dict_name = (name or "").strip() or (file.filename or "dictionary").rsplit(".", 1)[0]
        result = await dictionary_service.import_dictionary(
            db, dict_name, content, owner
        )
    finally:
        os.remove(tmp)
    await audit.record(
        db, user=owner, action="dictionary.import", entity="dictionary",
        entity_id=result["dictionary"]["id"],
        detail={"added": result["added"], "skipped": result["skipped"]},
    )
    return result


@router.get("/{dict_id}/frequencies")
async def dictionary_frequencies(
    dict_id: int, db: DbDep, normalize: bool = False, stopwords: bool = True
) -> dict:
    """Per-document x per-term occurrence matrix (optionally relative %)."""
    result = await dictionary_service.dictionary_frequencies(
        db, dict_id, normalize=normalize, use_stopwords=stopwords
    )
    if result is None:
        raise HTTPException(status_code=404, detail="dictionary not found")
    return result
