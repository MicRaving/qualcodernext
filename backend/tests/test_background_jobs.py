"""Background job queue tests — transcription + batch autocode registry
controls (queued → start → pause/resume → cancel). No real transcription or
LLM calls run here: the workers wait on their control events."""

from __future__ import annotations

import time

from qualcoder_api.services import autocode_jobs, transcription


async def _fake_session_factory():
    raise AssertionError("worker must not run in registry-control tests")


# ----------------------------------------------------------------------
# transcription queue controls
# ----------------------------------------------------------------------


def test_transcribe_job_starts_immediately_by_default():
    job_id = transcription.start_job(
        source_path="nope.wav",
        options={"engine": "whisper", "model": "tiny"},
        meta={"source_id": 1, "transcript_name": "t.txt", "project_path": "/tmp"},
    )
    try:
        job = transcription.get_job(job_id)
        assert job is not None
        assert job["state"] == "running"
        assert "paused" in job
        assert job["paused"] is False
        # Private control events never leak into the API snapshot.
        assert not any(k.startswith("_") for k in job)
    finally:
        transcription.control_job(job_id, "cancel")


def test_transcribe_job_queued_then_controlled():
    job_id = transcription.start_job(
        source_path="nope.wav",
        options={"engine": "whisper", "model": "tiny"},
        meta={"source_id": 1, "transcript_name": "t.txt", "project_path": "/tmp"},
        auto_start=False,
    )
    try:
        assert transcription.get_job(job_id)["state"] == "queued"

        # Pausing a queued job is not allowed (returns False).
        assert transcription.control_job(job_id, "pause") is False

        assert transcription.control_job(job_id, "start") is True
        assert transcription.get_job(job_id)["state"] == "running"

        assert transcription.control_job(job_id, "pause") is True
        assert transcription.get_job(job_id)["paused"] is True
        assert transcription.control_job(job_id, "resume") is True
        assert transcription.get_job(job_id)["paused"] is False

        assert transcription.control_job(job_id, "cancel") is True
        assert transcription.get_job(job_id)["state"] == "cancelled"
    finally:
        transcription.control_job(job_id, "cancel")


def test_transcribe_control_unknown_job():
    assert transcription.control_job("does-not-exist", "start") is False


# ----------------------------------------------------------------------
# batch autocode queue
# ----------------------------------------------------------------------


def test_autocode_batch_creates_queued_jobs_in_order():
    job_ids = autocode_jobs.start_batch(
        session_factory=_fake_session_factory,
        project_path="/tmp",
        source_ids=[1, 2, 3],
        cids=[10],
        prompt="code it",
        suggest=False,
        owner="tester",
    )
    try:
        assert len(job_ids) == 3
        jobs = [autocode_jobs.get_job(jid) for jid in job_ids]
        assert all(j is not None for j in jobs)
        assert [j["state"] for j in jobs] == ["queued", "queued", "queued"]
        assert [j["source_id"] for j in jobs] == [1, 2, 3]
        # Private control events never leak into the API snapshot.
        assert all(not any(k.startswith("_") for k in j) for j in jobs)
    finally:
        for jid in job_ids:
            autocode_jobs.control_job(jid, "cancel")


def test_autocode_batch_control_roundtrip():
    job_ids = autocode_jobs.start_batch(
        session_factory=_fake_session_factory,
        project_path="/tmp",
        source_ids=[7],
        cids=[10],
        prompt="code it",
        suggest=False,
        owner="tester",
    )
    job_id = job_ids[0]
    try:
        assert autocode_jobs.control_job(job_id, "start") is True
        assert autocode_jobs.get_job(job_id)["state"] == "running"
        assert autocode_jobs.control_job(job_id, "pause") is True
        assert autocode_jobs.get_job(job_id)["paused"] is True
        assert autocode_jobs.control_job(job_id, "resume") is True
        assert autocode_jobs.control_job(job_id, "cancel") is True
        assert autocode_jobs.get_job(job_id)["state"] == "cancelled"
        # A finished/cancelled job cannot be started again.
        assert autocode_jobs.control_job(job_id, "start") is False
    finally:
        autocode_jobs.control_job(job_id, "cancel")


def test_autocode_gate_allows_paused_worker_to_wait_and_resume():
    """The worker thread blocks while paused and proceeds after resume
    (verified via the pause event without running any real AI call)."""
    job_id = autocode_jobs.start_batch(
        session_factory=_fake_session_factory,
        project_path="/tmp",
        source_ids=[3],
        cids=[1],
        prompt="p",
        suggest=False,
        owner="t",
    )[0]
    try:
        # White-box: clear the pause event BEFORE the worker passes the gate
        # (a queued job cannot be paused via control_job; the UI dispatcher
        # pauses at the queue level instead). Start afterwards.
        with autocode_jobs._jobs_lock:
            autocode_jobs._JOBS[job_id]["_pause"].clear()
        autocode_jobs.control_job(job_id, "start")
        # While paused the worker must stay put.
        time.sleep(0.3)
        assert autocode_jobs.get_job(job_id)["state"] == "running"
        assert autocode_jobs.get_job(job_id)["paused"] is False
        # Resume releases the gate: the worker proceeds (and errors because
        # the fake session factory is never valid — proving it ran).
        autocode_jobs.control_job(job_id, "resume")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if autocode_jobs.get_job(job_id)["state"] != "running":
                break
            time.sleep(0.1)
        assert autocode_jobs.get_job(job_id)["state"] == "error"
    finally:
        autocode_jobs.control_job(job_id, "cancel")
