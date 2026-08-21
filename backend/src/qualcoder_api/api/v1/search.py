"""Full-text search API — literal/regex across project entity types
(files, codes, categories, cases, journal, memos, attributes, comments) with
an optional category filter for file results (``POST /search``)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.services.search_service import search_text

router = APIRouter(prefix="/search", tags=["search"])

MIN_LIMIT = 1
MAX_LIMIT = 100


class SearchRequest(BaseModel):
    query: str
    regex: bool = False
    category_id: int | None = None
    # Which entity types to search; None = all. Unknown types are rejected
    # with a 422 so a typo cannot silently return an empty result set.
    entities: list[str] | None = None
    limit: int = 20
    offset: int = 0


class SearchHit(BaseModel):
    pos0: int
    pos1: int
    #: Match offsets relative to ``context`` (the frontend highlights the
    #: exact matched part in yellow).
    rel0: int
    rel1: int
    context: str


class SearchResultItem(BaseModel):
    #: Entity type the hit lives in ("file" | "code" | "category" | "case" |
    #: "journal" | "memo" | "attribute" | "comment").
    kind: str
    #: Primary key of the matched entity (source id for files).
    id: int
    name: str
    mediapath: str
    match_count: int
    hits: list[SearchHit]
    #: Set for file hits (and file-owned memo hits) — the coder navigation
    #: target. None for the other entity types.
    source_id: int | None = None
    #: For memo hits: the owning entity kind + id (file/code/category/case/
    #: journal). For comment hits: the comment's target kind + id.
    ref_kind: str | None = None
    ref_id: int | None = None


class SearchResponse(BaseModel):
    total: int
    results: list[SearchResultItem]


@router.post("", response_model=SearchResponse)
async def search(req: SearchRequest, db: DbDep) -> SearchResponse:
    if not req.query.strip():
        raise HTTPException(status_code=422, detail="query is required")
    limit = max(MIN_LIMIT, min(MAX_LIMIT, req.limit))
    try:
        payload = await search_text(
            db,
            req.query,
            regex=req.regex,
            category_id=req.category_id,
            entities=req.entities,
            limit=limit,
            offset=req.offset,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return SearchResponse(**payload)
