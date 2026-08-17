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
from qualcoder_api.persistence import tables
from qualcoder_api.services.transcription import (
    TRANSCRIPTION_DEFAULTS,
    get_job,
    get_status,
    mark_job_consumed,
    start_job,
)

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
    # False enqueues the job ("queued" state) without starting it; the UI
    # dispatcher starts queued jobs one by one via POST /jobs/{id}/start.
    start: bool = True


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

    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername, get_transcription_settings

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    row = (
        await db.execute(select(tables.source).where(tables.source.c.id == req.source_id))
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="source not found")
    mediapath = row.mediapath or ""
    if mediapath.startswith(("/audio/", "/video/")):
        source_path = os.path.join(svc.project_path, mediapath.lstrip("/"))
    elif mediapath.startswith(("audio:", "video:")):
        # Linked (external) source: the path is stored verbatim.
        source_path = mediapath.split(":", 1)[1]
    else:
        raise HTTPException(status_code=422, detail="source is not audio/video")
    if not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail="media file missing on disk")

    # Request fields override the saved transcription settings, which in
    # turn override the built-in defaults.
    saved = get_transcription_settings()
    options = {
        "engine": req.engine or saved.get("engine") or TRANSCRIPTION_DEFAULTS["engine"],
        "model": req.model or saved.get("model") or TRANSCRIPTION_DEFAULTS["model"],
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
        "project_path": svc.project_path,
    }
    job_id = start_job(source_path=source_path, options=options, meta=meta, auto_start=req.start)
    await audit.record(
        db, user=get_codername(), action="transcribe.start", entity="source",
        source_id=req.source_id, entity_id=req.source_id,
        detail={"job_id": job_id, "model": options["model"], "engine": options["engine"]},
    )
    return {"job_id": job_id}


@router.post("/jobs/{job_id}/{action}")
async def control(job_id: str, action: str) -> dict:
    """Queue controls: ``start`` (begin a queued job), ``pause`` / ``resume``
    (halt/resume transcribing between segments), ``cancel``."""
    from qualcoder_api.services.transcription import control_job

    if action not in ("start", "pause", "resume", "cancel"):
        raise HTTPException(status_code=422, detail="unknown action")
    ok = control_job(job_id, action)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or not controllable")
    return {"ok": True}


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict:
    """Cancel/remove a job: queued jobs never start, running jobs stop at the
    next segment boundary (the transcript sidecar is discarded)."""
    from qualcoder_api.services.transcription import control_job

    ok = control_job(job_id, "cancel")
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or already finished")
    return {"ok": True}


@router.get("/jobs/{job_id}")
async def job(job_id: str, svc: ServiceDep) -> dict:
    """Poll a job; on completion the transcript source (and optional
    per-segment codings) are created exactly once, then the result is
    returned with the created source id."""
    job_data = get_job(job_id)
    if job_data is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job_data.get("state") != "done":
        return job_data
    # Reserve the job atomically: concurrent polls (or a poll racing the
    # project-open sweep) must not both finalize the same transcript.
    from qualcoder_api.services.transcription import claim_finished_job

    if not claim_finished_job(job_id):
        return get_job(job_id) or job_data

    from qualcoder_api.services.transcription import finalize_transcript

    try:
        source_id = await finalize_transcript(
            job_data=job_data,
            project_path=svc.project_path,
            session_factory=svc.session_factory,
        )
    except Exception:
        # Let a later poll retry finalization instead of losing the job.
        from qualcoder_api.services.transcription import _set_job

        _set_job(job_id, consumed=False)
        raise
    # The worker already persisted the transcript sidecar; it is finalized
    # here, so remove the leftovers.
    pending_dir = os.path.join(svc.project_path, "_transcripts")
    for name in (f"{job_id}.json", f"{job_id}.txt"):
        with contextlib.suppress(OSError):
            os.remove(os.path.join(pending_dir, name))

    mark_job_consumed(job_id, source_id)
    result = get_job(job_id)
    return result if result is not None else {"job_id": job_id}
