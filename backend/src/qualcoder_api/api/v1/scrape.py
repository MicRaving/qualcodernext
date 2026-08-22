"""URL import API — YouTube videos, articles, raw HTML, PDF.

``POST /scrape/import`` fetches a URL, reduces it to text (or raw HTML,
or a rendered PDF document) and persists it through the same file-import
pipeline as an upload, so duplicate detection, attribute placeholders and
audit behave identically.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep
from qualcoder_api.services import audit
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/scrape", tags=["scrape"])

VALID_MODES = ("auto", "youtube", "article", "html", "pdf")


class ScrapeImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    mode: str = "auto"


class ScrapeImportResponse(BaseModel):
    source_id: int
    name: str
    mode: str
    text_length: int


@router.post("/import", response_model=ScrapeImportResponse)
async def scrape_import(
    req: ScrapeImportRequest,
    db: DbDep,
    svc: OpenProjectDep,
) -> ScrapeImportResponse:
    """Import a web resource as a new source (blocking fetch runs off-loop)."""
    from qualcoder_api.services.import_service import ImportService
    from qualcoder_api.services.scrape_service import ScrapeError, scrape_url

    if req.mode not in VALID_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {', '.join(VALID_MODES)}")

    assert svc.session_factory is not None
    try:
        scraped = await asyncio.to_thread(scrape_url, req.url, req.mode)
    except ScrapeError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err

    tmp = svc.project_path + "/_scrape_" + scraped.filename
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        out.write(scraped.data)
    try:
        service = ImportService(svc.project_path, svc.session_factory)
        source = await service.import_file(
            tmp, owner=resolve_owner(None), link=False, filename=scraped.filename
        )
    finally:
        os.remove(tmp)
    if source is None:
        raise HTTPException(status_code=409, detail="duplicate filename or import failed")

    await audit.record(
        db,
        user=get_codername(),
        action="scrape.import",
        entity="source",
        entity_id=source.id,
        source_id=source.id,
        detail={"name": source.name, "mode": scraped.mode, "url": req.url},
    )
    return ScrapeImportResponse(
        source_id=source.id,
        name=source.name,
        mode=scraped.mode,
        text_length=len(source.fulltext or ""),
    )
