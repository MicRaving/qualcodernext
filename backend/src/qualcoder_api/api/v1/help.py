"""In-app help API — bundled markdown documentation topics and search."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from qualcoder_api.services import help_service

router = APIRouter(prefix="/help", tags=["help"])


@router.get("/topics")
async def help_topics() -> dict:
    return {"topics": help_service.list_topics()}


@router.get("/topic/{topic_id}")
async def help_topic(topic_id: str) -> dict:
    topic = help_service.get_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="unknown topic")
    return {"topic": topic}


@router.get("/search")
async def help_search(
    q: str = Query(default="", max_length=500),
    regex: bool = Query(default=False),
) -> dict:
    if not q.strip():
        raise HTTPException(status_code=422, detail="query is empty")
    if len(q.strip()) > 500:
        raise HTTPException(status_code=422, detail="query too long")
    try:
        results = help_service.search_topics(q.strip(), regex=regex)
    except re.error as err:
        raise HTTPException(status_code=422, detail=f"invalid regex: {err}") from err
    return {"query": q.strip(), "results": results}
