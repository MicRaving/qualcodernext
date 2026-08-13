"""Sentiment scoring for the sentiment report.

Offline (default) mode scores coded segments — or whole text sources — with
the VADER lexicon (``vaderSentiment``). VADER is synchronous CPU work, so
every scoring batch runs in ``asyncio.to_thread`` and never blocks the event
loop. AI mode classifies coded segments through ``AiService.chat`` with the
``sentiment`` prompt from the AI prompt catalog.

Return shapes are plain dicts (no Pydantic models), like the other report
services. ``segments_sentiment``/``sources_sentiment`` rows carry the VADER
``neg/neu/pos/compound`` scores; ``ai_segments_sentiment`` rows carry a
``sentiment`` label (positive/negative/neutral) plus the model's ``reason``.
Every result includes a ``summary`` with distribution counts over the
compound thresholds (>= 0.05 positive, <= -0.05 negative, else neutral) and
the average compound (null in AI mode).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.services.ai_service import AiService

POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

# AI mode caps how many segments are sent to the chat provider.
AI_LIMIT_MAX = 100
AI_PROMPT_ID = "sentiment"

_SELTEXT_MAX_CHARS = 200


def compound_class(compound: float) -> str:
    """Map a VADER compound score to positive/negative/neutral."""
    if compound >= POSITIVE_THRESHOLD:
        return "positive"
    if compound <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


_analyzer: Any | None = None


def _get_analyzer():
    """Lazily-built VADER analyzer singleton (import cost paid once)."""
    global _analyzer
    if _analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def score_text(text: str) -> dict:
    """VADER scores for one text: ``neg/neu/pos/compound`` (rounded to 4dp)."""
    scores = _get_analyzer().polarity_scores(text or "")
    return {
        "neg": round(scores["neg"], 4),
        "neu": round(scores["neu"], 4),
        "pos": round(scores["pos"], 4),
        "compound": round(scores["compound"], 4),
    }


def _score_texts(texts: list[str]) -> list[dict]:
    """Synchronous bulk scoring — the unit of work handed to ``to_thread``."""
    return [score_text(text) for text in texts]


def summarize(compounds: list[float]) -> dict:
    """Distribution counts over the compound thresholds + average compound."""
    counts = Counter(compound_class(compound) for compound in compounds)
    average = sum(compounds) / len(compounds) if compounds else None
    return {
        "positive": counts["positive"],
        "negative": counts["negative"],
        "neutral": counts["neutral"],
        "total": len(compounds),
        "avg_compound": round(average, 4) if average is not None else None,
    }


async def _segment_rows(
    session: AsyncSession, fid: int | None = None, cid: int | None = None
) -> list[dict]:
    """(fid, file_name, cid, code_name, seltext) for the visible text codings.

    Reads the ``code_text_visible`` view (hidden coders' segments stay out),
    mirroring the codes-by-segments report query, plus the file and code ids
    that report does not carry.
    """
    sql = (
        "SELECT ct.fid, s.name, ct.cid, cn.name, ct.seltext "
        "FROM code_text_visible ct "
        "JOIN source s ON s.id = ct.fid "
        "JOIN code_name cn ON cn.cid = ct.cid"
    )
    clauses: list[str] = []
    params: dict[str, int] = {}
    if fid is not None:
        clauses.append("ct.fid = :fid")
        params["fid"] = fid
    if cid is not None:
        clauses.append("ct.cid = :cid")
        params["cid"] = cid
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY s.name, ct.pos0"
    rows = await session.execute(text(sql), params)
    return [
        {
            "fid": fid_,
            "file_name": file_name or "",
            "cid": cid_,
            "code_name": code_name or "",
            "seltext": (seltext or "").strip(),
        }
        for fid_, file_name, cid_, code_name, seltext in rows
    ]


async def segments_sentiment(
    session: AsyncSession, fid: int | None = None, cid: int | None = None
) -> dict:
    """Lexicon scores for each coded text segment (VADER)."""
    segments = await _segment_rows(session, fid, cid)
    scores = await asyncio.to_thread(_score_texts, [s["seltext"] for s in segments])
    rows = [
        {**segment, "seltext": segment["seltext"][:_SELTEXT_MAX_CHARS], **scores[i]}
        for i, segment in enumerate(segments)
    ]
    return {"rows": rows, "summary": summarize([row["compound"] for row in rows])}


async def sources_sentiment(
    session: AsyncSession, fid: int | None = None
) -> dict:
    """Lexicon scores for each whole text source (VADER)."""
    sql = (
        "SELECT id, name, fulltext FROM source "
        "WHERE fulltext IS NOT NULL "
        "AND (mediapath IS NULL OR mediapath LIKE '/docs/%' OR mediapath LIKE 'docs:%')"
    )
    params: dict[str, int] = {}
    if fid is not None:
        sql += " AND id = :fid"
        params["fid"] = fid
    sql += " ORDER BY name"
    rows = await session.execute(text(sql), params)
    sources = [
        {"fid": fid_, "file_name": name or "", "fulltext": (fulltext or "").strip()}
        for fid_, name, fulltext in rows
    ]
    sources = [source for source in sources if source["fulltext"]]
    scores = await asyncio.to_thread(_score_texts, [s["fulltext"] for s in sources])
    out = [
        {"fid": source["fid"], "file_name": source["file_name"], **scores[i]}
        for i, source in enumerate(sources)
    ]
    return {"rows": out, "summary": summarize([row["compound"] for row in out])}


def classify_ai_reply(reply: str) -> tuple[str, str]:
    """(sentiment label, reason) parsed from the model's reply.

    The sentiment prompt asks for exactly one word followed by a one-sentence
    justification; the label is matched case-insensitively anywhere in the
    reply, anything unrecognized falls back to neutral.
    """
    text = (reply or "").strip()
    lower = text.lower()
    for label in ("positive", "negative", "neutral"):
        if label in lower:
            return label, text[:300]
    return "neutral", text[:300]


async def ai_segments_sentiment(
    session: AsyncSession,
    ai: dict,
    session_factory: Any | None = None,
    fid: int | None = None,
    cid: int | None = None,
    limit: int = AI_LIMIT_MAX,
) -> dict:
    """Classify coded segments through the chat provider (AI mode).

    Every segment goes through ``AiService.chat`` with the ``sentiment``
    prompt (one call per segment — the prompt classifies a single text);
    the batch is capped at ``limit`` (hard max ``AI_LIMIT_MAX``). Rows carry
    the predicted ``sentiment`` label and the model's ``reason``.
    """
    segments = await _segment_rows(session, fid, cid)
    selected = segments[: min(limit, AI_LIMIT_MAX)]
    service = AiService(session_factory)
    rows: list[dict] = []
    for segment in selected:
        result = await service.chat(
            ai, segment["seltext"], mode="general", prompt_id=AI_PROMPT_ID
        )
        sentiment, reason = classify_ai_reply(result["reply"])
        rows.append(
            {
                "fid": segment["fid"],
                "file_name": segment["file_name"],
                "cid": segment["cid"],
                "code_name": segment["code_name"],
                "seltext": segment["seltext"][:_SELTEXT_MAX_CHARS],
                "sentiment": sentiment,
                "reason": reason,
            }
        )
    counts = Counter(row["sentiment"] for row in rows)
    return {
        "rows": rows,
        "summary": {
            "positive": counts["positive"],
            "negative": counts["negative"],
            "neutral": counts["neutral"],
            "total": len(rows),
            "avg_compound": None,
        },
    }
