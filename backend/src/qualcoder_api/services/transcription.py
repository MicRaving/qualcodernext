"""Audio/video transcription — faster-whisper (bundled) and noScribe (optional).

Models are cached under ``~/.qualcoder/models/whisper`` (HuggingFace
downloads). All heavy imports are lazy so the rest of the app never pays
for them; the job registry is in-process (one backend = one instance).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path

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
    engines: dict[str, bool] = {"whisper": False, "noscribe": False}
    try:
        import faster_whisper  # noqa: F401

        engines["whisper"] = True
    except ImportError:
        pass
    try:
        import noscribe  # noqa: F401

        engines["noscribe"] = True
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
        return dict(job) if job else None


def start_job(*, source_path: str, options: dict, meta: dict | None = None) -> str:
    """Queue a transcription job and return its id (runs in a worker thread).

    ``meta`` carries completion metadata (transcript name, segment coding
    options) used by the polling endpoint to finalize the job.
    """
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _JOBS[job_id] = {
            "id": job_id,
            "state": "running",
            "progress": 0.0,
            "message": "loading model",
            "segments": 0,
            "result": None,
            "error": None,
            "started": time.time(),
            **(meta or {}),
        }
    threading.Thread(
        target=_run_worker,
        args=(job_id, source_path, dict(options)),
        daemon=True,
    ).start()
    return job_id


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(fields)


def mark_job_consumed(job_id: str, source_id: int | None) -> None:
    """Mark a finished job as finalized (transcript source created)."""
    _set_job(job_id, consumed=True, transcript_source_id=source_id)


def _run_worker(job_id: str, source_path: str, options: dict) -> None:
    engine = options.get("engine") or "whisper"
    try:
        if engine == "noscribe":
            segments = _transcribe_noscribe(job_id, source_path, options)
        else:
            segments = _transcribe_whisper(job_id, source_path, options)
        _set_job(
            job_id,
            state="done",
            progress=100.0,
            message="done",
            segments=len(segments),
            result=segments,
        )
    except Exception as err:
        logger.exception("transcription failed")
        _set_job(job_id, state="error", error=str(err), message="failed")


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
    for idx, seg in enumerate(segments_iter):
        segments.append(
            {"start": float(seg.start), "end": float(seg.end), "text": (seg.text or "").strip()}
        )
        _set_job(
            job_id,
            progress=min(99.0, float(seg.end) / duration * 100.0),
            message=f"transcribing {idx + 1}",
        )
    return segments


def _transcribe_noscribe(job_id: str, source_path: str, options: dict) -> list[dict]:
    """noScribe engine (optional; requires the noscribe package)."""
    import noscribe  # noqa: F401

    raise NotImplementedError(
        "noScribe engine not wired yet — import its .docx transcripts instead"
    )


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
