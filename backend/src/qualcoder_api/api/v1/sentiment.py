"""Sentiment analysis report — VADER lexicon scoring (offline) plus an
optional AI mode that classifies coded segments through the chat provider.

All endpoints depend on ``DbDep`` (409 when no project is open). Responses
are plain dicts: ``{rows, summary}``. The AI mode is gated on the AI feature
settings (the same mechanism ``/ai/status`` uses) and answers 409 when AI is
not enabled/configured.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.services import sentiment_service, user_settings
from qualcoder_api.services.ai_service import AiService, AiUnavailable

router = APIRouter(prefix="/reports/sentiment", tags=["sentiment"])


@router.get("")
async def sentiment_report(
    db: DbDep,
    svc: ServiceDep,
    scope: str = "segments",
    mode: str = "lexicon",
    fid: int | None = None,
    cid: int | None = None,
    limit: int = 100,
) -> dict:
    """Sentiment scores for coded segments (``scope=segments``) or whole
    text sources (``scope=sources``).

    ``mode=lexicon`` (default) scores offline with VADER and returns the
    ``neg/neu/pos/compound`` columns; ``mode=ai`` classifies coded segments
    through the configured chat provider (capped at ``limit`` segments, max
    100) and returns a ``sentiment`` label per row. ``fid``/``cid`` restrict
    the segments when ``scope=segments``; ``fid`` restricts sources.
    """
    if scope not in ("segments", "sources"):
        raise HTTPException(status_code=422, detail="scope must be 'segments' or 'sources'")
    if mode not in ("lexicon", "ai"):
        raise HTTPException(status_code=422, detail="mode must be 'lexicon' or 'ai'")

    if mode == "ai":
        if scope != "segments":
            raise HTTPException(
                status_code=422, detail="AI sentiment covers coded segments (scope=segments)"
            )
        ai = user_settings.get_ai_settings()
        configured, _ = AiService.is_configured(ai)
        if not ai["enabled"] or not configured:
            raise HTTPException(status_code=409, detail="AI not configured")
        try:
            body = await sentiment_service.ai_segments_sentiment(
                db,
                ai,
                session_factory=svc.session_factory,
                fid=fid,
                cid=cid,
                limit=limit,
            )
        except AiUnavailable as err:
            raise HTTPException(status_code=503, detail=str(err)) from err
        return {"mode": mode, "scope": scope, **body}

    if scope == "sources":
        body = await sentiment_service.sources_sentiment(db, fid=fid)
    else:
        body = await sentiment_service.segments_sentiment(db, fid=fid, cid=cid)
    return {"mode": mode, "scope": scope, **body}
