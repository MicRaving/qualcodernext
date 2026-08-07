"""Transcription API — status, job submission, job polling.

The job worker writes the finished transcript as a new text source next to
the media file and (optionally) codes each segment onto the timeline.
"""

from __future__ import annotations

import contextlib
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.services import audit
from qualcoder_api.services.transcription import (
    TRANSCRIPTION_DEFAULTS,
    get_job,
    get_status,
    mark_job_consumed,
    segments_to_text,
    start_job,
)
from qualcoder_api.services.user_settings import get_codername

router = APIRouter(prefix="/transcribe", tags=["transcribe"])


class TranscribeRequest(BaseModel):
    source_id: int
    engine: str = "whisper"
    model: str | None = None
    language: str | None = None
    translate: bool = False
    beam_size: int = 5
    temperature: float = 0.0
    vad: bool = True
    device: str = "auto"
    timestamps: bool = True
    segment_coding: bool = False
    segment_cid: int | None = None


@router.get("/status")
async def status() -> dict:
    from qualcoder_api.services.user_settings import get_transcription_settings

    info = get_status()
    info["settings"] = get_transcription_settings()
    return info


class TranscribeSettingsRequest(BaseModel):
    engine: str | None = None
    model: str | None = None
    language: str | None = None
    translate: bool | None = None
    beam_size: int | None = None
    temperature: float | None = None
    vad: bool | None = None
    device: str | None = None
    segment_coding: bool | None = None


@router.put("/settings")
async def save_settings(req: TranscribeSettingsRequest) -> dict:
    from qualcoder_api.services.user_settings import save_transcription_settings

    return save_transcription_settings(req.model_dump(exclude_none=True))


@router.post("", status_code=202)
async def transcribe(req: TranscribeRequest, svc: ServiceDep, db: DbDep) -> dict:
    """Start a transcription job; returns its id for polling."""
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    row = (
        await db.execute(select(tables.source).where(tables.source.c.id == req.source_id))
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="source not found")
    mediapath = row.mediapath or ""
    if not mediapath.startswith(("/audio/", "/video/")):
        raise HTTPException(status_code=422, detail="source is not audio/video")
    source_path = os.path.join(svc.project_path, mediapath.lstrip("/"))
    if not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail="media file missing on disk")

    options = {
        "engine": req.engine,
        "model": req.model or TRANSCRIPTION_DEFAULTS["model"],
        "language": req.language,
        "translate": req.translate,
        "beam_size": req.beam_size,
        "temperature": req.temperature,
        "vad": req.vad,
        "device": req.device,
    }

    base_name = (row[1] or f"source{req.source_id}").rsplit(".", 1)[0]
    meta = {
        "source_id": req.source_id,
        "transcript_name": f"{base_name}.txt",
        "timestamps": req.timestamps,
        "segment_coding": req.segment_coding,
        "segment_cid": req.segment_cid,
    }
    job_id = start_job(source_path=source_path, options=options, meta=meta)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def job(job_id: str, svc: ServiceDep) -> dict:
    """Poll a job; on completion the transcript source (and optional
    per-segment codings) are created exactly once, then the result is
    returned with the created source id."""
    job_data = get_job(job_id)
    if job_data is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job_data.get("state") != "done" or job_data.get("consumed"):
        return job_data

    from qualcoder_api.persistence.repositories import CodingRepository
    from qualcoder_api.services.import_service import ImportService

    segments = job_data.get("result") or []
    source_id = None
    if segments and svc.session_factory is not None:
        factory = svc.session_factory
        transcript = segments_to_text(segments, timestamps=job_data.get("timestamps", True))
        media_source_id = job_data.get("source_id")
        tmp_txt = os.path.join(svc.project_path, f"_transcript_{job_id}.txt")
        with open(tmp_txt, "w", encoding="utf-8") as f:  # noqa: ASYNC230 - small local write
            f.write(transcript)
        try:
            importer = ImportService(svc.project_path, svc.session_factory)
            source = await importer.import_file(
                tmp_txt,
                owner=get_codername(),
                link=False,
                filename=job_data.get("transcript_name", "transcript.txt"),
            )
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp_txt)
        if source is not None:
            source_id = source.id
            # Link the transcript to the media source (the video view shows
            # it; the importer already created an empty companion for most
            # AV files — prefer that one over a second source).
            async with factory() as session:
                from sqlalchemy import delete, select, update

                from qualcoder_api.persistence import tables

                media_row = (
                    await session.execute(
                        select(tables.source).where(tables.source.c.id == media_source_id)
                    )
                ).first()
                companion_id = media_row.av_text_id if media_row is not None else None
                if companion_id is not None:
                    # Fold the transcript into the linked companion instead of
                    # leaving a second, orphaned source behind.
                    await session.execute(
                        update(tables.source)
                        .where(tables.source.c.id == companion_id)
                        .values(fulltext=transcript)
                    )
                    await session.execute(
                        update(tables.source)
                        .where(tables.source.c.id == source_id)
                        .values(fulltext="")
                    )
                    await session.commit()
                    await session.execute(
                        delete(tables.source).where(tables.source.c.id == source_id)
                    )
                    await session.commit()
                    source_id = companion_id
                else:
                    await session.execute(
                        update(tables.source)
                        .where(tables.source.c.id == media_source_id)
                        .values(av_text_id=source_id)
                    )
                    await session.commit()
            async with factory() as session:
                await audit.record(
                    session, user=get_codername(), action="source.import", entity="source",
                    entity_id=source_id,
                    detail={"name": "transcript", "transcription": True},
                )
            if job_data.get("segment_coding") and job_data.get("segment_cid") is not None:
                async with factory() as session:
                    repo = CodingRepository(session)
                    for seg in segments:
                        await repo.add_av_coding(
                            id=int(media_source_id or 0),
                            pos0=int(seg["start"] * 1000),
                            pos1=int(seg["end"] * 1000),
                            cid=job_data["segment_cid"],
                            owner=get_codername(),
                        )

    mark_job_consumed(job_id, source_id)
    result = get_job(job_id)
    return result if result is not None else {"job_id": job_id}
