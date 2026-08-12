"""Batch AI autocoding — background jobs (one per source file).

Jobs live in an in-process registry (like transcription) and run one file
at a time in a worker thread. The UI drives the queue through the same
``start`` / ``pause`` / ``resume`` / ``cancel`` controls as transcription.

A pause only takes effect *between* files — the LLM call itself cannot be
interrupted; with the UI dispatching one job at a time that is effectively
a per-file pause.
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


def _snapshot(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        return {k: v for k, v in job.items() if not k.startswith("_")} if job else None


def start_batch(
    *,
    session_factory,
    project_path: str,
    source_ids: list[int],
    cids: list[int],
    prompt: str,
    suggest: bool,
    owner: str,
    auto_start: bool = False,
) -> list[str]:
    """Create one queued autocode job per source and return their ids.

    With ``auto_start=False`` (default) jobs wait for a ``start`` control —
    the UI dispatcher runs them sequentially so the queue stays orderly.
    """
    job_ids: list[str] = []
    for fid in source_ids:
        job_id = uuid.uuid4().hex[:12]
        start_event = threading.Event()
        pause_event = threading.Event()
        cancel_event = threading.Event()
        # A set pause event means "running allowed" (default); control_job's
        # pause/resume clear/set it.
        pause_event.set()
        if auto_start:
            start_event.set()
        with _jobs_lock:
            _JOBS[job_id] = {
                "id": job_id,
                "state": "running" if auto_start else "queued",
                "progress": 0.0,
                "message": "queued",
                "source_id": fid,
                "result": None,
                "error": None,
                "paused": False,
                "started": time.time(),
                "_start": start_event,
                "_pause": pause_event,
                "_cancel": cancel_event,
                "_session_factory": session_factory,
                "_project_path": project_path,
                "_cids": cids,
                "_prompt": prompt,
                "_suggest": suggest,
                "_owner": owner,
            }
        threading.Thread(target=_run_worker, args=(job_id,), daemon=True).start()
        job_ids.append(job_id)
    return job_ids


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


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(fields)


def _wait_gate(job_id: str) -> bool:
    """Block while queued/paused; returns True when the job may run, False
    when it was cancelled."""
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
            job = _JOBS[job_id]
            session_factory = job["_session_factory"]
            fid = job["source_id"]
            cids = job["_cids"]
            prompt = job["_prompt"]
            suggest = job["_suggest"]
            owner = job["_owner"]
        _set_job(job_id, progress=5.0, message="coding")
        result = asyncio.run(
            _run_one(session_factory, fid, cids, prompt, suggest, owner)
        )
        if not _wait_gate(job_id):
            return
        _set_job(
            job_id,
            state="done",
            progress=100.0,
            message="done",
            result=result,
        )
    except Exception as err:  # pragma: no cover - defensive
        logger.exception("autocode job failed")
        _set_job(job_id, state="error", error=str(err), message="failed")


async def _run_one(session_factory, fid: int, cids: list[int], prompt: str, suggest: bool, owner: str) -> dict:
    from qualcoder_api.services.coding_service import ai_autocode

    async with session_factory() as session:
        return await ai_autocode(
            session, fid=fid, cids=cids, prompt=prompt, suggest=suggest, owner=owner
        )
