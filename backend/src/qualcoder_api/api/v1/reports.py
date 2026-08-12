"""Reports API — aggregation endpoints over the open project.

All endpoints depend on ``DbDep``, which already returns 409 when no
project is open. Responses are plain dicts; no response models needed.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/code-frequencies")
async def code_frequencies(db: DbDep) -> dict:
    return {"rows": await report_service.code_frequencies(db)}


@router.get("/codes-by-segments")
async def codes_by_segments(db: DbDep) -> dict:
    return {"rows": await report_service.codes_by_segments(db)}


@router.get("/comparison-table")
async def comparison_table(db: DbDep) -> dict:
    return await report_service.comparison_table(db)


@router.get("/co-occurrence")
async def cooccurrence(db: DbDep) -> dict:
    return await report_service.cooccurrence(db)


@router.get("/exact-matches")
async def exact_matches(db: DbDep) -> dict:
    return {"rows": await report_service.exact_matches(db)}


@router.get("/file-summary")
async def file_summary(db: DbDep) -> dict:
    return {"rows": await report_service.file_summary(db)}


@router.get("/coder-comparison")
async def coder_comparison(db: DbDep) -> dict:
    return {"rows": await report_service.coder_comparison(db)}


@router.get("/attributes")
async def attributes_report(db: DbDep) -> dict:
    return {"rows": await report_service.attributes_report(db)}


class InterraterRequest(BaseModel):
    coder_a: str
    coder_b: str
    coders: list[str] | None = None


@router.post("/interrater")
async def interrater(db: DbDep, req: InterraterRequest) -> dict:
    """Interrater reliability between coders on the same documents.

    Units are the project's sources; categories are the codes. Each
    unit x category cell is rated present/absent by every selected coder.
    ``coders`` (optional) restricts the comparison — default: all coders
    with codings. Returns Krippendorff's Alpha over all selected coders
    plus pairwise Cohen's Kappa and Gwet's AC1 (mean/min/max across pairs).
    """
    from fastapi import HTTPException

    try:
        return await report_service.interrater(db, req.coder_a, req.coder_b, req.coders)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


class CoderFileComparisonRequest(BaseModel):
    coder_a: str
    coder_b: str


@router.get("/code-segments/{cid}")
async def code_segments(cid: int, db: DbDep) -> dict:
    """All coded segments of one code across text/image/AV (code-in-all-files)."""
    return {"rows": await report_service.code_segments(db, cid)}


@router.get("/code-summary/{cid}")
async def code_summary(cid: int, db: DbDep) -> dict:
    try:
        return await report_service.code_summary(db, cid)
    except KeyError:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="code not found") from None


@router.post("/coder-file-comparison")
async def coder_file_comparison(db: DbDep, req: CoderFileComparisonRequest) -> dict:
    from fastapi import HTTPException

    try:
        return await report_service.coder_file_comparison(db, req.coder_a, req.coder_b)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.get("/code-relations")
async def code_relations(db: DbDep, owner: str | None = None) -> dict:
    """Code crossover relations for one coder (default: current coder)."""
    return await report_service.code_relations(db, owner)


@router.get("/word-frequencies")
async def word_frequencies(
    db: DbDep, source_id: int | None = None, limit: int = 100, stopwords: bool = True
) -> dict:
    return {"rows": await report_service.word_frequencies(db, source_id, limit, stopwords)}


@router.get("/charts")
async def charts(db: DbDep, kind: str = "bar-frequency") -> dict:
    """Chart datasets: cumulative | stacked-files | stacked-cases |
    bar-frequency | bar-volume | heatmap-file-code | heatmap-case."""
    from fastapi import HTTPException

    try:
        return await report_service.charts_data(db, kind)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.get("/codebook")
async def codebook(db: DbDep, memos: bool = False) -> dict:
    """Plain-text codebook (round-trippable with the codebook import)."""
    return {"text": await report_service.codebook_plain(db, include_memos=memos)}
