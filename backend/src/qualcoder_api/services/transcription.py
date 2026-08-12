"""Audio/video transcription — faster-whisper (bundled).

Models are cached under ``~/.qualcoder/models/whisper`` (HuggingFace
downloads). All heavy imports are lazy so the rest of the app never pays
for them; the job registry is in-process (one backend = one instance).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from qualcoder_api.services import audit

logger = logging.getLogger(__name__)

MODEL_CACHE = Path(os.path.expanduser("~")) / ".qualcoder" / "models" / "whisper"

TRANSCRIPTION_DEFAULTS: dict = {
    "engine": "whisper",
    "model": "large-v3-turbo",
    "language": None,
    "translate": False,
    "beam_size": 5,
    "temperature": 0.0,
    "vad": True,
    "device": "auto",
    "segment_coding": False,
}

# In-process job registry: job_id -> state dict. One backend serves one
# app instance, so an in-memory registry is sufficient.
_JOBS: dict[str, dict] = {}
_jobs_lock = threading.Lock()

WHISPER_MODELS = (
    "tiny",
    "tiny.en",
    "base",
    "base.en",
    "small",
    "small.en",
    "medium",
    "medium.en",
    "large-v1",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
    "distil-large-v3",
)


def engines_available() -> dict[str, bool]:
    """Which transcription engines are importable in this environment."""
    engines: dict[str, bool] = {"whisper": False}
    try:
        import faster_whisper  # noqa: F401

        engines["whisper"] = True
    except ImportError:
        pass
    return engines


def get_status() -> dict:
    models = (
        sorted(p.name for p in MODEL_CACHE.iterdir() if p.is_dir())
        if MODEL_CACHE.exists()
        else []
    )
    return {
        "engines": engines_available(),
        "models_cached": models,
        "model_dir": str(MODEL_CACHE),
        "models": list(WHISPER_MODELS),
        "defaults": dict(TRANSCRIPTION_DEFAULTS),
    }


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        # Strip the private control events — they must never be JSON-serialized.
        return {k: v for k, v in job.items() if not k.startswith("_")} if job else None


def start_job(
    *,
    source_path: str,
    options: dict,
    meta: dict | None = None,
    auto_start: bool = True,
) -> str:
    """Queue a transcription job and return its id (runs in a worker thread).

    ``meta`` carries completion metadata (transcript name, segment coding
    options) used by the polling endpoint to finalize the job. With
    ``auto_start=False`` the job is created in the ``queued`` state and only
    begins transcribing once :func:`control_job` is called with ``"start"``
    (the UI drives a sequential queue this way).
    """
    job_id = uuid.uuid4().hex[:12]
    start_event = threading.Event()
    pause_event = threading.Event()
    cancel_event = threading.Event()
    # A set pause event means "running allowed" (default). control_job's
    # pause/resume clear/set it.
    pause_event.set()
    if auto_start:
        start_event.set()
    with _jobs_lock:
        _JOBS[job_id] = {
            "id": job_id,
            "state": "running" if auto_start else "queued",
            "progress": 0.0,
            "message": "loading model" if auto_start else "queued",
            "segments": 0,
            "result": None,
            "error": None,
            "live_text": None,
            "paused": False,
            "started": time.time(),
            "_start": start_event,
            "_pause": pause_event,
            "_cancel": cancel_event,
            **(meta or {}),
        }
    threading.Thread(
        target=_run_worker,
        args=(job_id, source_path, dict(options)),
        daemon=True,
    ).start()
    return job_id


def control_job(job_id: str, action: str) -> bool:
    """Apply a queue control to a job: ``start``, ``pause``, ``resume`` or
    ``cancel``. Returns False when the job id is unknown (or no longer
    controllable)."""
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return False
        state = job.get("state")
        if action == "start" and state in ("queued",):
            job["_start"].set()
            job["state"] = "running"
            job["message"] = "loading model"
        elif action == "pause" and state in ("running",):
            job["_pause"].clear()
            job["paused"] = True
        elif action == "resume":
            job["_pause"].set()
            job["paused"] = False
        elif action == "cancel" and state in ("queued", "running", "paused"):
            job["_cancel"].set()
            job["state"] = "cancelled"
            job["message"] = "cancelled"
        else:
            return False
        return True


def _gate(job_id: str) -> None:
    """Block the worker while the job is paused, aborting on cancel."""
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return
        start = job["_start"]
        pause = job["_pause"]
        cancel = job["_cancel"]
    start.wait()
    while cancel.is_set() is False and pause.is_set() is False:
        if cancel.wait(0.25):
            break


class JobCancelled(Exception):
    """Raised by workers when a job is cancelled mid-transcription."""


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(fields)


def claim_finished_job(job_id: str) -> bool:
    """Atomically reserve a finished job for finalization. Exactly one
    caller wins (concurrent polls race otherwise and would both create the
    transcript source); the loser sees ``consumed`` set and skips."""
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None or job.get("state") != "done" or job.get("consumed"):
            return False
        job["consumed"] = True
        return True


def mark_job_consumed(job_id: str, source_id: int | None) -> None:
    """Mark a finished job as finalized (transcript source created)."""
    _set_job(job_id, consumed=True, transcript_source_id=source_id)


def _run_worker(job_id: str, source_path: str, options: dict) -> None:
    try:
        # A queued job waits here until the UI starts it (or cancels it).
        _gate(job_id)
        if _is_cancelled(job_id):
            return
        # Whisper is the only engine; any legacy engine value stored in
        # the options (or an old settings file) is treated as whisper.
        segments = _transcribe_whisper(job_id, source_path, options)
        if _is_cancelled(job_id):
            return
        # Persist the finished transcript so it survives an app restart even
        # when nobody polls the job (a sweep on project open finalizes it).
        persist_finished_job(job_id)
        _set_job(
            job_id,
            state="done",
            progress=100.0,
            message="done",
            segments=len(segments),
            result=segments,
        )
    except JobCancelled:
        _set_job(job_id, state="cancelled", message="cancelled")
    except Exception as err:
        logger.exception("transcription failed")
        _set_job(job_id, state="error", error=str(err), message="failed")


def _is_cancelled(job_id: str) -> bool:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        return bool(job and job.get("_cancel") and job["_cancel"].is_set())


def persist_finished_job(job_id: str) -> None:
    """Write the finished job's transcript to the project dir as a sidecar
    (``_transcripts/<job_id>.json`` + ``.txt``). The API finalizes these on
    project open or on the next job poll, so completed transcriptions are
    never lost when the app quits mid-poll."""
    with _jobs_lock:
        job = dict(_JOBS.get(job_id) or {})
    project_path = job.get("project_path")
    if not project_path or job.get("state") == "error":
        return
    segments = job.get("result") or []
    if not segments:
        return
    try:
        out_dir = Path(project_path) / "_transcripts"
        out_dir.mkdir(parents=True, exist_ok=True)
        text = segments_to_text(segments, timestamps=bool(job.get("timestamps", True)))
        (out_dir / f"{job_id}.txt").write_text(text, encoding="utf-8")
        sidecar = {
            "source_id": job.get("source_id"),
            "transcript_name": job.get("transcript_name", "transcript.txt"),
            "timestamps": bool(job.get("timestamps", True)),
            "segment_coding": bool(job.get("segment_coding", False)),
            "segment_cid": job.get("segment_cid"),
            "segments": segments,
        }
        (out_dir / f"{job_id}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        logger.exception("could not persist finished transcript")


async def finalize_transcript(
    *,
    job_data: dict,
    project_path: str,
    session_factory,
) -> int | None:
    """Create the transcript source for a finished job, fold it into the AV
    companion and link ``av_text_id``; optionally codes every segment onto
    the timeline. Returns the transcript source id (or the companion id)."""
    import contextlib

    from qualcoder_api.persistence.repositories import CodingRepository, _capture, _rowdict
    from qualcoder_api.services.import_service import ImportService
    from qualcoder_api.services.user_settings import get_codername

    segments = job_data.get("result") or []
    source_id = None
    if segments and session_factory is not None:
        transcript = segments_to_text(segments, timestamps=job_data.get("timestamps", True))
        media_source_id = job_data.get("source_id")
        tmp_txt = os.path.join(project_path, f"_transcript_{job_data['id']}.txt")
        with open(tmp_txt, "w", encoding="utf-8") as f:  # noqa: ASYNC230 - small local write
            f.write(transcript)
        try:
            importer = ImportService(project_path, session_factory)
            source = await importer.import_file(
                tmp_txt,
                owner=get_codername(),
                link=False,
                filename=job_data.get("transcript_name", "transcript.txt"),
            )
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp_txt)
        if source is None:
            # Re-transcription: a transcript with the same name already
            # exists (import returns None on duplicates). Update its text
            # instead of silently discarding the new result.
            from sqlalchemy import select, update

            from qualcoder_api.persistence import tables

            transcript_name = job_data.get("transcript_name", "transcript.txt")
            async with session_factory() as session:
                existing = (
                    await session.execute(
                        select(tables.source).where(tables.source.c.name == transcript_name)
                    )
                ).first()
                if existing is not None:
                    await session.execute(
                        update(tables.source)
                        .where(tables.source.c.id == existing.id)
                        .values(fulltext=transcript)
                    )
                    updated = (
                        await session.execute(
                            select(tables.source).where(tables.source.c.id == existing.id)
                        )
                    ).first()
                    if updated is not None:
                        await _capture(
                            session, "source", "update", "id", existing.id, _rowdict(updated)
                        )
                    media_row = (
                        await session.execute(
                            select(tables.source).where(tables.source.c.id == media_source_id)
                        )
                    ).first()
                    if media_row is not None and media_row.av_text_id is None:
                        await session.execute(
                            update(tables.source)
                            .where(tables.source.c.id == media_source_id)
                            .values(av_text_id=existing.id)
                        )
                        media_after = (
                            await session.execute(
                                select(tables.source).where(tables.source.c.id == media_source_id)
                            )
                        ).first()
                        if media_after is not None:
                            await _capture(
                                session, "source", "update", "id", media_source_id,
                                _rowdict(media_after),
                            )
                    await session.commit()
                    source_id = existing.id
        if source is not None:
            source_id = source.id
            from sqlalchemy import delete, select, update

            from qualcoder_api.persistence import tables

            async with session_factory() as session:
                media_row = (
                    await session.execute(
                        select(tables.source).where(tables.source.c.id == media_source_id)
                    )
                ).first()
                companion_id = media_row.av_text_id if media_row is not None else None
                companion_row = None
                if companion_id is not None:
                    companion_row = (
                        await session.execute(
                            select(tables.source).where(tables.source.c.id == companion_id)
                        )
                    ).first()
                if companion_row is not None:
                    await session.execute(
                        update(tables.source)
                        .where(tables.source.c.id == companion_id)
                        .values(fulltext=transcript)
                    )
                    # Capture the POST-update row — the sidecar is replayed
                    # by collaborators, so a stale (pre-update) snapshot
                    # would overwrite their transcript with the old text.
                    companion_after = (
                        await session.execute(
                            select(tables.source).where(tables.source.c.id == companion_id)
                        )
                    ).first()
                    if companion_after is not None:
                        await _capture(
                            session, "source", "update", "id", companion_id,
                            _rowdict(companion_after),
                        )
                    dup_row = (
                        await session.execute(
                            select(tables.source).where(tables.source.c.id == source_id)
                        )
                    ).first()
                    await session.execute(
                        update(tables.source)
                        .where(tables.source.c.id == source_id)
                        .values(fulltext="")
                    )
                    await session.execute(
                        delete(tables.source).where(tables.source.c.id == source_id)
                    )
                    if dup_row is not None:
                        await _capture(
                            session, "source", "delete", "id", int(source_id), _rowdict(dup_row)
                        )
                    await session.commit()
                    source_id = companion_id
                else:
                    await session.execute(
                        update(tables.source)
                        .where(tables.source.c.id == media_source_id)
                        .values(av_text_id=source_id)
                    )
                    media_after = (
                        await session.execute(
                            select(tables.source).where(tables.source.c.id == media_source_id)
                        )
                    ).first()
                    if media_after is not None:
                        await _capture(
                            session, "source", "update", "id", media_source_id,
                            _rowdict(media_after),
                        )
                    await session.commit()
        async with session_factory() as session:
            await audit.record(
                session,
                user=get_codername(),
                action="source.import",
                entity="source",
                entity_id=source_id,
                detail={"name": "transcript", "transcription": True},
            )
        if job_data.get("segment_coding") and job_data.get("segment_cid") is not None:
            async with session_factory() as session:
                repo = CodingRepository(session)
                for seg in segments:
                    await repo.add_av_coding(
                        id=int(media_source_id or 0),
                        pos0=int(seg["start"] * 1000),
                        pos1=int(seg["end"] * 1000),
                        cid=job_data["segment_cid"],
                        owner=get_codername(),
                    )
    return source_id


async def sweep_pending_transcripts(*, project_path: str, session_factory) -> list[dict]:
    """Finalize transcripts persisted by completed jobs (so transcriptions
    survive app restarts). Runs on project open; deletes the sidecars."""
    if not project_path or session_factory is None:
        return []
    dir_ = Path(project_path) / "_transcripts"
    if not dir_.exists():
        return []
    finalized: list[dict] = []
    for sidecar in sorted(dir_.glob("*.json")):
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["id"] = sidecar.stem
        try:
            sid = await finalize_transcript(
                job_data=data,
                project_path=project_path,
                session_factory=session_factory,
            )
            finalized.append({"job_id": sidecar.stem, "transcript_source_id": sid})
        except Exception:
            logger.exception("failed to finalize persisted transcript %s", sidecar.stem)
            continue
        sidecar.unlink(missing_ok=True)
        (dir_ / f"{sidecar.stem}.txt").unlink(missing_ok=True)
    return finalized


def _transcribe_whisper(job_id: str, source_path: str, options: dict) -> list[dict]:
    """faster-whisper worker (runs off the event loop)."""
    from faster_whisper import WhisperModel

    model_name = options.get("model") or TRANSCRIPTION_DEFAULTS["model"]
    device = "cuda" if options.get("device") == "cuda" else "cpu"
    compute_type = options.get("compute_type") or ("float16" if device == "cuda" else "int8")
    _set_job(job_id, message=f"loading model {model_name}")
    model = WhisperModel(
        model_name, device=device, compute_type=compute_type, download_root=str(MODEL_CACHE)
    )
    _set_job(job_id, message="transcribing")
    segments_iter, info = model.transcribe(
        source_path,
        language=(options.get("language") or None) or None,
        task="translate" if options.get("translate") else "transcribe",
        beam_size=int(options.get("beam_size") or TRANSCRIPTION_DEFAULTS["beam_size"]),
        temperature=float(options.get("temperature") or TRANSCRIPTION_DEFAULTS["temperature"]),
        vad_filter=bool(options.get("vad", True)),
    )
    duration = max(float(getattr(info, "duration", 0) or 0), 1.0)
    segments: list[dict] = []
    live_lines: list[str] = []
    for idx, seg in enumerate(segments_iter):
        _gate(job_id)
        if _is_cancelled(job_id):
            raise JobCancelled
        segments.append(
            {"start": float(seg.start), "end": float(seg.end), "text": (seg.text or "").strip()}
        )
        # Live preview: keep the partial transcript on the job so the video
        # view can show it while the transcription is still running.
        text = (seg.text or "").strip()
        if text:
            live_lines.append(f"{format_timestamp(float(seg.start))} {text}")
        _set_job(
            job_id,
            progress=min(99.0, float(seg.end) / duration * 100.0),
            message=f"transcribing {idx + 1}",
            live_text="\n".join(live_lines),
        )
    return segments


# ----------------------------------------------------------------------
# Transcript formatting / import helpers
# ----------------------------------------------------------------------

def format_timestamp(seconds: float) -> str:
    """Format seconds as [mm:ss] (or [hh:mm:ss] for long media)."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def segments_to_text(segments: list[dict], timestamps: bool = True) -> str:
    """Render segments as lines (with or without [mm:ss] prefixes)."""
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if timestamps:
            lines.append(f"{format_timestamp(seg.get('start', 0))} {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def parse_timestamped_text(text: str) -> list[dict]:
    """Parse transcript lines back into segments (round-trip helper)."""
    import re

    pattern = re.compile(r"^\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.*)$")
    segments: list[dict] = []
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        if match.group(3) is not None:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            secs = int(match.group(3))
        else:
            minutes = int(match.group(1))
            secs = int(match.group(2))
            hours = 0
        start = hours * 3600 + minutes * 60 + secs
        segments.append({"start": float(start), "end": float(start), "text": match.group(4).strip()})
    return segments
