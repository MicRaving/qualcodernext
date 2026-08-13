"""Document comparison chart API — MAXQDA-style document comparison.

``GET /compare?fid1=&fid2=`` aligns the two documents' code sequences
(left-to-right reads, one symbol per segment — see compare_service) and
returns the alignment rows plus similarity measures. Pure Python LCS; no
extra dependencies.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.core.models import Code
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodingRepository, SourceRepository
from qualcoder_api.services.compare_service import compare_documents

router = APIRouter(prefix="/compare", tags=["compare"])


@router.get("")
async def compare_files(fid1: int, fid2: int, db: DbDep) -> dict:
    """Align two documents' code sequences and score their similarity."""
    if fid1 == fid2:
        raise HTTPException(status_code=422, detail="the two documents must differ")

    source1 = await SourceRepository(db).get_source(fid1)
    source2 = await SourceRepository(db).get_source(fid2)
    if source1 is None:
        raise HTTPException(status_code=422, detail=f"source {fid1} not found")
    if source2 is None:
        raise HTTPException(status_code=422, detail=f"source {fid2} not found")

    repo = CodingRepository(db)
    codings1 = await repo.list_text_codings_for_file(fid1)
    codings2 = await repo.list_text_codings_for_file(fid2)
    if not codings1:
        raise HTTPException(
            status_code=422, detail=f"source \"{source1.name}\" has no text codings"
        )
    if not codings2:
        raise HTTPException(
            status_code=422, detail=f"source \"{source2.name}\" has no text codings"
        )

    used = {c.cid for c in codings1} | {c.cid for c in codings2}
    code_rows = await db.execute(
        select(
            tables.code_name.c.cid,
            tables.code_name.c.name,
            tables.code_name.c.color,
        ).where(tables.code_name.c.cid.in_(used))
    )
    codes: dict[int, Code] = {
        cid: Code(cid=cid, name=name or "", color=color or "#ffffff")
        for cid, name, color in code_rows
    }

    body = compare_documents(codings1, codings2, codes)
    body["fid1"] = fid1
    body["fid2"] = fid2
    body["file1"] = source1.name
    body["file2"] = source2.name
    return body
