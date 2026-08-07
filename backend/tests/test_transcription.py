"""Tests for the transcription service + API (job lifecycle, formatting).

The heavy Whisper model is never loaded: the worker is monkeypatched while
the real threading/polling/finalize path runs end-to-end.
"""

from __future__ import annotations

import asyncio
import io
import wave

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import transcription as tr


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_wav_bytes(text_seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        frames = b"\x00\x00" * (8000 * int(text_seconds))
        w.writeframes(frames)
    return buf.getvalue()


def test_format_timestamp():
    assert tr.format_timestamp(0) == "[00:00]"
    assert tr.format_timestamp(75) == "[01:15]"
    assert tr.format_timestamp(3661) == "[01:01:01]"


def test_segments_roundtrip():
    segments = [
        {"start": 0.0, "end": 1.2, "text": "hello world"},
        {"start": 1.2, "end": 2.5, "text": "second line"},
    ]
    text = tr.segments_to_text(segments, timestamps=True)
    assert text == "[00:00] hello world\n[00:01] second line"
    parsed = tr.parse_timestamped_text(text)
    assert len(parsed) == 2
    assert parsed[0]["text"] == "hello world"
    assert parsed[1]["start"] == 1.0
    assert tr.segments_to_text(segments, timestamps=False) == "hello world\nsecond line"


async def test_transcribe_job_creates_transcript_source(client, tmp_path, monkeypatch):
    target = tmp_path / "tr.qda"
    res = await client.post(
        "/api/v1/projects", json={"project_path": str(target), "codername": "default"}
    )
    assert res.status_code == 200, res.text

    # Import a WAV source (real upload path).
    wav_bytes = make_wav_bytes()
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("clip.wav", wav_bytes, "audio/wav")},
    )
    assert res.status_code == 200, res.text
    fid = res.json()["id"]

    # Fake the Whisper worker; everything else (threading, polling, source
    # creation, audit) runs for real.
    def fake_worker(job_id: str, source_path: str, options: dict) -> None:
        tr._set_job(
            job_id,
            state="done",
            progress=100.0,
            message="done",
            segments=2,
            result=[
                {"start": 0.0, "end": 1.2, "text": "hello world"},
                {"start": 1.2, "end": 2.5, "text": "second line"},
            ],
        )

    monkeypatch.setattr(tr, "_run_worker", fake_worker)

    res = await client.post(
        "/api/v1/transcribe",
        json={"source_id": fid, "model": "tiny", "timestamps": True},
    )
    assert res.status_code == 202, res.text
    job_id = res.json()["job_id"]

    # Poll until the job is consumed (transcript source created once).
    body = {}
    for _ in range(100):
        res = await client.get(f"/api/v1/transcribe/jobs/{job_id}")
        assert res.status_code == 200
        body = res.json()
        if body.get("consumed"):
            break
        await asyncio.sleep(0.05)
    assert body.get("consumed") is True, body
    assert body["state"] == "done"
    transcript_source_id = body.get("transcript_source_id")
    assert transcript_source_id, body

    # The transcript lands in the media source's linked companion
    # ("clip.wav.txt"), which the AvCoder displays below the timeline.
    sources = (await client.get("/api/v1/sources")).json()
    transcript = next((s for s in sources if s["id"] == transcript_source_id), None)
    assert transcript is not None
    assert transcript["name"] == "clip.wav.txt"
    assert "hello world" in (transcript["fulltext"] or "")
    # No orphaned second transcript source.
    assert not any(s["name"] == "clip.txt" for s in sources)

    # The media source points at the transcript.
    media = next(s for s in sources if s["name"] == "clip.wav")
    assert media["av_text_id"] == transcript_source_id

    # The audit log recorded the transcript import.
    res = await client.get("/api/v1/audit", params={"action": "source.import"})
    assert any(r["detail"].get("transcription") for r in res.json()["rows"])

    await client.post("/api/v1/projects/close")


async def test_transcribe_requires_media_source(client, tmp_path):
    target = tmp_path / "tr2.qda"
    await client.post("/api/v1/projects", json={"project_path": str(target)})
    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("doc.txt", "hello", "text/plain")},
    )
    fid = res.json()["id"]
    res = await client.post("/api/v1/transcribe", json={"source_id": fid})
    assert res.status_code == 422
    await client.post("/api/v1/projects/close")


async def test_transcribe_status_and_settings(client, tmp_path, monkeypatch):
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    res = await client.get("/api/v1/transcribe/status")
    assert res.status_code == 200
    body = res.json()
    assert body["engines"]["whisper"] is True
    assert body["settings"]["model"] == "large-v3-turbo"

    res = await client.put(
        "/api/v1/transcribe/settings", json={"model": "base", "vad": False}
    )
    assert res.status_code == 200
    assert res.json()["model"] == "base"
    assert res.json()["vad"] is False
