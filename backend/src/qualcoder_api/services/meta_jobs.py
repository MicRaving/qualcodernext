"""Meta pipeline background jobs — in-process thread registry.

Follows the transcription/autocode job pattern (``autocode_jobs.py``): jobs
live in a process-wide registry and run one at a time in a worker thread with
``start`` / ``pause`` / ``resume`` / ``cancel`` controls. A pause only takes
effect *between* units of work — the LLM call itself cannot be interrupted.

Meta jobs are local-only (no ``sync_log`` rows): their progress/state is
ephemeral; the durable pipeline state lives in the ``meta_*`` tables.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid

logger = logging.getLogger(__name__)

_JOBS: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_VALID_KINDS = ("screen", "download", "extract")


def _snapshot(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        return {k: v for k, v in job.items() if not k.startswith("_")}


def start_job(
    *,
    kind: str,
    label: str,
    run: object,
    auto_start: bool = True,
) -> str:
    """Create a meta job. ``run`` is an async callable ``async def run(
    progress_cb, should_stop) -> dict``; its dict return is stored as
    ``result``. Returns the job id."""
    if kind not in _VALID_KINDS:
        raise ValueError(f"kind must be one of {_VALID_KINDS}")
    job_id = uuid.uuid4().hex[:12]
    start_event = threading.Event()
    pause_event = threading.Event()
    cancel_event = threading.Event()
    pause_event.set()
    if auto_start:
        start_event.set()
    with _jobs_lock:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "label": label,
            "state": "running" if auto_start else "queued",
            "progress": 0.0,
            "message": "queued",
            "result": None,
            "error": None,
            "paused": False,
            "started": time.time(),
            "_start": start_event,
            "_pause": pause_event,
            "_cancel": cancel_event,
            "_run": run,
        }
    threading.Thread(target=_run_worker, args=(job_id,), daemon=True).start()
    return job_id


def control_job(job_id: str, action: str) -> bool:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return False
        state = job.get("state")
        if action == "start" and state in ("queued",):
            job["_start"].set()
            job["state"] = "running"
            job["message"] = "starting"
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


def get_job(job_id: str) -> dict | None:
    return _snapshot(job_id)


def list_jobs(kind: str | None = None) -> list[dict]:
    with _jobs_lock:
        jobs = [
            {k: v for k, v in job.items() if not k.startswith("_")}
            for job in _JOBS.values()
        ]
    if kind:
        jobs = [j for j in jobs if j.get("kind") == kind]
    jobs.sort(key=lambda j: j.get("started") or 0, reverse=True)
    return jobs


def delete_job(job_id: str) -> bool:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return False
        job["_cancel"].set()
        del _JOBS[job_id]
    return True


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(fields)


def _wait_gate(job_id: str) -> bool:
    """Block while queued/paused; True when the job may run, False when
    cancelled."""
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return False
        start, pause, cancel = job["_start"], job["_pause"], job["_cancel"]
    start.wait()
    while not cancel.is_set() and not pause.is_set():
        if cancel.wait(0.25):
            break
    return not cancel.is_set()


def _run_worker(job_id: str) -> None:
    try:
        if not _wait_gate(job_id):
            return
        with _jobs_lock:
            job = _JOBS.get(job_id)
            if job is None:
                return
            run_fn = job["_run"]
        _set_job(job_id, progress=1.0, message="running")

        def progress_cb(done: float, total: float = 100.0, message: str = "") -> None:
            pct = min(99.0, (done / max(total, 1)) * 100.0)
            _set_job(job_id, progress=pct, message=message or job.get("message", "running"))

        def should_stop() -> bool:
            with _jobs_lock:
                current = _JOBS.get(job_id)
                if current is None:
                    return True
                return current["_cancel"].is_set()

        result = asyncio.run(run_fn(progress_cb, should_stop))  # type: ignore[operator]
        if not _wait_gate(job_id):
            return
        _set_job(job_id, state="done", progress=100.0, message="done", result=result)
    except Exception as err:  # pragma: no cover - defensive
        logger.exception("meta job failed: %s", job_id)
        _set_job(job_id, state="error", error=str(err), message="failed")
